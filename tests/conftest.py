import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config, database, storage
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    """Fresh database and storage folder for every test."""
    tmp = Path(tempfile.mkdtemp())
    engine = create_engine(
        f"sqlite:///{tmp / 'test.db'}", connect_args={"check_same_thread": False}
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    database.Base.metadata.create_all(engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = override_get_db
    monkeypatch.setattr(config, "STORAGE_DIR", tmp / "storage")
    (tmp / "storage").mkdir()

    with TestClient(app) as c:  # note: lifespan creates tables on the real engine, harmless
        yield c
    app.dependency_overrides.clear()


def make_user(client, name="Rawan", email="rawan@example.com") -> dict:
    r = client.post("/users", json={"name": name, "email": email})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def auth(client):
    user = make_user(client)
    return {"X-API-Key": user["api_key"]}
