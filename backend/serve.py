"""Production entrypoint: waitress WSGI server for the Flask app."""

from __future__ import annotations

import logging
import os

from waitress import serve

from app import create_app
from app.config import Config

logging.basicConfig(level=logging.INFO)
app = create_app(Config)

if __name__ == "__main__":
    host = os.getenv("HOST", Config.HOST)
    port = int(os.getenv("PORT", Config.PORT))
    print(f"Lectora is running on http://{host}:{port}")
    serve(
        app,
        host=host,
        port=port,
        threads=int(os.getenv("WAITRESS_THREADS", "12")),
        channel_timeout=900,
        ident="Lectora",
    )
