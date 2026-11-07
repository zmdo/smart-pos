import copy, json, os, tempfile, threading, time, unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import httpx
from test_studio import sample
from studio import config, model_client, model_gateway, parallel, store, workflow
from studio.common import job_dir, now, read, save, sha
import app


class ModelRoutingTests(unittest.TestCase):
    def request(self):
        response = httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )
        client = unittest.mock.MagicMock()
        client.__enter__.return_value.post.return_value = response
        return client

    def test_member_uses_snapshot_and_parent_relay(self):
        original = dict(
            base_url="https://snapshot.test/v1", model="snapshot-model", api_key="old"
        )
        relay = dict(
            base_url="http://127.0.0.1:6011/model/test/v1",
            model="snapshot-model",
            api_key="local",
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.json"
            save(path, relay)
            save(path.with_name("settings.json"), {"model": original})
            client = self.request()
            with patch.dict(os.environ, STUDIO_MODEL_SETTINGS=str(path)), patch.object(
                config, "load", side_effect=AssertionError("must use member snapshot")
            ), patch.object(model_client.httpx, "Client", return_value=client):
                value, _ = model_client.ask("system", "prompt")
            call = client.__enter__.return_value.post.call_args
            self.assertEqual(value, {"ok": True})
            self.assertEqual(call.args[0], relay["base_url"] + "/chat/completions")
            self.assertEqual(call.kwargs["json"]["model"], original["model"])
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer local")

    def test_only_server_owner_starts_relay_for_interactive_requests(self):
        cfg = dict(base_url="https://provider.test/v1", model="test", api_key="private")
        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.dict(
                os.environ, {}, clear=True
            ), patch.object(config, "load", return_value={"model": cfg}), patch.object(
                model_gateway, "ENABLED", enabled
            ), patch.object(
                model_gateway, "settings", return_value=cfg
            ) as settings, patch.object(
                model_client.httpx, "Client", return_value=self.request()
            ):
                model_client.ask("system", "prompt")
                self.assertEqual(settings.call_count, int(enabled))


class ParallelTests(unittest.TestCase):
    def test_phase_waits_for_actual_displayed_images_not_just_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            save(
                path / "display/summary.json",
                [
                    {
                        "asset_id": "a1",
                        "status": "needs_review",
                        "reason": "common_frame_would_cut_confirmed_head_feet_or_torso",
                    }
                ],
            )
            self.assertFalse(workflow.has_phase_images(path))
            self.assertFalse(workflow.has_phase_images(None))
            save(
                path / "display/summary.json",
                [{"asset_id": "a1", "status": "displayed"}],
            )
            self.assertTrue(workflow.has_phase_images(path))

    def setUp(self):
        store.initialize()
        workflow.STOPPING.clear()
        self.parent = store.create("parallel-test.zip", config.snapshot())["id"]
        self.base = job_dir(self.parent) / "fixture"
        self.groups, self.assets = [], []
        for i, directory in enumerate(("甲店/同名", "甲店/乙", "乙店/同名"), 1):
            shop, member = directory.split("/")
            self.groups.append(
                dict(store=shop, member=member, coach="", directory=directory)
            )
            relative = "私教会员案例项目/" + directory + "/photo.jpg"
            f = self.base / "dataset/input" / relative
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(f"image-{i}".encode())
            (f.parent / "report.txt").write_text("会员资料")
            self.assets.append(
                dict(
                    id=f"a{i:04d}",
                    path=relative,
                    directory=directory,
                    store=shop,
                    member=member,
                    coach="",
                    source_sha256=sha(f),
                    **{"class": {}},
                )
            )
        save(
            self.base / "dataset/job.json",
            dict(groups=self.groups, assets=self.assets, excluded=[]),
        )
        store.set_node(
            self.parent,
            dict(key="intake", name="整理", path=str(self.base), status="complete"),
        )

    def finish(self, jid):
        child = store.get(jid)
        entered = parallel.completed(child, "intake")
        job = read(Path(entered["path"]) / "dataset/job.json")
        group = job["groups"][0]
        m = sample()
        m.update(
            directory=group["directory"], store=group["store"], photos=[], sources=[]
        )
        m["profile"] = dict(name=group["member"], gender="", coach="")
        m["_engine"]["rows"] = []
        for asset in job["assets"]:
            path = Path(entered["path"]) / "dataset/input" / asset["path"]
            mid = store.media(jid, path)
            m["sources"].append(dict(asset_id=asset["id"], media=mid))
            m["_engine"]["rows"].append(dict(asset_id=asset["id"], group_id="m001"))
        store.save_review(jid, {"members": [m]}, child["review_version"])
        store.patch(jid, status="review", progress=100, resolved_profile=m["profile"])

    def test_partition_preserves_member_boundaries_ids_and_documents(self):
        children = parallel.partition(self.parent, self.base)
        self.assertEqual(len(children), 3)
        for child, group, asset in zip(children, self.groups, self.assets):
            path = (
                Path(parallel.completed(child, "intake")["path"]) / "dataset/job.json"
            )
            actual = read(path)
            self.assertEqual(actual["groups"], [group])
            self.assertEqual(actual["assets"], [asset])
            self.assertEqual(len(list(path.parent.rglob("photo.jpg"))), 1)
            self.assertEqual(len(list(path.parent.rglob("report.txt"))), 1)
        self.assertEqual(
            [c["id"] for c in parallel.partition(self.parent, self.base)],
            [c["id"] for c in children],
        )
        visible = {j["id"] for j in store.listing()}
        self.assertFalse(visible.intersection(c["id"] for c in children))

    def test_saved_classification_and_splits_are_reused_without_cross_member_assets(
        self,
    ):
        original = read(self.base / "dataset/job.json")
        for a in original["assets"]:
            a["class"] = dict(kind="body_scan", phase="both")
        save(self.base / "dataset/job.json", original)
        cls, splits = self.base / "classification", self.base / "split"
        save(
            cls / "classification-comparison.json",
            [
                dict(asset_id=a["id"], source="old", qwen=a["class"])
                for a in original["assets"]
            ],
        )
        split_assets = []
        for asset in original["assets"]:
            a = copy.deepcopy(asset)
            a.update(
                id=a["id"] + "_L",
                path=a["path"].replace("photo", "left"),
                pair_source={"parent_asset_id": asset["id"]},
            )
            f = splits / "dataset/input" / a["path"]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"split")
            split_assets.append(a)
        save(splits / "dataset/job.json", {"assets": split_assets})
        for key, path in (("classify", cls), ("split", splits)):
            store.set_node(
                self.parent, dict(key=key, status="complete", path=str(path))
            )
        children = parallel.partition(self.parent, self.base)
        child = children[0]
        source = Path(parallel.completed(child, "intake")["path"]) / "dataset/job.json"
        audit = read(
            Path(parallel.completed(child, "classify")["path"])
            / "classification-comparison.json"
        )
        self.assertEqual([r["asset_id"] for r in audit], ["a0001"])
        self.assertTrue(Path(audit[0]["source"]).exists())
        rows = workflow.combine_sources(
            source, splits, ["a0001"], job_dir(child["id"]) / "combined"
        )
        self.assertEqual([r["id"] for r in rows], ["a0001_L"])
        self.assertEqual(rows[0]["directory"], self.groups[0]["directory"])

    def test_two_members_overlap_and_merged_media_remains_accessible(self):
        lock = threading.Lock()
        barrier = threading.Barrier(2)
        active = peak = calls = 0

        def work(jid):
            nonlocal active, peak, calls
            store.patch(jid, status="processing")
            with lock:
                active += 1
                peak = max(peak, active)
                calls += 1
                number = calls
            if number <= 2:
                barrier.wait(timeout=5)
            self.finish(jid)
            with lock:
                active -= 1

        with patch.object(workflow, "preprocess_member", side_effect=work):
            parallel.run(self.parent)
        self.assertEqual(peak, 2)
        result = store.review(self.parent)
        self.assertEqual([m["id"] for m in result["members"]], ["m001", "m002", "m003"])
        for m in result["members"]:
            self.assertEqual(m["_engine"]["rows"][0]["group_id"], m["id"])
            self.assertTrue(
                store.media_file(self.parent, m["sources"][0]["media"]).exists()
            )
        public = app.public_job(store.get(self.parent))["preprocessing"]
        self.assertEqual([g["status"] for g in public["groups"]], ["complete"] * 3)
        self.assertNotIn(str(job_dir(self.parent)), json.dumps(public))

    def test_failed_member_does_not_stop_others_and_retry_reuses_successes(self):
        calls = Counter()

        def work(jid):
            group = store.get(jid)["member_group"]["id"]
            calls[group] += 1
            if group == "m002" and calls[group] == 1:
                raise RuntimeError("controlled test failure")
            self.finish(jid)

        with patch.object(workflow, "preprocess_member", side_effect=work):
            with self.assertRaisesRegex(RuntimeError, "1 位会员"):
                parallel.run(self.parent)
            self.assertEqual(
                [c["status"] for c in store.children(self.parent)],
                ["review", "failed", "review"],
            )
            parallel.run(self.parent)
        self.assertEqual(dict(calls), {"m001": 1, "m002": 2, "m003": 1})
        self.assertEqual(len(store.review(self.parent)["members"]), 3)

    def test_concurrent_node_updates_keep_every_branch(self):
        def write(i):
            for status in ("running", "complete"):
                store.set_node(
                    self.parent, dict(key=f"branch-{i}", status=status, name=str(i))
                )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(12)))
        rows = [
            n for n in store.get(self.parent)["nodes"] if n["key"].startswith("branch-")
        ]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(n["status"] == "complete" for n in rows))

    def test_gpu_limit_and_stop_while_waiting(self):
        a, b = [c["id"] for c in parallel.partition(self.parent, self.base)[:2]]
        started, release = threading.Event(), threading.Event()

        def hold(out):
            started.set()
            release.wait(5)
            out.mkdir(parents=True)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(workflow.node, a, "standardize", hold)
                self.assertTrue(started.wait(5))
                forbidden = unittest.mock.Mock()
                second = pool.submit(workflow.node, b, "standardize", forbidden)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if any(
                        n["key"] == "standardize" and n["status"] == "waiting"
                        for n in store.get(b)["nodes"]
                    ):
                        break
                    time.sleep(0.01)
                else:
                    self.fail("second member did not wait for GPU")
                workflow.STOPPING.set()
                with self.assertRaisesRegex(RuntimeError, "停止"):
                    second.result(timeout=3)
                forbidden.assert_not_called()
                release.set()
                first.result(timeout=3)
        finally:
            release.set()
            workflow.STOPPING.clear()
        self.assertTrue(workflow.RESOURCES["gpu"].acquire(blocking=False))
        workflow.RESOURCES["gpu"].release()


