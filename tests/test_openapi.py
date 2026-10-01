from flask.testing import FlaskClient
from openapi_spec_validator import validate


def test_generated_openapi_document_is_valid(client: FlaskClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json
    assert document is not None
    validate(document)
    assert "/livez" in document["paths"]
    assert "/readyz" in document["paths"]


def test_swagger_ui_is_served(client: FlaskClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert b"swagger-ui" in response.data


def test_the_api_key_security_scheme_is_documented_on_protected_operations(
    client: FlaskClient,
) -> None:
    document = client.get("/openapi.json").json
    assert document is not None

    assert document["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    ingest = document["paths"]["/health-reports"]["post"]
    assert ingest["security"] == [{"ApiKeyAuth": []}]
    assert {"401", "403", "422"} <= set(ingest["responses"])
    assert "security" not in document["paths"]["/livez"]["get"]
