from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Common magic bytes for file type validation
_FILE_MAGIC_BYTES: dict[str, bytes] = {
    "pdf": b"%PDF",
    "docx": b"PK\x03\x04",
}


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, extra_claims: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.security.access_token_expire_minutes)
    claims = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.security.secret_key, algorithm=settings.security.jwt_algorithm)


def create_refresh_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.security.refresh_token_expire_days)
    claims = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(claims, settings.security.secret_key, algorithm=settings.security.jwt_algorithm)


def verify_token(token: str, expected_type: str = "access") -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.security.secret_key,
            algorithms=[settings.security.jwt_algorithm],
        )
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None


def generate_secure_filename(original_filename: str) -> tuple[str, str]:
    stem = Path(original_filename).stem
    safe_stem = "".join(c for c in stem if c.isalnum() or c in "._- ").strip()
    if not safe_stem:
        safe_stem = "document"
    unique_id = uuid.uuid4().hex
    ext = Path(original_filename).suffix.lower()
    secure_name = f"{safe_stem}_{unique_id}{ext}"
    return secure_name, unique_id


def validate_file_safety(file_path: Path) -> bool:
    if not file_path.exists() or not file_path.is_file():
        return False

    if file_path.stat().st_size == 0:
        return False

    try:
        with open(file_path, "rb") as f:
            header = f.read(16)

        is_pdf = header.startswith(_FILE_MAGIC_BYTES["pdf"])
        if not is_pdf:
            return False

        suspicious_patterns = [
            b"/JavaScript",
            b"/JS",
            b"/AA",
            b"/OpenAction",
            b"/Launch",
            b"/EmbeddedFile",
        ]
        f.seek(0)
        content = f.read(8192)
        for pattern in suspicious_patterns:
            if pattern in content:
                return False

        return True
    except (IOError, OSError):
        return False
