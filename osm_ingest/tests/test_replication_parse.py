"""Tests for replication state parsing and MD5 helpers."""

from __future__ import annotations

from pathlib import Path

from osm_ingest.download.planet import _parse_md5_file, file_md5
from osm_ingest.replicate.diff_apply import _seq_path, parse_state_txt


def test_parse_md5_with_filename() -> None:
    assert (
        _parse_md5_file("d41d8cd98f00b204e9800998ecf8427e  planet-latest.osm.pbf")
        == "d41d8cd98f00b204e9800998ecf8427e"
    )


def test_parse_md5_bare() -> None:
    assert _parse_md5_file("d41d8cd98f00b204e9800998ecf8427e") == (
        "d41d8cd98f00b204e9800998ecf8427e"
    )


def test_file_md5(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"")
    assert file_md5(p) == "d41d8cd98f00b204e9800998ecf8427e"


def test_parse_state_txt() -> None:
    text = (
        "sequenceNumber=123456\n"
        "timestamp=2024-06-01T12:00:00Z\n"
    )
    state = parse_state_txt(text)
    assert state.sequence == 123456
    assert state.timestamp is not None
    assert state.timestamp.year == 2024


def test_seq_path() -> None:
    assert _seq_path(123456789) == "123/456/789"
    assert _seq_path(1) == "000/000/001"
