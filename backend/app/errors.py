"""Uniform error handling and JSON error envelopes."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    """An error that is safe and meaningful to show to the client."""

    def __init__(
        self,
        message: str,
        status: int = 400,
        code: str = "bad_request",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details or {}


def _payload(code: str, message: str, details: dict[str, Any] | None = None):
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(err: ApiError):  # pragma: no cover - exercised via API
        log.warning("api error %s: %s", err.code, err.message)
        return jsonify(_payload(err.code, err.message, err.details)), err.status

    @app.errorhandler(HTTPException)
    def _http_error(err: HTTPException):  # pragma: no cover
        code = (err.name or "http_error").lower().replace(" ", "_")
        return jsonify(_payload(code, err.description or "Request failed")), err.code

    @app.errorhandler(Exception)
    def _unhandled(err: Exception):  # pragma: no cover
        log.exception("unhandled error")
        return (
            jsonify(
                _payload(
                    "internal_error",
                    "Внутренняя ошибка сервера. Попробуйте ещё раз.",
                )
            ),
            500,
        )
