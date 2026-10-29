import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from redfirst.repos.extract import (
    ExtractionLimits,
    UnsafeArchive,
    _clean_member_name,
    extract_archive,
)


def make_zip(path: Path, members: dict[str, bytes | tuple[bytes, int]]) -> Path:
    """members: name -> data, or (data, unix_mode)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, value in members.items():
            data, mode = value if isinstance(value, tuple) else (value, None)
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED  # ZipInfo defaults to STORED
            if mode is not None:
                info.external_attr = mode << 16
            zf.writestr(info, data)
    return path


def make_tar(path: Path, add) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        add(tf)
    return path


def tar_file(tf, name, data=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "out"


def test_extracts_normal_zip_and_strips_single_root(tmp_path, dest):
    z = make_zip(tmp_path / "a.zip", {"proj/app.py": b"x = 1\n", "proj/tests/test_a.py": b"pass"})
    res = extract_archive(z, dest)
    assert (dest / "app.py").read_text() == "x = 1\n"
    assert res.file_count == 2


def test_extracts_tar_gz(tmp_path, dest):
    t = make_tar(tmp_path / "a.tar.gz", lambda tf: tar_file(tf, "app.py", b"y = 2"))
    extract_archive(t, dest)
    assert (dest / "app.py").read_bytes() == b"y = 2"


@pytest.mark.parametrize("name", ["a\\b.py", "ok\x00.py", "..\\evil.py", "C:\\evil.py"])
def test_hostile_member_names_rejected_by_validator(name):
    # zipfile.ZipInfo rewrites backslashes/NULs itself, so test the validator directly.
    with pytest.raises(UnsafeArchive):
        _clean_member_name(name, ExtractionLimits())


@pytest.mark.parametrize(
    "name", ["../evil.py", "a/../../evil.py", "a/../evil.py", "/etc/passwd", "C:/evil.py"]
)
def test_zip_path_traversal_rejected(tmp_path, dest, name):
    z = make_zip(tmp_path / "bad.zip", {"good.py": b"1", name: b"pwn"})
    with pytest.raises(UnsafeArchive):
        extract_archive(z, dest)
    assert not dest.exists()
    assert not (tmp_path / "evil.py").exists()


def test_tar_path_traversal_rejected(tmp_path, dest):
    t = make_tar(tmp_path / "bad.tar.gz", lambda tf: tar_file(tf, "../evil.py"))
    with pytest.raises(UnsafeArchive):
        extract_archive(t, dest)
    assert not (tmp_path / "evil.py").exists()


def test_zip_symlink_rejected(tmp_path, dest):
    link_mode = stat.S_IFLNK | 0o777
    z = make_zip(tmp_path / "s.zip", {"link": (b"/etc/passwd", link_mode), "a.py": b"1"})
    with pytest.raises(UnsafeArchive, match="symlink"):
        extract_archive(z, dest)


def test_tar_symlink_and_hardlink_rejected(tmp_path, dest):
    def add_sym(tf):
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)

    def add_hard(tf):
        tar_file(tf, "real.py")
        info = tarfile.TarInfo("hard")
        info.type = tarfile.LNKTYPE
        info.linkname = "real.py"
        tf.addfile(info)

    for i, add in enumerate((add_sym, add_hard)):
        t = make_tar(tmp_path / f"l{i}.tar.gz", add)
        with pytest.raises(UnsafeArchive, match="link"):
            extract_archive(t, tmp_path / f"o{i}")


def test_tar_device_file_rejected(tmp_path, dest):
    def add(tf):
        info = tarfile.TarInfo("dev")
        info.type = tarfile.CHRTYPE
        tf.addfile(info)

    with pytest.raises(UnsafeArchive, match="special"):
        extract_archive(make_tar(tmp_path / "d.tar.gz", add), dest)


def test_zip_bomb_rejected_by_ratio(tmp_path, dest):
    z = make_zip(tmp_path / "bomb.zip", {"zeros.bin": b"\0" * (20 * 1024 * 1024)})
    with pytest.raises(UnsafeArchive, match="size limit"):
        extract_archive(z, dest)
    assert not dest.exists()


def test_total_size_limit(tmp_path, dest):
    rng_data = bytes(range(256)) * 400
    z = make_zip(tmp_path / "big.zip", {"a.bin": rng_data, "b.bin": rng_data})
    with pytest.raises(UnsafeArchive):
        extract_archive(z, dest, ExtractionLimits(max_total_bytes=150_000, max_ratio=1000))


def test_per_file_limit(tmp_path, dest):
    z = make_zip(tmp_path / "f.zip", {"a.bin": b"a" * 5000})
    with pytest.raises(UnsafeArchive, match="too large"):
        extract_archive(z, dest, ExtractionLimits(max_file_bytes=1000, max_ratio=10_000))


def test_member_count_limit(tmp_path, dest):
    z = make_zip(tmp_path / "m.zip", {f"f{i}.py": b"1" for i in range(20)})
    with pytest.raises(UnsafeArchive, match="too many"):
        extract_archive(z, dest, ExtractionLimits(max_members=10))


def test_depth_limit(tmp_path, dest):
    deep = "/".join(["d"] * 40) + "/f.py"
    z = make_zip(tmp_path / "deep.zip", {deep: b"1"})
    with pytest.raises(UnsafeArchive, match="too long or too deep"):
        extract_archive(z, dest)


def test_case_colliding_names_rejected(tmp_path, dest):
    z = make_zip(tmp_path / "c.zip", {"A.py": b"1", "a.py": b"2"})
    with pytest.raises(UnsafeArchive, match="duplicate"):
        extract_archive(z, dest)


def test_garbage_file_rejected(tmp_path, dest):
    p = tmp_path / "junk.zip"
    p.write_bytes(b"not an archive at all")
    with pytest.raises(UnsafeArchive, match="not a supported"):
        extract_archive(p, dest)


def test_nonempty_destination_refused(tmp_path, dest):
    dest.mkdir()
    (dest / "keep.txt").write_text("x")
    z = make_zip(tmp_path / "a.zip", {"a.py": b"1"})
    with pytest.raises(ValueError, match="empty"):
        extract_archive(z, dest)
    assert (dest / "keep.txt").exists()
