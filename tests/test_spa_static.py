"""SPA static serving: deep links must not fall back to the home page."""


def test_root_serves_home_page(test_client):
    response = test_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "node_ids: [0, 3]" in response.text


def test_billing_serves_prerendered_page(test_client):
    response = test_client.get("/billing")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "node_ids: [0, 9]" in response.text
    assert "node_ids: [0, 3]" not in response.text


def test_login_serves_spa_shell(test_client):
    response = test_client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "kit.start" in response.text
    assert "node_ids:" not in response.text


def test_register_serves_spa_shell(test_client):
    response = test_client.get("/register")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "kit.start" in response.text
    assert "node_ids:" not in response.text
