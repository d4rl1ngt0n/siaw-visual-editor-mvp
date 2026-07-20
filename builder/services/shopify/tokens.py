from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from django.conf import settings


def _key() -> bytes:
    return hashlib.sha256(f"{settings.SECRET_KEY}:siaw-shopify-token-v1".encode("utf-8")).digest()


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        stream.extend(hashlib.sha256(key + iv + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(stream[:length])


def encrypt_token(plain: str) -> str:
    if not plain:
        return ""
    key = _key()
    iv = secrets.token_bytes(16)
    data = plain.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(key, iv, len(data))))
    mac = hmac.new(key, iv + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(iv + mac + cipher).decode("ascii")


def decrypt_token(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        raw = base64.urlsafe_b64decode(cipher_text.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Stored Shopify access token could not be decoded.") from exc
    if len(raw) < 48:
        raise ValueError("Stored Shopify access token is invalid.")
    iv, mac, cipher = raw[:16], raw[16:48], raw[48:]
    key = _key()
    expected = hmac.new(key, iv + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Stored Shopify access token could not be decrypted.")
    plain = bytes(a ^ b for a, b in zip(cipher, _keystream(key, iv, len(cipher))))
    return plain.decode("utf-8")
