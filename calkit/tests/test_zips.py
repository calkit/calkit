"""Tests for ``calkit.zips``."""

import json
import os

import pytest

import calkit.zips
from calkit.zips import (
    calc_dir_sig,
    get_hash,
    get_mtime_ns,
    get_sync_record,
    get_sync_status,
    get_zip_path_map,
    make_zip_path,
    sync_one,
    unzip_path,
    write_zip_path_map,
    zip_path,
)


def test_get_mtime_ns(tmp_dir):
    # Nonexistent path returns 0
    assert get_mtime_ns("nonexistent-file.txt") == 0
    # Existing file returns a positive integer matching os.stat
    p = tmp_dir / "file.txt"
    p.write_text("hello")
    result = get_mtime_ns(str(p))
    assert isinstance(result, int)
    assert result > 0
    assert result == os.stat(str(p)).st_mtime_ns


def test_calc_dir_sig(tmp_dir):
    # Non-directory returns empty string
    p = tmp_dir / "file.txt"
    p.write_text("hello")
    assert calc_dir_sig(str(p)) == ""
    # Empty directory returns 0-0-0
    d = tmp_dir / "d"
    d.mkdir()
    assert calc_dir_sig(str(d)) == "0-0-0"
    # Adding a file changes the signature
    sig_before = calc_dir_sig(str(d))
    (d / "a.txt").write_text("data")
    assert calc_dir_sig(str(d)) != sig_before
    # Modifying a file's content (changing size) changes the signature
    sig_before = calc_dir_sig(str(d))
    (d / "a.txt").write_text("changed content here")
    assert calc_dir_sig(str(d)) != sig_before


def test_get_hash(tmp_dir):
    # Nonexistent path returns None
    assert get_hash("no-such-file.txt") is None
    # File returns a non-empty string hash
    p = tmp_dir / "file.txt"
    p.write_text("hello world")
    h = get_hash(str(p))
    assert h is not None and len(h) > 0
    # Second call returns same hash and cache file is written
    assert get_hash(str(p)) == h
    assert os.path.isfile(calkit.zips.HASH_CACHE_PATH)
    # Cache entry stores mtime as int (nanoseconds)
    with open(calkit.zips.HASH_CACHE_PATH) as f:
        entry = list(json.load(f).values())[0]
    assert isinstance(entry["mtime"], int)
    # Modifying the file invalidates the cache
    p.write_text("version 2 with more content")
    assert get_hash(str(p)) != h
    # Directory is hashable and cache is invalidated when contents change
    d = tmp_dir / "d"
    d.mkdir()
    (d / "a.txt").write_text("hello")
    h_dir = get_hash(str(d))
    assert h_dir is not None
    (d / "b.txt").write_text("new file")
    assert get_hash(str(d)) != h_dir
    # Stale cache entry (float mtime, old format) is ignored and rehashed
    p2 = tmp_dir / "other.txt"
    p2.write_text("hello")
    os.makedirs(calkit.zips.LOCAL_DIR, exist_ok=True)
    stale = {
        str(p2.as_posix()): {
            "path": str(p2.as_posix()),
            "hash": "stale-hash",
            "mtime": 1234567890.123,
            "size": 5,
            "dir_sig": None,
        }
    }
    with open(calkit.zips.HASH_CACHE_PATH, "w") as f:
        json.dump(stale, f)
    h2 = get_hash(str(p2))
    assert h2 is not None and h2 != "stale-hash"


def test_make_zip_path():
    assert make_zip_path("data/mydir") == ".calkit/zips/data/mydir.zip"


def test_get_write_zip_path_map(tmp_dir):
    # Missing info file returns empty dict
    assert get_zip_path_map() == {}
    # Write and read back
    pm = {"data/mydir": ".calkit/zips/data/mydir.zip"}
    write_zip_path_map(pm)
    assert get_zip_path_map() == pm


def test_zip_unzip(tmp_dir):
    src = tmp_dir / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("world")
    zip_out = str(tmp_dir / "out.zip")
    zip_path(str(src), zip_out)
    assert os.path.isfile(zip_out)
    dest = tmp_dir / "dest"
    unzip_path(str(dest), zip_out)
    assert (dest / "a.txt").read_text() == "hello"
    assert (dest / "sub" / "b.txt").read_text() == "world"


def test_get_sync_status(tmp_dir):
    src = tmp_dir / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    zip_out = str(tmp_dir / "out.zip")
    # Only input exists: input changed, output not changed
    status = get_sync_status(str(src), zip_out)
    assert status.input_changed is True
    assert status.output_changed is False
    assert status.last_sync_record is None
    # Both exist and no sync record: both marked changed
    zip_path(str(src), zip_out)
    write_zip_path_map({str(src.as_posix()): zip_out})
    status = get_sync_status(str(src), zip_out)
    assert status.input_changed is True
    assert status.output_changed is True
    assert status.last_sync_record is None


def test_sync_one(tmp_dir, monkeypatch):
    monkeypatch.setattr("calkit.zips.subprocess.run", lambda *_, **__: None)
    # to-zip: zips input and writes sync record
    src = tmp_dir / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    zip_out = str(tmp_dir / calkit.zips.ZIPS_DIR / "src.zip")
    write_zip_path_map({str(src.as_posix()): zip_out})
    sync_one(str(src), zip_out, direction="to-zip")
    assert os.path.isfile(zip_out)
    record = get_sync_record(str(src.as_posix()))
    assert record is not None
    assert record.input_hash is not None and record.output_hash is not None
    # to-workspace: unzips output to dest and writes sync record
    dest = tmp_dir / "dest"
    write_zip_path_map({str(dest.as_posix()): zip_out})
    sync_one(str(dest), zip_out, direction="to-workspace")
    assert (dest / "a.txt").read_text() == "hello"
    assert get_sync_record(str(dest.as_posix())) is not None
    # both sides changed with direction='both' raises a conflict error
    src2 = tmp_dir / "src2"
    src2.mkdir()
    (src2 / "a.txt").write_text("hello")
    zip_out2 = str(tmp_dir / "out2.zip")
    zip_path(str(src2), zip_out2)
    with pytest.raises(RuntimeError, match="Conflict"):
        sync_one(str(src2), zip_out2, direction="both")
