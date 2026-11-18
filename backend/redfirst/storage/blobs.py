"""Content-addressed local blob store for archives and execution logs.

Keys are SHA-256 hex digests; the database stores only keys. Keys are validated before
any path is built, so a key can never address a file outside the store.
"""

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

_KEY = re.compile(r"^[0-9a-f]{64}$")


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not _KEY.match(key):
            raise ValueError(f"invalid blob key: {key!r}")
        return self.root / key[:2] / key

    def put_bytes(self, data: bytes) -> str:
        key = hashlib.sha256(data).hexdigest()
        target = self._path(key)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=target.parent)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        return key

    def put_file(self, source: Path) -> str:
        digest = hashlib.sha256()
        with open(source, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                digest.update(chunk)
        key = digest.hexdigest()
        target = self._path(key)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=target.parent)
            os.close(fd)
            try:
                shutil.copyfile(source, tmp)
                try:
                    os.replace(tmp, target)
                except (FileExistsError, PermissionError):
                    # Windows can deny a replace racing another writer of the same digest.
                    if not target.is_file():
                        raise
            finally:
                Path(tmp).unlink(missing_ok=True)
        return key

    def path(self, key: str) -> Path:
        p = self._path(key)
        if not p.is_file():
            raise FileNotFoundError(f"blob not found: {key}")
        return p

    def delete(self, key: str) -> bool:
        """Remove a blob; returns whether anything was deleted."""
        p = self._path(key)
        try:
            p.unlink()
        except FileNotFoundError:
            return False
        return True

    def read_text(self, key: str, limit: int | None = None) -> str:
        with open(self.path(key), "rb") as fh:
            data = fh.read(limit) if limit else fh.read()
        return data.decode("utf-8", errors="replace")
