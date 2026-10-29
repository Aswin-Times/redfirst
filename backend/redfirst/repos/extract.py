"""Safe extraction of untrusted zip / tar archives.

Nothing here uses ``extractall``. Every member is validated, then written by hand
to a path that is re-checked to stay inside the destination. Any violation rejects
the whole archive and removes the partially written destination.
"""

import posixpath
import shutil
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

_CHUNK = 64 * 1024


class UnsafeArchive(ValueError):
    """The archive violates a safety rule and was rejected."""


@dataclass(frozen=True)
class ExtractionLimits:
    max_members: int = 10_000
    max_total_bytes: int = 200 * 1024 * 1024
    max_file_bytes: int = 50 * 1024 * 1024
    max_ratio: float = 100.0  # uncompressed / compressed, whole archive
    max_path_length: int = 255
    max_depth: int = 30


@dataclass(frozen=True)
class ExtractionResult:
    root: Path
    file_count: int
    total_bytes: int


def _clean_member_name(raw: str, limits: ExtractionLimits) -> str:
    if "\x00" in raw:
        raise UnsafeArchive(f"NUL byte in member name: {raw!r}")
    if "\\" in raw:
        raise UnsafeArchive(f"backslash in member name: {raw!r}")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise UnsafeArchive(f"absolute path in archive: {raw!r}")
    # Reject ".." before normalising: "a/../b" would otherwise collapse to a "safe" path.
    if ".." in raw.split("/"):
        raise UnsafeArchive(f"path traversal in archive: {raw!r}")
    name = posixpath.normpath(raw) if raw not in ("", ".", "./") else "."
    parts = name.split("/")
    if len(name) > limits.max_path_length or len(parts) > limits.max_depth:
        raise UnsafeArchive(f"path too long or too deep: {raw[:80]!r}")
    return name


def _strip_common_root(names: list[str]) -> str | None:
    tops = {n.split("/")[0] for n in names if n != "."}
    if len(tops) != 1:
        return None
    top = next(iter(tops))
    # Only strip if the top level is a directory: something must live beneath it.
    has_children = any(n.startswith(top + "/") for n in names)
    return top if has_children and all(n.startswith(top + "/") or n == top for n in names) else None


class _Writer:
    """Tracks totals and writes validated members under ``dest``."""

    def __init__(self, dest: Path, limits: ExtractionLimits, strip: str | None) -> None:
        self.dest = dest.resolve()
        self.limits = limits
        self.strip = strip
        self.total = 0
        self.files = 0
        self._seen: set[str] = set()

    def _target(self, name: str) -> Path | None:
        if self.strip:
            if name == self.strip:
                return None
            name = name[len(self.strip) + 1 :]
        key = name.casefold()
        if key in self._seen:
            raise UnsafeArchive(f"duplicate or case-colliding member: {name!r}")
        self._seen.add(key)
        target = (self.dest / name).resolve()
        if target != self.dest and self.dest not in target.parents:
            raise UnsafeArchive(f"member escapes destination: {name!r}")
        return target

    def directory(self, name: str) -> None:
        target = self._target(name)
        if target is not None:
            target.mkdir(parents=True, exist_ok=True)

    def file(self, name: str, src: IO[bytes]) -> None:
        target = self._target(name)
        if target is None:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(target, "xb") as out:
            # Count real bytes: headers can lie about size.
            while chunk := src.read(_CHUNK):
                written += len(chunk)
                self.total += len(chunk)
                if written > self.limits.max_file_bytes:
                    raise UnsafeArchive(f"file too large: {name!r}")
                if self.total > self.limits.max_total_bytes:
                    raise UnsafeArchive("archive exceeds total size limit")
                out.write(chunk)
        self.files += 1


def _extract_zip(path: Path, w: _Writer, limits: ExtractionLimits, compressed: int) -> None:
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.flag_bits & 0x1:
                raise UnsafeArchive(f"encrypted member: {info.filename!r}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UnsafeArchive(f"symlink in archive: {info.filename!r}")
            # S_IFMT == 0 means the writer recorded permissions only (treated as regular).
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise UnsafeArchive(f"special file in archive: {info.filename!r}")
        for info in zf.infolist():
            name = _clean_member_name(info.filename.rstrip("/") or ".", limits)
            if info.is_dir():
                w.directory(name)
            else:
                with zf.open(info) as src:
                    w.file(name, src)


def _extract_tar(path: Path, w: _Writer, limits: ExtractionLimits) -> None:
    with tarfile.open(path) as tf:
        for member in tf:
            name = _clean_member_name(member.name.rstrip("/") or ".", limits)
            if member.issym() or member.islnk():
                raise UnsafeArchive(f"link in archive: {member.name!r}")
            if member.isdir():
                w.directory(name)
            elif member.isreg():
                src = tf.extractfile(member)
                if src is None:
                    raise UnsafeArchive(f"unreadable member: {member.name!r}")
                with src:
                    w.file(name, src)
            else:
                raise UnsafeArchive(f"special file in archive: {member.name!r}")


def _list_names(path: Path, kind: str, limits: ExtractionLimits) -> list[str]:
    names: list[str] = []
    if kind == "zip":
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > limits.max_members:
                raise UnsafeArchive("too many members")
            names = [i.filename for i in infos]
    else:
        with tarfile.open(path) as tf:
            for m in tf:
                names.append(m.name)
                if len(names) > limits.max_members:
                    raise UnsafeArchive("too many members")
    return [_clean_member_name(n.rstrip("/") or ".", limits) for n in names]


def extract_archive(
    archive: Path, dest: Path, limits: ExtractionLimits | None = None
) -> ExtractionResult:
    """Extract ``archive`` into the (new or empty) directory ``dest``."""
    limits = limits or ExtractionLimits()
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("destination must be empty")
    if zipfile.is_zipfile(archive):
        kind = "zip"
    elif tarfile.is_tarfile(archive):
        kind = "tar"
    else:
        raise UnsafeArchive("not a supported archive (zip, tar, tar.gz)")

    compressed = max(archive.stat().st_size, 1)
    max_by_ratio = int(compressed * limits.max_ratio)
    effective = ExtractionLimits(
        **{**limits.__dict__, "max_total_bytes": min(limits.max_total_bytes, max(max_by_ratio, 1))}
    )
    dest.mkdir(parents=True, exist_ok=True)
    try:
        names = _list_names(archive, kind, effective)
        writer = _Writer(dest, effective, _strip_common_root(names))
        if kind == "zip":
            _extract_zip(archive, writer, effective, compressed)
        else:
            _extract_tar(archive, writer, effective)
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        if isinstance(exc, UnsafeArchive):
            raise
        if isinstance(exc, (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError)):
            raise UnsafeArchive(f"corrupt or unreadable archive: {exc}") from exc
        raise
    return ExtractionResult(root=dest, file_count=writer.files, total_bytes=writer.total)
