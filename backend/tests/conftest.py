from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.db import Base, get_db

# Registers every model on Base.metadata (needed for the teardown drop_all below —
# schema creation itself goes through real migrations). See app/models.py. Must be
# imported as `from app import models`, not `import app.models` — the latter binds
# the local name `app` to the app *package*, clobbering `from app.main import app`
# below (the FastAPI instance) since both bind the same name `app`.
from app import models as _registered_models  # noqa: F401
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parent.parent

settings = get_settings()
engine = create_engine(settings.test_database_url)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Builds the test schema by running real Alembic migrations (not
    Base.metadata.create_all) so tests catch drift between models and migrations —
    e.g. the patient_code_seq that only the migration knows to create."""
    command.upgrade(_alembic_config(), "head")
    yield
    Base.metadata.drop_all(bind=engine)
    # Not part of Base.metadata — drop it too, or the next run's upgrade("head")
    # thinks the schema already exists and skips recreating the dropped tables.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture()
def db_session():
    """A session whose outer transaction always rolls back, even if the code under
    test calls db.commit() — commits only close a SAVEPOINT, per the SQLAlchemy
    'joining a session into an external transaction' pattern."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(session, transaction):
        if transaction.nested and not transaction._parent.nested:
            session.begin_nested()

    try:
        yield session
    finally:
        session.close()
        # A test that itself calls db_session.rollback() after a flush failure (to
        # keep using the session) can leave this outer transaction already ended —
        # only roll it back here if that didn't already happen.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def outside_session():
    """A completely independent connection/session, outside db_session's SAVEPOINT-
    wrapped transaction. Used to prove that db.commit() calls made through the app
    during a test never actually reach a separate connection — i.e. the outer
    transaction really is uncommitted, not just "rolled back at teardown by luck"."""
    connection = engine.connect()
    session = TestingSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        connection.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