class ModelGatewayTests(unittest.TestCase):
    def test_auth_relay_and_global_three_request_limit(self):
        model_gateway.stop()
        active = peak = 0
        lock = threading.Lock()
        saturated, release = threading.Event(), threading.Event()
        observed = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                nonlocal active, peak
                payload = self.rfile.read(int(self.headers["Content-Length"]))
                with lock:
                    observed.append(
                        (
                            self.path,
                            self.headers.get("Authorization"),
                            json.loads(payload),
                        )
                    )
                    active += 1
                    peak = max(peak, active)
                    if active == 3:
                        saturated.set()
                release.wait(8)
                with lock:
                    active -= 1
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = model_gateway.settings(
                dict(
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    model="test-model",
                    api_key="private-upstream-key",
                )
            )
            endpoint = cfg["base_url"] + "/chat/completions"
            self.assertEqual(httpx.post(endpoint, json={}).status_code, 401)
            self.assertFalse(observed)

            def call(i):
                return httpx.post(
                    endpoint,
                    json={"index": i},
                    headers={"Authorization": "Bearer " + cfg["api_key"]},
                    timeout=10,
                ).status_code

            with ThreadPoolExecutor(max_workers=6) as pool:
                jobs = [pool.submit(call, i) for i in range(6)]
                self.assertTrue(saturated.wait(5))
                self.assertEqual(active, 3)
                release.set()
                self.assertEqual([j.result(timeout=10) for j in jobs], [200] * 6)
            self.assertEqual(peak, 3)
            self.assertEqual(len(observed), 6)
            self.assertTrue(
                all(
                    p == "/v1/chat/completions"
                    and token == "Bearer private-upstream-key"
                    for p, token, body in observed
                )
            )
            self.assertEqual(
                sorted(body["index"] for p, token, body in observed), list(range(6))
            )
            updated = model_gateway.settings(
                dict(
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    model="test-model",
                    api_key="replacement-key",
                )
            )
            self.assertEqual(updated["base_url"], cfg["base_url"])
            self.assertEqual(call(6), 200)  # Existing member snapshot still works.
            response = httpx.post(
                endpoint,
                json={"index": 7},
                headers={"Authorization": "Bearer " + updated["api_key"]},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [r[1] for r in observed[-2:]],
                ["Bearer private-upstream-key", "Bearer replacement-key"],
            )
        finally:
            release.set()
            model_gateway.stop()
            server.shutdown()
            server.server_close()
            thread.join(2)
