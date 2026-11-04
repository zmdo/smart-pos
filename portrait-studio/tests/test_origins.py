import pytest
from origins import origin_key, is_allowed_origin
from fastapi.testclient import TestClient
from app import app, AUTH_SECRET

PUBLIC = "https://u55868-7936f251bb5f.westd.seetacloud.com:8443"
HOST = "u55868-7936f251bb5f.westd.seetacloud.com"

def test_public_origin_survives_proxy_port_removal():
    assert is_allowed_origin(PUBLIC, "http", HOST)
    assert is_allowed_origin(PUBLIC, "https", HOST)
    assert is_allowed_origin(PUBLIC, "http", "127.0.0.1:6006")

def test_direct_same_origin_and_default_port():
    assert is_allowed_origin("http://localhost:6006", "http", "localhost:6006")
    assert is_allowed_origin("https://example.com:443", "https", "example.com")
    assert not is_allowed_origin("http://example.com", "https", "example.com")

@pytest.mark.parametrize("origin", [
    "https://attacker.example", "null", "https://"+HOST+":8444",
    "http://"+HOST+":8443", PUBLIC+".attacker.example",
    PUBLIC+"/evil", "https://user:pass@"+HOST+":8443",
    PUBLIC+",https://attacker.example", "https://[bad", PUBLIC+"\n",
])
def test_untrusted_or_malformed_origin_denied(origin):
    assert not is_allowed_origin(origin, "http", "127.0.0.1:6006")

def test_proxy_browser_login_sets_working_session():
    # The browser sends the public port, while the upstream sees a portless Host.
    c = TestClient(app, base_url="https://"+HOST)
    response = c.post("/api/login", headers={"Origin": PUBLIC}, json={"code": AUTH_SECRET})
    assert response.status_code == 200
    assert c.get("/api/settings").status_code == 200
    # A post-login mutation from this same public origin must also work.
    assert c.post("/api/logout", headers={"Origin": PUBLIC}).status_code == 200
    assert c.get("/api/settings").status_code == 401
    c.close()

def test_host_forwarding_does_not_authorize_external_origin():
    c = TestClient(app, base_url="https://"+HOST)
    response = c.post("/api/login", headers={
        "Origin": "https://attacker.example",
        "X-Forwarded-Host": "attacker.example",
    }, json={"code": AUTH_SECRET})
    assert response.status_code == 403
    c.close()

