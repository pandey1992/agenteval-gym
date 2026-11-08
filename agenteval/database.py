"""SQLite engine configuration and schema setup."""
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from agenteval.models import Base

def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("M1 supports SQLite URLs only.")
    engine = create_engine(database_url, connect_args={"check_same_thread": False, "timeout": 5})
    @event.listens_for(engine, "connect")
    def set_pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
    in_memory = url.database in (None, "", ":memory:") or url.query.get("mode") == "memory"
    if not in_memory:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine

def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)

def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
