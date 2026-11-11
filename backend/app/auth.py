"""Password hashing (stdlib scrypt), JWT tokens, and the current-user / admin-only dependencies."""
import hashlib
import hmac
import logging
import os
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import User, get_db, now

JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_hex(32)
if not os.getenv("JWT_SECRET"):
    logging.warning("JWT_SECRET not set: using a random one, so logins reset on every restart.")
TOKEN_TTL = timedelta(days=7)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest)


def create_token(user: User) -> str:
    # Role is NOT trusted from the token; it is re-read from the DB on every request.
    return jwt.encode({"sub": str(user.id), "exp": now() + TOKEN_TTL}, JWT_SECRET, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(401, "Please log in.")
    try:
        user_id = int(jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Your session has expired. Please log in again.")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Account not found. Please log in again.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only.")
    return user
