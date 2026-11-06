from fastapi.testclient import TestClient
from app import app, TOKEN


def test_public_https_login_preserves_secure_session_behind_proxy():
    origin='https://uu55868-793909b1c426.weste.seetacloud.com:8443'
    client=TestClient(app,base_url=origin)
    try:
        response=client.post('/api/login',headers={'Origin':origin,'X-Forwarded-Proto':'http'},json={'token':TOKEN})
        assert response.status_code==200
        assert all(cookie.secure for cookie in client.cookies.jar)
        assert client.get('/api/batches').status_code==200
    finally:
        client.close()
