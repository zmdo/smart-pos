"""Loopback-only model relay shared by all isolated processing nodes."""

import hashlib, hmac, json, os, secrets, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx

LOCK = threading.RLock()
SERVER = None
THREAD = None
ROUTES = {}
STOP = threading.Event()
CAPACITY = threading.BoundedSemaphore(3)
METRICS = dict(active=0, peak=0, completed=0)
ENABLED = False


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log member payloads or model credentials.

    def reply(self, status, body):
        if not isinstance(body, bytes):
            body = json.dumps({"error": {"message": body}}).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        supplied = self.headers.get("Authorization", "")
        with LOCK:
            route = next(
                (
                    r
                    for r in ROUTES.get(self.path, [])
                    if hmac.compare_digest(supplied, "Bearer " + r["token"])
                ),
                None,
            )
        if not route:
            return self.reply(401, "Invalid model relay token")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= 64 * 1024**2:
            return self.reply(413, "Invalid model request size")
        self.connection.settimeout(30)
        try:
            body = self.rfile.read(size)
        except OSError:
            return self.reply(400, "Incomplete model request")
        if len(body) != size:
            return self.reply(400, "Incomplete model request")
        while not CAPACITY.acquire(timeout=0.2):
            if STOP.is_set():
                return self.reply(503, "Model relay is stopping")
        if STOP.is_set():
            CAPACITY.release()
            return self.reply(503, "Model relay is stopping")
        with LOCK:
            METRICS["active"] += 1
            METRICS["peak"] = max(METRICS["peak"], METRICS["active"])
        try:
            cfg = route["config"]
            with httpx.Client(
                timeout=httpx.Timeout(115, connect=15), trust_env=False
            ) as client:
                response = client.post(
                    cfg["base_url"].rstrip("/") + "/chat/completions",
                    headers={
                        "Authorization": "Bearer " + cfg["api_key"],
                        "Content-Type": "application/json",
                    },
                    content=body,
                )
            self.reply(
                response.status_code,
                (
                    response.content
                    if response.status_code == 200
                    else f"Model upstream returned {response.status_code}"
                ),
            )
        except httpx.HTTPError:
            self.reply(502, "Model upstream request failed")
        finally:
            with LOCK:
                METRICS["active"] -= 1
                METRICS["completed"] += 1
            CAPACITY.release()


def start():
    global SERVER, THREAD
    with LOCK:
        if SERVER:
            return
        STOP.clear()
        SERVER = Server(
            ("127.0.0.1", int(os.environ.get("STUDIO_GATEWAY_PORT", "6011"))), Handler
        )
        THREAD = threading.Thread(
            target=SERVER.serve_forever,
            kwargs={"poll_interval": 0.2},
            daemon=True,
            name="model-relay",
        )
        THREAD.start()


def settings(cfg):
    """Stable endpoint identity; only the local bearer token changes on restart."""
    if not all(cfg.get(k) for k in ("base_url", "model", "api_key")):
        return dict(cfg)
    start()
    identity = hashlib.sha256(
        (cfg["base_url"] + "\0" + cfg["model"]).encode()
    ).hexdigest()[:24]
    path = f"/model/{identity}/v1/chat/completions"
    with LOCK:
        routes = ROUTES.setdefault(path, [])
        route = next((r for r in routes if r["config"] == cfg), None)
        if not route:
            # Keep active member snapshots valid if settings change mid-batch.
            route = {"config": dict(cfg), "token": secrets.token_urlsafe(32)}
            routes.append(route)
        return {
            **cfg,
            "base_url": f"http://127.0.0.1:{SERVER.server_port}/model/{identity}/v1",
            "api_key": route["token"],
        }


def stats():
    with LOCK:
        return dict(METRICS, limit=3)


def stop():
    global SERVER, THREAD, ENABLED
    ENABLED = False
    STOP.set()
    with LOCK:
        server, thread = SERVER, THREAD
        SERVER = THREAD = None
        ROUTES.clear()
    if server:
        server.shutdown()
        server.server_close()
    if thread:
        thread.join(timeout=2)
