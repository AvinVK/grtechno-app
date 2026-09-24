"""Encrypts a handful of contact-detail columns (phone, email, street address) so the raw
SQLite file can't be read as plain text if it ever leaks. Kept separate from SECRET_KEY:
that one only signs session cookies and is fine to rotate or regenerate per-server, but this
key must travel WITH the data - lose it or mismatch it and every encrypted value already
written becomes permanently unreadable. Set FIELD_ENCRYPTION_KEY in .env for anything beyond
local dev, and use the exact same value on every server that reads this database."""

import os

from cryptography.fernet import Fernet, InvalidToken

from .config import BASE_DIR
from .extensions import db


def _persistent_field_key() -> bytes:
    env_key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if env_key:
        return env_key.strip().encode()
    path = BASE_DIR / "instance" / "field_encryption_key"
    if not path.exists():
        path.write_text(Fernet.generate_key().decode())
    return path.read_text().strip().encode()


_fernet = Fernet(_persistent_field_key())


class EncryptedText(db.TypeDecorator):
    """A text column that is encrypted at rest. Application code reads and writes plain
    strings as usual; only the bytes actually stored in the database are encrypted."""

    impl = db.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:
            return value
        return _fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if not value:
            return value
        try:
            return _fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            return value  # written before encryption was added on this column
