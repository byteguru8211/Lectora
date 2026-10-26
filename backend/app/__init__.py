"""Application factory for the Lectora backend."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from .api import lectures as lectures_api
from .api import qa as qa_api
from .api import search as search_api
from .api import system as system_api
from .config import Config
from .errors import register_error_handlers
from .extensions import db
from .schema import ensure_schema
from .services.jobs import JobRunner
from .services.media import MediaService
from .services.pipeline import init_pipeline
from .services.storage import Storage

log = logging.getLogger(__name__)

__version__ = "1.0.0"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    for noisy in ("urllib3", "sentence_transformers", "transformers", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def create_app(config_object: type[Config] = Config, overrides: dict | None = None) -> Flask:
    configure_logging(config_object.LOG_LEVEL)
    app = Flask(__name__, static_folder=None, static_url_path="")
    app.config.from_object(config_object)
    if overrides:
        app.config.update(overrides)
    app.config["APP_VERSION"] = __version__
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False

    db.init_app(app)

    storage = Storage(app.config["STORAGE_DIR"], app.config["MEDIA_DIR"])
    app.extensions["storage"] = storage
    app.extensions["media"] = MediaService()

    pipeline = init_pipeline(storage)
    app.extensions["pipeline"] = pipeline

    try:
        ensure_schema(db.engine)
    except Exception as exc:  # pragma: no cover - misconfiguration
        log.error(
            "Не удалось подключиться к PostgreSQL (%s). Проверьте DATABASE_URL и запущен ли сервер.",
            exc,
        )
        raise

    runner = JobRunner(db, pipeline, threads=app.config["WORKER_THREADS"])
    app.extensions["job_runner"] = runner
    if app.config["START_WORKER"]:
        runner.start()

    register_error_handlers(app)
    app.register_blueprint(lectures_api.bp)
    app.register_blueprint(search_api.bp)
    app.register_blueprint(qa_api.bp)
    app.register_blueprint(system_api.bp)

    if app.config.get("WARMUP", True):
        threading.Thread(target=_warm_up, name="lectora-warmup", daemon=True).start()

    _register_middleware(app)
    _register_frontend(app)
    log.info("Lectora %s ready (env=%s)", __version__, app.config["ENV"])
    return app


def _warm_up() -> None:
    """Load heavy models in the background so the first upload is not a mystery."""
    try:
        from .services.asr import AsrService
        from .services.embeddings import embeddings
        from .services.reranker import reranker

        log.info("warming up models…")
        # Search models first: they make the first query feel instant, while the
        # (slower) ASR model is only needed when a lecture is uploaded.
        embeddings.warm_up()
        reranker.warm_up()
        AsrService().warm_up()
        log.info("models are warm")
    except Exception:  # pragma: no cover - never block the app
        log.exception("warm-up failed (continuing)")


def _register_middleware(app: Flask) -> None:
    @app.before_request
    def _start_timer():
        g.request_started = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

    @app.after_request
    def _finalise(response):
        elapsed_ms = int((time.perf_counter() - getattr(g, "request_started", time.perf_counter())) * 1000)
        response.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Permissions-Policy"] = "microphone=(), camera=()"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = response.headers.get(
                "Cache-Control", "no-store"
            )
        if request.method != "OPTIONS" and not request.path.startswith("/api/lectures/"):
            log.info("%s %s -> %s (%d ms)", request.method, request.path, response.status_code, elapsed_ms)
        return response

    @app.get("/api")
    def api_index():
        return jsonify(
            {
                "name": "Lectora API",
                "version": app.config["APP_VERSION"],
                "docs": "/api/system/info",
            }
        )


def _register_frontend(app: Flask) -> None:
    dist = Path(app.config["FRONTEND_DIST"])
    index = dist / "index.html"
    if not index.is_file():
        log.info("frontend build not found (%s) — API-only mode", dist)
        return

    @app.get("/")
    def spa_index():
        return send_from_directory(dist, "index.html")

    @app.get("/<path:path>")
    def spa_assets(path: str):
        candidate = (dist / path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            return ("Not found", 404)
        if candidate.is_file():
            response = send_from_directory(dist, path)
            if path.startswith("assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response
        # client-side routes (/lectures/<id>) fall back to index.html
        if "." not in Path(path).name:
            return send_from_directory(dist, "index.html")
        return ("Not found", 404)


def create_production_app() -> Flask:
    return create_app(Config)


if __name__ == "__main__":  # pragma: no cover
    create_app(Config).run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        threaded=True,
    )
