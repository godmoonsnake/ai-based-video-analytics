"""Bounded encrypted local spool. Broker messages are acknowledged only after fsync."""
import hashlib
from pathlib import Path
import sqlite3
import time
from cryptography.fernet import Fernet


class SpoolFull(RuntimeError):
    pass


class Spool:
    def __init__(self, path: Path, key: str, max_bytes=100_000_000):
        if not key:
            raise ValueError("a separately provisioned spool encryption key is required")
        self.cipher = Fernet(key.encode())
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.max_bytes = path, max_bytes
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS message (id TEXT PRIMARY KEY, payload BLOB NOT NULL, "
                       "status TEXT NOT NULL, received REAL NOT NULL, error TEXT)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def put(self, payload: bytes):
        identifier = hashlib.sha256(payload).hexdigest()
        encrypted = self.cipher.encrypt(payload)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM message WHERE id=?", (identifier,)).fetchone():
                return identifier
            used = db.execute("SELECT COALESCE(SUM(LENGTH(payload)),0) FROM message").fetchone()[0]
            if used + len(encrypted) > self.max_bytes:
                raise SpoolFull("spool capacity exceeded; message not acknowledged; operator action required")
            db.execute("INSERT INTO message VALUES (?,?,?, ?,NULL)",
                       (identifier, encrypted, "pending", time.time()))
        return identifier

    def pending(self, limit=50):
        with self.connect() as db:
            rows = db.execute("SELECT id,payload FROM message WHERE status='pending' ORDER BY received,id LIMIT ?",
                              (limit,)).fetchall()
        return [(key, self.cipher.decrypt(payload)) for key, payload in rows]

    def delivered(self, identifier):
        # Safe only after the central event + outbox transaction has committed.
        with self.connect() as db:
            db.execute("DELETE FROM message WHERE id=? AND status='pending'", (identifier,))

    def quarantine(self, identifier, error):
        with self.connect() as db:
            db.execute("UPDATE message SET status='quarantined',error=? WHERE id=?",
                       (type(error).__name__, identifier))

    def stats(self):
        with self.connect() as db:
            return {row[0]: row[1] for row in db.execute("SELECT status,COUNT(*) FROM message GROUP BY status")}
