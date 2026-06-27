"""Tests for ingest and deduplication."""

from ideaforge.ingest import compute_file_hash, get_audio_files, should_skip_by_hash


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