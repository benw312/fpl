"""The on-disk capture format: a directory holding one fetch's inputs.

`fpl sync` writes one of these per day (FU-41). A capture is a directory
containing `bootstrap-static.json`, `fixtures.json` and a `manifest.json`
describing both — everything a projection depends on, kept together, so a run
pinned to it reads exactly what was fetched rather than whatever the caches
hold now.

This module knows the format and nothing about FPL. It raises `OSError` and
`ValueError`; callers map those onto whatever their own layer reports, because
a missing capture is a hard error for `--snapshot` and merely an unusable
candidate for `plan evaluate`'s archive scan.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

BOOTSTRAP_FILENAME = "bootstrap-static.json"
FIXTURES_FILENAME = "fixtures.json"
MANIFEST_FILENAME = "manifest.json"

# Bumped when a reader can no longer make sense of an older manifest. A
# mismatch is refused rather than guessed at: a capture exists to be trusted.
MANIFEST_VERSION = 1

_HASH_BLOCK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(directory: Path) -> dict[str, Any]:
    """Parse and version-check `directory/manifest.json`.

    Raises `OSError` if it is unreadable and `ValueError` if it is not a
    manifest this build understands.
    """
    path = directory / MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a manifest object (top level is a {type(payload).__name__})")
    version = payload.get("version")
    if version != MANIFEST_VERSION:
        raise ValueError(f"{path} is manifest version {version!r}; this build writes and reads {MANIFEST_VERSION}")
    return payload


def manifest_captured_at(manifest: dict[str, Any]) -> datetime:
    """The fetch time the manifest records.

    This, not a file mtime, is a capture's date: `cp -r` resets mtimes, and the
    archive is written by a `Persistent=true` timer whose catch-up firings land
    hours from the schedule they are catching up on.
    """
    raw = manifest.get("captured_at")
    if not isinstance(raw, str):
        raise ValueError(f"manifest records no captured_at (found {raw!r})")
    return datetime.fromisoformat(raw)


def recorded_sha256(manifest: dict[str, Any], filename: str) -> str:
    files = manifest.get("files")
    if not isinstance(files, dict) or not isinstance(files.get(filename), dict):
        raise ValueError(f"manifest records no entry for {filename}")
    digest = files[filename].get("sha256")
    if not isinstance(digest, str):
        raise ValueError(f"manifest records no sha256 for {filename} (found {digest!r})")
    return digest


def write_capture(
    directory: Path,
    *,
    bootstrap: dict[str, Any],
    fixtures: list[Any],
    captured_at: datetime,
    current_event: dict[str, Any] | None,
) -> Path:
    """Write the two payloads and the manifest describing them.

    The digests are taken from the files as written rather than from the
    in-memory payloads, so the manifest attests to the bytes a reader will
    actually hash.
    """
    directory.mkdir(parents=True, exist_ok=True)
    bootstrap_path = directory / BOOTSTRAP_FILENAME
    fixtures_path = directory / FIXTURES_FILENAME
    bootstrap_path.write_text(json.dumps(bootstrap, ensure_ascii=False), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "version": MANIFEST_VERSION,
        "captured_at": captured_at.isoformat(),
        "current_event": current_event,
        "files": {
            BOOTSTRAP_FILENAME: {"sha256": sha256_file(bootstrap_path)},
            FIXTURES_FILENAME: {"sha256": sha256_file(fixtures_path)},
        },
    }
    (directory / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return directory
