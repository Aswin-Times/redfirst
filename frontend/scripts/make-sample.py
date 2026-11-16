"""Rebuild public/samples/accounts-demo.zip from the planted-bug fixture repo.

The archive is STORED (uncompressed) with fixed timestamps, so it is deterministic and a test can
check that it holds exactly the fixture's files. Run from the repository root:
    python frontend/scripts/make-sample.py
"""
import zipfile
from pathlib import Path

SRC = Path("fixtures/repos/exception_bug")
OUT = Path("frontend/public/samples/accounts-demo.zip")
ROOT = "accounts-demo"

OUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_STORED) as zf:
    for path in sorted(p for p in SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        info = zipfile.ZipInfo(f"{ROOT}/{path.relative_to(SRC).as_posix()}", (2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        zf.writestr(info, path.read_bytes())
print(OUT, OUT.stat().st_size, "bytes")
