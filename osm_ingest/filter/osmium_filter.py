"""Wrapper around osmium-tool tags-filter."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class OsmiumNotFoundError(RuntimeError):
    """Raised when the osmium binary is not on PATH."""


def resolve_osmium(bin_name: str = "osmium") -> str:
    path = shutil.which(bin_name)
    if not path:
        raise OsmiumNotFoundError(
            f"'{bin_name}' not found on PATH. Install osmium-tool "
            "(https://osmcode.org/osmium-tool/) before filtering planet files."
        )
    return path


def run_tags_filter(
    input_path: Path,
    output_path: Path,
    expressions: tuple[str, ...] | list[str],
    *,
    osmium_bin: str = "osmium",
    overwrite: bool = True,
) -> Path:
    """Filter PBF to business-related objects, keeping referenced nodes.

    osmium tags-filter keeps referenced objects by default (needed for way geometry).
    """
    if not expressions:
        raise ValueError("At least one tags-filter expression is required")
    if not input_path.exists():
        raise FileNotFoundError(f"Input PBF not found: {input_path}")

    binary = resolve_osmium(osmium_bin)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        binary,
        "tags-filter",
        str(input_path),
        *expressions,
        "-o",
        str(output_path),
    ]
    if overwrite:
        cmd.append("--overwrite")

    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"osmium tags-filter failed ({result.returncode}): {result.stderr or result.stdout}"
        )
    logger.info("Filtered PBF written to %s (%s bytes)", output_path, output_path.stat().st_size)
    return output_path
