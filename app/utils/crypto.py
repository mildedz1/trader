from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


@dataclass
class SecretBox:
    fernet: Fernet

    @classmethod
    def from_base64_key(cls, key_b64: str) -> "SecretBox":
        return cls(Fernet(key_b64.encode("utf-8")))

    def encrypt(self, plaintext: str) -> str:
        token = self.fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            data = self.fernet.decrypt(ciphertext.encode("utf-8"))
            return data.decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Invalid encryption token") from exc


def b64decode_to_bytes(data_b64: str | None) -> Optional[bytes]:
    if not data_b64:
        return None
    return base64.b64decode(data_b64.encode("utf-8"))
