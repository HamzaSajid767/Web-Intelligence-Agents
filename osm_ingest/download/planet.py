"""Resume-capable planet PBF downloader with MD5 verification."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def _parse_md5_file(text: str) -> str:
    """Parse `md5  filename` or bare hex digest."""
    text = text.strip()
    match = re.match(r"^([a-fA-F0-9]{32})\s+", text)
    if match:
        return match.group(1).lower()
    if re.fullmatch(r"[a-fA-F0-9]{32}", text):
        return text.lower()
    raise ValueError(f"Unrecognized MD5 file contents: {text[:80]!r}")


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=60))
def fetch_expected_md5(md5_url: str, timeout: float = 60.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(md5_url)
        resp.raise_for_status()
        return _parse_md5_file(resp.text)


def file_md5(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@retry(stop=stop_after_attempt(8), wait=wait_exponential(multiplier=2, min=2, max=120))
def download_planet(
    url: str,
    dest: Path,
    *,
    chunk_bytes: int = 8 * 1024 * 1024,
    md5_url: str | None = None,
    verify_md5: bool = True,
) -> Path:
    """Download planet PBF with HTTP Range resume support.

    Returns the local path on success.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")

    existing = partial.stat().st_size if partial.exists() else 0
    headers: dict[str, str] = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        logger.info("Resuming download of %s from byte %s", url, existing)

    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 416:
                logger.info("Server reports range satisfied; treating partial as complete")
            else:
                resp.raise_for_status()
                mode = "ab" if resp.status_code == 206 and existing > 0 else "wb"
                if mode == "wb" and existing > 0:
                    logger.warning("Server ignored Range; restarting download from scratch")
                    existing = 0
                with partial.open(mode) as fh:
                    for chunk in resp.iter_bytes(chunk_size=chunk_bytes):
                        fh.write(chunk)

    partial.replace(dest)
    logger.info("Downloaded planet to %s (%s bytes)", dest, dest.stat().st_size)

    if verify_md5 and md5_url:
        expected = fetch_expected_md5(md5_url)
        actual = file_md5(dest)
        if actual != expected:
            dest.unlink(missing_ok=True)
            raise ValueError(f"MD5 mismatch for {dest}: expected {expected}, got {actual}")
        logger.info("MD5 verified: %s", actual)

    return dest
