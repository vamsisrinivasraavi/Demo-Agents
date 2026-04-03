"""
Symmetric encryption for sensitive fields stored in MongoDB.

Uses Fernet (AES-128-CBC with HMAC-SHA256) from the cryptography library.
The encryption key is derived from JWT_SECRET_KEY via PBKDF2 — this means
no additional secret to manage, but changing JWT_SECRET_KEY will invalidate
all encrypted passwords (which is acceptable for this use case).

Usage:
    from app.core.encryption import encrypt_value, decrypt_value

    encrypted = encrypt_value("my_db_password")
    original  = decrypt_value(encrypted)
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _get_fernet() -> Fernet:
    """
    Derive a Fernet key from JWT_SECRET_KEY.
    Fernet requires a 32-byte base64-encoded key.
    """
    settings = get_settings()
    # Derive 32 bytes from the secret via SHA-256
    key_bytes = hashlib.sha256(settings.JWT_SECRET_KEY.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value. Returns a Fernet token as a string."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted: str) -> str:
    """Decrypt a Fernet token back to the original string."""
    f = _get_fernet()
    return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")