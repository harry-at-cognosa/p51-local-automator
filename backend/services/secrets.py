"""Encryption-at-rest helper for sensitive payloads (OAuth tokens, secrets).

Uses AES-GCM with a 12-byte random nonce per encryption. Output format:
``nonce (12) || ciphertext || tag (16)``. The cryptography library's AESGCM
class glues ciphertext+tag together, so the on-disk layout is:

    [12 bytes nonce][ciphertext][16 bytes tag]

The 32-byte key is read from env var ``TOKEN_ENCRYPTION_KEY`` (base64-encoded).
For dev, generate one with::

    python -c 'import os, base64; print(base64.b64encode(os.urandom(32)).decode())'

For production each deployment must generate its own. Sharing keys across
deployments breaks isolation and makes key rotation impossible.

The key is loaded lazily on first ``encrypt``/``decrypt`` call, NOT at import
time, so the module is safe to import even when the env var is unset (e.g.
during early-development boots before Gmail integration is configured).
Callers that depend on encryption hitting an unset env var get a clear
RuntimeError on the call.

Originally written for B1 (Gmail OAuth token storage). The module is
deliberately generic — it can later wrap type-4 SQL connection strings or
any other plaintext-secret-at-rest concern.
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_ENV_VAR = "TOKEN_ENCRYPTION_KEY"
_NONCE_LEN = 12   # AES-GCM standard
_KEY_LEN = 32     # AES-256

_cached_aesgcm: AESGCM | None = None


def _load_aesgcm() -> AESGCM:
    """Return a cached AESGCM instance built from the env var key."""
    global _cached_aesgcm
    if _cached_aesgcm is not None:
        return _cached_aesgcm

    raw = os.environ.get(_ENV_VAR)
    if not raw:
        raise RuntimeError(
            f"{_ENV_VAR} is not set. Generate a key with "
            f"`python -c 'import os, base64; print(base64.b64encode(os.urandom(32)).decode())'` "
            f"and set it in your .env. See backend/services/secrets.py for details."
        )
    try:
        key = base64.b64decode(raw)
    except Exception as e:
        raise RuntimeError(f"{_ENV_VAR} is not valid base64: {e}") from e
    if len(key) != _KEY_LEN:
        raise RuntimeError(
            f"{_ENV_VAR} must decode to exactly {_KEY_LEN} bytes (got {len(key)}); "
            f"regenerate with the recipe in backend/services/secrets.py."
        )
    _cached_aesgcm = AESGCM(key)
    return _cached_aesgcm


def encrypt(plaintext: str) -> bytes:
    """Encrypt a UTF-8 string. Output is `nonce || ciphertext || tag`.

    Two calls with identical plaintext produce different ciphertexts (each
    call generates a fresh random nonce). Useful for storing OAuth tokens
    where the same token may be re-encrypted on refresh.
    """
    if not isinstance(plaintext, str):
        raise TypeError("encrypt() expects a str")
    aesgcm = _load_aesgcm()
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ciphertext


def decrypt(blob: bytes) -> str:
    """Decrypt the output of :func:`encrypt` back to its original UTF-8 string.

    Raises RuntimeError if the blob is malformed (too short to contain a
    nonce + tag) or if the auth tag fails to verify (key change, tampering,
    or wrong ciphertext).
    """
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise TypeError("decrypt() expects bytes")
    blob = bytes(blob)
    if len(blob) < _NONCE_LEN + 16:
        raise RuntimeError(
            "encrypted blob too short — corrupted or not produced by secrets.encrypt()"
        )
    aesgcm = _load_aesgcm()
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except Exception as e:
        raise RuntimeError(
            "Decryption failed. Either the encrypted blob has been tampered with, "
            "or the key has changed since the blob was written. If the latter, the "
            "stored secret cannot be recovered — re-encrypt with the new key."
        ) from e
    return plaintext.decode("utf-8")


def encrypt_to_b64(plaintext: str) -> str:
    """Encrypt and return a base64 string, suitable for storing in a JSON field.

    JSON can't carry raw bytes — base64 is the standard encoding for
    embedding the output of :func:`encrypt` in a JSON config column.
    """
    return base64.b64encode(encrypt(plaintext)).decode("ascii")


def decrypt_from_b64(b64_str: str) -> str:
    """Inverse of :func:`encrypt_to_b64`."""
    if not isinstance(b64_str, str):
        raise TypeError("decrypt_from_b64() expects a str")
    try:
        blob = base64.b64decode(b64_str)
    except Exception as e:
        raise RuntimeError(f"value is not valid base64: {e}") from e
    return decrypt(blob)
