import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_greeting(client):
    resp = client.get("/api/greeting/Ada")
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "Hello, Ada!"}


def test_greeting_empty_name(client):
    resp = client.get("/api/greeting/%20")
    assert resp.status_code == 400
