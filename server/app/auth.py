import datetime as dt

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .config import JWT_SECRET, JWT_ALGO, SESSION_HOURS
from .database import get_db
from .models import User

bearer_scheme = HTTPBearer(auto_error=True)


def create_session_token(subject: str, role: str) -> str:
    payload = {
        "sub": subject,
        "role": role,
        "exp": dt.datetime.utcnow() + dt.timedelta(hours=SESSION_HOURS),
        "iat": dt.datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token")


def require_admin(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    payload = _decode(creds.credentials)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


def require_client(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = _decode(creds.credentials)
    if payload.get("role") != "client":
        raise HTTPException(status_code=403, detail="Client access required")
    user = db.get(User, payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def decode_ws_token(token: str, expected_role: str) -> dict:
    """For websocket auth, where a Bearer header isn't convenient to send."""
    payload = _decode(token)
    if payload.get("role") != expected_role:
        raise HTTPException(status_code=403, detail="Wrong token role")
    return payload
