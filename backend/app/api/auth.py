"""Registration and cookie-based authentication."""

from __future__ import annotations

import re
import uuid

from flask import Blueprint, g, jsonify, request, session
from sqlalchemy import func, update
from werkzeug.security import check_password_hash, generate_password_hash

from ..errors import ApiError
from ..extensions import db
from ..models import Lecture, User

bp = Blueprint("auth", __name__, url_prefix="/api/auth")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def user_dict(user: User) -> dict:
    return {"id": str(user.id), "name": user.name, "email": user.email, "created_at": user.created_at.isoformat() if user.created_at else None}


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if len(name) < 2 or len(name) > 120:
        raise ApiError("Укажите имя длиной от 2 до 120 символов", 400, "bad_name")
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise ApiError("Укажите корректный email", 400, "bad_email")
    if len(password) < 8:
        raise ApiError("Пароль должен содержать не менее 8 символов", 400, "weak_password")

    db_session = db.session()
    try:
        if db_session.query(User).filter(func.lower(User.email) == email).first():
            raise ApiError("Аккаунт с таким email уже существует", 409, "email_exists")
        first_user = (db_session.query(func.count(User.id)).scalar() or 0) == 0
        user = User(name=name, email=email, password_hash=generate_password_hash(password))
        db_session.add(user)
        db_session.flush()
        # Preserve installations created before accounts existed.
        if first_user:
            db_session.execute(update(Lecture).where(Lecture.user_id.is_(None)).values(user_id=user.id))
        db_session.commit()
        session.clear()
        session["user_id"] = str(user.id)
        return jsonify({"user": user_dict(user)}), 201
    finally:
        db_session.close()


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    db_session = db.session()
    try:
        user = db_session.query(User).filter(func.lower(User.email) == email).first()
        if user is None or not check_password_hash(user.password_hash, password):
            raise ApiError("Неверный email или пароль", 401, "invalid_credentials")
        session.clear()
        session["user_id"] = str(user.id)
        return jsonify({"user": user_dict(user)})
    finally:
        db_session.close()


@bp.post("/logout")
def logout():
    session.clear()
    return ("", 204)


@bp.get("/me")
def me():
    raw_id = session.get("user_id")
    if not raw_id:
        raise ApiError("Требуется вход", 401, "authentication_required")
    db_session = db.session()
    try:
        user = db_session.get(User, uuid.UUID(raw_id))
        if user is None:
            session.clear()
            raise ApiError("Требуется вход", 401, "authentication_required")
        return jsonify({"user": user_dict(user)})
    finally:
        db_session.close()
