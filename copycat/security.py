import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def device_id_for(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:16]


class Identity:
    """This computer's long-term key pair, created on first launch."""

    def __init__(self, folder: Path):
        key_file = folder / "identity.key"
        if key_file.exists():
            self._private = X25519PrivateKey.from_private_bytes(key_file.read_bytes())
        else:
            self._private = X25519PrivateKey.generate()
            key_file.write_bytes(self._private.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            ))
            os.chmod(key_file, 0o600)
        self.public_key = self._private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.device_id = device_id_for(self.public_key)

    def session_key(self, peer_public_key: bytes, salt: bytes) -> bytes:
        shared = self._private.exchange(X25519PublicKey.from_public_bytes(peer_public_key))
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"copycat v1").derive(shared)


def pairing_code(key_a: bytes, key_b: bytes) -> str:
    # Both computers compute the same code; a man-in-the-middle would make the two screens disagree.
    digest = hashlib.sha256(b"copycat pairing" + min(key_a, key_b) + max(key_a, key_b)).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


class Cipher:
    def __init__(self, key: bytes):
        self._aead = ChaCha20Poly1305(key)

    def seal(self, message: dict) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, json.dumps(message, ensure_ascii=False).encode(), None)

    def open(self, frame: bytes) -> dict:
        return json.loads(self._aead.decrypt(frame[:12], frame[12:], None))


class PairedDevices:
    def __init__(self, folder: Path):
        self._file = folder / "paired.json"
        try:
            self._devices = json.loads(self._file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._devices = {}

    def is_paired(self, device_id: str, public_key: bytes) -> bool:
        return self._devices.get(device_id, {}).get("public_key") == b64(public_key)

    def ids(self) -> set:
        return set(self._devices)

    def add(self, device_id: str, public_key: bytes, name: str):
        self._devices[device_id] = {"public_key": b64(public_key), "name": name}
        self._save()

    def remove(self, device_id: str):
        self._devices.pop(device_id, None)
        self._save()

    def _save(self):
        self._file.write_text(json.dumps(self._devices, indent=2))
