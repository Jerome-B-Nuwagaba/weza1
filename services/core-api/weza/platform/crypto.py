"""Cryptographic primitives: envelope encryption for the Identity Vault, blind indexes, OTP hashing,
password hashing, TOTP and signed tokens (TSD §12–13, §69)."""

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from weza.config import get_settings

_ph = PasswordHasher()


def _master_key() -> bytes:
    value = get_settings().vault_master_key
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError:
        raw = value.encode()  # platform-generated secrets may not be base64; still high-entropy
    return hashlib.sha256(raw).digest()  # normalise to 32 bytes


def encrypt_record(fields: dict) -> tuple[bytes, bytes]:
    """Encrypt a dict with a fresh data key; return (ciphertext, wrapped data key)."""
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ct = nonce + AESGCM(dek).encrypt(nonce, json.dumps(fields).encode(), None)
    wnonce = os.urandom(12)
    wrapped = wnonce + AESGCM(_master_key()).encrypt(wnonce, dek, b"weza-dek")
    return ct, wrapped


def decrypt_record(ct: bytes, wrapped: bytes) -> dict:
    dek = AESGCM(_master_key()).decrypt(wrapped[:12], wrapped[12:], b"weza-dek")
    return json.loads(AESGCM(dek).decrypt(ct[:12], ct[12:], None))


def encrypt_bytes(data: bytes) -> tuple[bytes, bytes]:
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ct = nonce + AESGCM(dek).encrypt(nonce, data, None)
    wnonce = os.urandom(12)
    return ct, wnonce + AESGCM(_master_key()).encrypt(wnonce, dek, b"weza-dek")


def decrypt_bytes(ct: bytes, wrapped: bytes) -> bytes:
    dek = AESGCM(_master_key()).decrypt(wrapped[:12], wrapped[12:], b"weza-dek")
    return AESGCM(dek).decrypt(ct[:12], ct[12:], None)


def blind_index(kind: str, value: str) -> str:
    """Deterministic keyed hash for lookups without storing the identifier in clear."""
    key = get_settings().blind_index_key.encode()
    return hmac.new(key, f"{kind}:{value.strip().upper()}".encode(), hashlib.sha256).hexdigest()


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_otp(code: str, salt: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{salt}:{code}".encode(), hashlib.sha256).hexdigest()


def hmac_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def totp_new_secret() -> str:
    return pyotp.random_base32()


def totp_verify(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="WEZA")


def sign_jwt(claims: dict, minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "iat": now, "exp": now + timedelta(minutes=minutes), "iss": "weza"}
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")


def verify_jwt(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"], issuer="weza")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()
