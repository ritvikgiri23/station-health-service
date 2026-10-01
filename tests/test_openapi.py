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
