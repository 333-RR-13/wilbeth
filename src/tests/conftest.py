import os
os.environ.setdefault("AUTH_MODE", "off")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import app.models  # noqa: F401 – registers all table metadata with SQLModel


@pytest.fixture(name="session")
def session_fixture():
    # StaticPool: eine einzige Connection fuer alle Threads, damit die
    # In-Memory-DB auch im Worker-Thread des TestClient sichtbar ist.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session):
    """TestClient mit auf die Test-Session umgebogener DB-Dependency.

    TestClient wird bewusst OHNE Context-Manager genutzt, damit der
    Startup-Hook (init_db gegen die echte wilbeth.db) nicht feuert.
    """
    from app.database import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
