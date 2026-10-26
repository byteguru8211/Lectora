"""Flask extension singletons."""

from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from .models import Base


class Database:
    """Thin wrapper around SQLAlchemy with a per-request session."""

    def __init__(self) -> None:
        self.engine = None
        self.session_factory: sessionmaker | None = None
        self.Session: scoped_session | None = None

    def init_app(self, app: Flask) -> None:
        url = app.config["DATABASE_URL"]
        self.engine = create_engine(
            url,
            pool_size=app.config["DB_POOL_SIZE"],
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=app.config["DB_ECHO"],
            future=True,
        )

        if self.engine.dialect.name == "postgresql":

            @event.listens_for(self.engine, "connect")
            def _set_timezone(dbapi_connection, _record):  # pragma: no cover
                with dbapi_connection.cursor() as cursor:
                    cursor.execute("SET TIME ZONE 'UTC'")
                    cursor.execute("SET statement_timeout = '60s'")

        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False
        )
        self.Session = scoped_session(self.session_factory)

        @app.teardown_appcontext
        def _remove_session(_exc):  # pragma: no cover - framework hook
            if self.Session is not None:
                self.Session.remove()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        assert self.Session is not None, "Database is not initialised"
        return self.Session()


db = Database()
