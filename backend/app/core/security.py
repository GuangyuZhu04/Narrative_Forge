import os
import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from app.core.config import settings


def _derive_key(master_key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    return kdf.derive(master_key.encode())


def encrypt_api_key(api_key: str) -> str:
    salt = os.urandom(16)
    key = _derive_key(settings.SECRET_KEY, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, api_key.encode(), None)
    return base64.urlsafe_b64encode(salt + nonce + ciphertext).decode()


def decrypt_api_key(encrypted: str) -> str:
    payload = base64.urlsafe_b64decode(encrypted.encode())
    salt, nonce, ciphertext = payload[:16], payload[16:28], payload[28:]
    key = _derive_key(settings.SECRET_KEY, salt)
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode()
