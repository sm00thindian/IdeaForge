"""Tests for ingest and deduplication."""

from ideaforge.ingest import (
    archive_folder_for_file,
    compute_file_hash,
    copy_file_safely,
    find_archive_copy,
    get_audio_files,
    remove_device_file_after_copy,
    should_skip_by_hash,
    verify_copy,
)


def test_compute_file_hash_stable(tmp_path):
    f = tmp_path / "test.wav"
    f.write_bytes(b"audio data here")
    assert compute_file_hash(f) == compute_file_hash(f)


def test_get_audio_files_filters_small(tmp_path):
    big = tmp_path / "big.wav"
    big.write_bytes(b"\x00" * 60_000)
    small = tmp_path / "small.wav"
    small.write_bytes(b"\x00" * 100)
    files = get_audio_files(tmp_path, {".wav"}, min_size_bytes=50_000)
    assert len(files) == 1
    assert files[0].name == "big.wav"


def test_should_skip_by_hash(tmp_path):
    f = tmp_path / "rec.wav"
    f.write_bytes(b"content")
    h = compute_file_hash(f)
    log = {"hashes": [h], "files": {}}
    assert should_skip_by_hash(f, log)
    assert not should_skip_by_hash(tmp_path / "other.wav", log)


def test_verify_copy_matches(tmp_path):
    src = tmp_path / "R2026-06-27-07-43-11.WAV"
    src.write_bytes(b"\x00" * 1000)
    archive = tmp_path / "archive"
    dest = copy_file_safely(src, archive)
    assert verify_copy(src, dest)


def test_remove_device_file_after_verified_copy(tmp_path):
    src = tmp_path / "device" / "R2026-06-27-07-43-11.WAV"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"\x00" * 1000)
    dest = copy_file_safely(src, tmp_path / "archive")
    assert remove_device_file_after_copy(src, dest)
    assert not src.exists()
    assert dest.exists()


def test_remove_device_file_refuses_mismatched_copy(tmp_path):
    src = tmp_path / "device" / "rec.WAV"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"original")
    dest = tmp_path / "archive" / "rec.WAV"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"tampered")
    assert not remove_device_file_after_copy(src, dest)
    assert src.exists()


def test_find_archive_copy_by_name(tmp_path):
    src = tmp_path / "device" / "R2026-06-27-07-43-11.WAV"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"\x00" * 1000)
    archive_root = tmp_path / "IdeaForge"
    copied = copy_file_safely(src, archive_folder_for_file(src, archive_root))
    found = find_archive_copy(src, archive_root)
    assert found == copied