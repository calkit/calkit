"""Tests for ``calkit.zips``."""

import json
import os
import shutil

import pytest

import calkit.zips
from calkit.zips import (
    calc_dir_sig,
    check_overlap,
    get_hash,
    get_mtime_ns,
    get_sync_record,
    get_sync_status,
    get_zip_path_map,
    is_zip_candidate,
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


def test_is_zip_candidate(tmp_dir):
    from calkit.core import DVC_SIZE_THRESH_BYTES

    # Non-directory is never a candidate
    p = tmp_dir / "file.txt"
    p.write_text("x")
    assert not is_zip_candidate(str(p))
    # Directory below the size threshold is not a candidate
    small_dir = tmp_dir / "small"
    small_dir.mkdir()
    (small_dir / "a.txt").write_text("tiny")
    assert not is_zip_candidate(str(small_dir))
    # Large directory with many small files is a candidate
    large_small = tmp_dir / "large_small"
    large_small.mkdir()
    file_size = (
        DVC_SIZE_THRESH_BYTES // calkit.zips.ZIP_CANDIDATE_MIN_FILE_COUNT
    ) + 1
    for i in range(calkit.zips.ZIP_CANDIDATE_MIN_FILE_COUNT):
        (large_small / f"f{i}.bin").write_bytes(b"x" * file_size)
    assert is_zip_candidate(str(large_small))
    # Large directory with too few files is NOT a candidate
    few_files = tmp_dir / "few_files"
    few_files.mkdir()
    big_file_size = DVC_SIZE_THRESH_BYTES + 1
    for i in range(calkit.zips.ZIP_CANDIDATE_MIN_FILE_COUNT - 1):
        (few_files / f"f{i}.bin").write_bytes(b"x" * big_file_size)
    assert not is_zip_candidate(str(few_files))
    # Large directory with a single huge file is NOT a candidate
    # (avg file size exceeds threshold)
    large_single = tmp_dir / "large_single"
    large_single.mkdir()
    huge = calkit.zips.ZIP_CANDIDATE_AVG_FILE_SIZE_BYTES + 1
    (large_single / "big.bin").write_bytes(b"x" * huge)
    assert not is_zip_candidate(str(large_single))


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
    assert make_zip_path("data/mydir") == ".calkit/zips/files/data/mydir.zip"


def test_get_write_zip_path_map(tmp_dir):
    # Missing info file returns empty dict
    assert get_zip_path_map() == {}
    # Write and read back
    pm = {"data/mydir": ".calkit/zips/data/mydir.zip"}
    write_zip_path_map(pm)
    assert get_zip_path_map() == pm


def test_check_overlap():
    pm = {
        "data": ".calkit/zips/data.zip",
        "results": ".calkit/zips/results.zip",
    }
    # Non-overlapping path is fine
    check_overlap("other", pm)
    # Exact match (re-adding same path) is fine
    check_overlap("data", pm)
    # Child of existing path raises
    with pytest.raises(ValueError, match="overlaps"):
        check_overlap("data/subdir", pm)
    # Parent of existing path raises
    with pytest.raises(ValueError, match="overlaps"):
        check_overlap("results/output", pm)


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
    # Workspace deleted: zip is removed and sync record cleared
    src3 = tmp_dir / "src3"
    src3.mkdir()
    (src3 / "a.txt").write_text("hello")
    zip_out3 = str(tmp_dir / calkit.zips.ZIPS_DIR / "src3.zip")
    write_zip_path_map({str(src3.as_posix()): zip_out3})
    sync_one(str(src3), zip_out3, direction="to-zip")
    assert os.path.isfile(zip_out3)
    shutil.rmtree(str(src3))
    result = sync_one(str(src3), zip_out3, direction="to-zip")
    assert result is None
    assert not os.path.exists(zip_out3)
    assert get_sync_record(str(src3.as_posix())) is None
    # Zip deleted: workspace is removed and sync record cleared
    src4 = tmp_dir / "src4"
    src4.mkdir()
    (src4 / "a.txt").write_text("hello")
    zip_out4 = str(tmp_dir / calkit.zips.ZIPS_DIR / "src4.zip")
    write_zip_path_map({str(src4.as_posix()): zip_out4})
    sync_one(str(src4), zip_out4, direction="to-zip")
    assert os.path.isfile(zip_out4)
    os.remove(zip_out4)
    result = sync_one(str(src4), zip_out4, direction="to-workspace")
    assert result is None
    assert not os.path.exists(str(src4))
    assert get_sync_record(str(src4.as_posix())) is None
    # Both deleted: sync record is cleared so future recreated side is a fresh
    # sync
    src5 = tmp_dir / "src5"
    src5.mkdir()
    (src5 / "a.txt").write_text("hello")
    zip_out5 = str(tmp_dir / calkit.zips.ZIPS_DIR / "src5.zip")
    write_zip_path_map({str(src5.as_posix()): zip_out5})
    sync_one(str(src5), zip_out5, direction="to-zip")
    shutil.rmtree(str(src5))
    os.remove(zip_out5)
    result = sync_one(str(src5), zip_out5, direction="both")
    assert result is None
    assert get_sync_record(str(src5.as_posix())) is None
    # Neither side exists and no sync record: skip silently (e.g., pipeline
    # output not yet produced on first run)
    result = sync_one(
        str(tmp_dir / "nonexistent"), str(tmp_dir / "nonexistent.zip")
    )
    assert result is None
    # Zip deleted but direction=to-zip: restore zip from workspace
    src6 = tmp_dir / "src6"
    src6.mkdir()
    (src6 / "a.txt").write_text("hello")
    zip_out6 = str(tmp_dir / calkit.zips.ZIPS_DIR / "src6.zip")
    write_zip_path_map({str(src6.as_posix()): zip_out6})
    sync_one(str(src6), zip_out6, direction="to-zip")
    assert os.path.isfile(zip_out6)
    os.remove(zip_out6)
    result = sync_one(str(src6), zip_out6, direction="to-zip")
    assert result is not None
    assert os.path.isfile(zip_out6)
    assert get_sync_record(str(src6.as_posix())) is not None
    # Workspace deleted but direction=to-workspace: restore workspace from zip
    src7 = tmp_dir / "src7"
    src7.mkdir()
    (src7 / "a.txt").write_text("hello")
    zip_out7 = str(tmp_dir / calkit.zips.ZIPS_DIR / "src7.zip")
    write_zip_path_map({str(src7.as_posix()): zip_out7})
    sync_one(str(src7), zip_out7, direction="to-zip")
    shutil.rmtree(str(src7))
    result = sync_one(str(src7), zip_out7, direction="to-workspace")
    assert result is not None
    assert (src7 / "a.txt").read_text() == "hello"
    assert get_sync_record(str(src7.as_posix())) is not None
