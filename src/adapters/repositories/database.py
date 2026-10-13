"""Engine and session factory."""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.repositories.orm import metadata, start_mappers


def create_db_engine(url: str, echo: bool = False) -> Engine:
    kwargs: dict = {"echo": echo}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    return create_engine(url, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    start_mappers()
    return sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Creates all tables directly (tests only; real databases use Alembic migrations)."""
    metadata.create_all(engine)


def drop_schema(engine: Engine) -> None:
    metadata.drop_all(engine)


def ping(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
