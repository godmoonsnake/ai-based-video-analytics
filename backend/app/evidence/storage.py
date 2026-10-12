import hashlib
import os
from pathlib import Path
import re
import uuid
from cryptography.fernet import Fernet
from app.config import get_settings


class ObjectStore:
    """Private encrypted file-object store; atomic writes on a persistent volume.

    Production deployments must supply the key outside this volume and protect
    the mounted directory. This implementation is single-host, not an HA claim.
    """
    def __init__(self):
        settings = get_settings()
        self.root = Path(settings.evidence_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        key = settings.evidence_key
        if not key:
            if settings.environment == "production":
                raise RuntimeError("production evidence encryption key required")
            key_path = self.root.parent / ".development-evidence.key"
            try:
                with key_path.open("xb") as f:
                    f.write(Fernet.generate_key())
                    f.flush()
                    os.fsync(f.fileno())
            except FileExistsError:
                pass
            key = key_path.read_text()
        self.cipher = Fernet(key.encode())

    def path(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}/[a-f0-9]{32}\.bin", key):
            raise ValueError("invalid storage key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("storage escape denied")
        return path

    def put(self, scope, content: bytes):
        prefix = hashlib.sha256(f"{scope.tenant}\0{scope.site}".encode()).hexdigest()
        key = prefix + "/" + uuid.uuid4().hex + ".bin"
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".pending")
        with temporary.open("xb") as f:
            f.write(self.cipher.encrypt(content))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)
        return key

    def read(self, scope, key):
        expected = hashlib.sha256(f"{scope.tenant}\0{scope.site}".encode()).hexdigest()
        if not key.startswith(expected + "/"):
            raise PermissionError("object scope mismatch")
        return self.cipher.decrypt(self.path(key).read_bytes())

    def delete(self, scope, key):
        self.read(scope, key)  # validate scope and decryptability before removal
        self.path(key).unlink(missing_ok=True)
