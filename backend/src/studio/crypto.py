"""Encryption at rest for OAuth tokens.

Fernet is AES-128-CBC with an HMAC-SHA256 tag: a ciphertext that was tampered
with fails to decrypt instead of decrypting to garbage. MultiFernet adds key
rotation: the first key encrypts, every key decrypts. To rotate, put a new key
first, re-encrypt with `rotate`, then drop the old key.

The keys live in the environment, never in the database, so a stolen database
dump on its own reveals no tokens.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

from studio.config import get_settings


class NotConfigured(Exception):
    """No TOKEN_ENCRYPTION_KEYS: features that store tokens stay switched off."""


@lru_cache
def _fernet() -> MultiFernet:
    keys = [k.strip() for k in (get_settings().token_encryption_keys or "").split(",") if k.strip()]
    if not keys:
        raise NotConfigured
    return MultiFernet([Fernet(k) for k in keys])


def configured() -> bool:
    try:
        _fernet()
    except NotConfigured:
        return False
    return True


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()


def rotate(ciphertext: bytes) -> bytes:
    """The same plaintext, encrypted again with the newest key."""
    return _fernet().rotate(ciphertext)
