import json, os, secrets, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PORTRAIT_DATA", "/root/autodl-fs/portrait-studio"))
for folder in ("models", "jobs", "logs"):
    (DATA / folder).mkdir(parents=True, exist_ok=True)
LOCK = threading.RLock()
PATH = DATA / "settings.json"
def load():
    with LOCK:
        if not PATH.exists():
            save({"api_key": "", "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "access_code": secrets.token_urlsafe(12)})
        return json.loads(PATH.read_text())
def save(value):
    with LOCK:
        tmp = PATH.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(value, f)
        os.replace(tmp, PATH)

