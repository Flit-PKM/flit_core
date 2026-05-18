"""OpenAPI schema documentation tests."""

from openapi_augment import API_TAG_DESCRIPTIONS
from main import app


def _fresh_schema() -> dict:
    app.openapi_schema = None
    return app.openapi()


def test_openapi_json_available(test_client):
    response = test_client.get("/openapi.json")
    assert response.status_code == 200
    assert "openapi" in response.json()


def test_openapi_description_includes_authentication():
    schema = _fresh_schema()
    desc = schema.get("info", {}).get("description", "")
    assert "Authentication" in desc
    assert "POST /api/auth/login-json" in desc


def test_api_tags_have_descriptions():
    schema = _fresh_schema()
    tag_map = {
        t["name"]: t.get("description", "")
        for t in schema.get("tags", [])
        if isinstance(t, dict) and t.get("name")
    }
    for name in API_TAG_DESCRIPTIONS:
        assert name in tag_map, f"Missing tag {name}"
        assert tag_map[name], f"Empty description for tag {name}"


def test_health_endpoint_tagged():
    schema = _fresh_schema()
    health = schema["paths"]["/api/health"]["get"]
    assert health.get("tags") == ["health"]


def test_note_get_documents_404():
    schema = _fresh_schema()
    op = schema["paths"]["/api/notes/{note_id}"]["get"]
    responses = op.get("responses", {})
    assert "404" in responses
    assert "Note not found" in responses["404"]["description"]


def test_register_is_public():
    schema = _fresh_schema()
    op = schema["paths"]["/api/auth/register"]["post"]
    assert not op.get("security")


def test_http_bearer_scheme_documented():
    schema = _fresh_schema()
    bearer = schema["components"]["securitySchemes"]["HTTPBearer"]
    assert bearer["scheme"] == "bearer"
    assert "JWT" in bearer["description"]
    assert "connect/exchange" in bearer["description"]
