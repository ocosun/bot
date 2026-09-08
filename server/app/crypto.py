import secrets

import bcrypt
from cryptography.fernet import Fernet

from .config import FERNET_KEY

_fernet = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)


def new_login_token() -> str:
    """Cryptographically random login token, given to a client exactly once."""
    return secrets.token_urlsafe(32)


def hash_login_token(token: str) -> str:
    return bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()


def verify_login_token(token: str, token_hash: str) -> bool:
    try:
        return bcrypt.checkpw(token.encode(), token_hash.encode())
    except ValueError:
        return False


def encrypt_secret(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
