from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# "disable" (the default) is fine for a local Postgres on localhost — no
# network segment for sslmode to protect. Set DATABASE_SSL_MODE to "require"
# or "verify-full" the moment the database isn't on the same host as the
# app anymore; nothing else here needs to change.
engine = create_engine(
    settings.database_url, pool_pre_ping=True, connect_args={"sslmode": settings.database_ssl_mode}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared metadata for every module's models.py — Alembic autogenerate reads
    Base.metadata, so each module must import its models where env.py can see them."""


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
