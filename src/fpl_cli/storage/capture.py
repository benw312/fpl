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
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

BOOTSTRAP_FILENAME = "bootstrap-static.json"
FIXTURES_FILENAME = "fixtures.json"
MANIFEST_FILENAME = "manifest.json"

# Bumped when the manifest gains something a reader may rely on. Version 2
# added `role` and `next_event`. Older manifests stay readable — the additions
# have safe defaults — but an unknown *newer* version is refused rather than
# guessed at: a capture exists to be trusted.
MANIFEST_VERSION = 2
SUPPORTED_MANIFEST_VERSIONS = (1, 2)

ROLE_CANONICAL = "canonical"
ROLE_ADHOC = "adhoc"

# Renamed-aside captures carry this in their directory name. Automatic
# selection skips them: quarantine exists to make someone look, and a capture a
# later build happens to be able to read should not slide back into use before
# they have.
QUARANTINE_INFIX = ".unreadable-"

PROBLEM_UNRECOGNISED_VERSION = "unrecognised-version"
PROBLEM_UNVERIFIABLE = "unverifiable"


class UnrecognisedManifestVersion(ValueError):
    """The manifest parses but names a version this build does not know.

    A `ValueError` so every caller that already skips unusable captures keeps
    working unchanged, but a distinguishable one, because it means something
    quite different from corruption: the capture is probably perfectly good and
    *this build* is the one that is out of date.
    """


@dataclass(frozen=True)
class CaptureProblem:
    """Why a directory cannot be used as a capture."""

    kind: str
    detail: str

# The archive is filed by UK date because that is the day a gameweek deadline
# and a price change belong to. A 23:30 UTC capture in summer is 00:30 the next
# day in London, and filing it under the UTC date would put it in the wrong
# slot — the one the following night's capture is entitled to.
UK = ZoneInfo("Europe/London")
_UTC = ZoneInfo("UTC")

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
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        raise UnrecognisedManifestVersion(
            f"{path} is manifest version {version!r}; this build writes {MANIFEST_VERSION} "
            f"and reads {', '.join(str(v) for v in SUPPORTED_MANIFEST_VERSIONS)}"
        )
    return payload


def manifest_role(manifest: dict[str, Any]) -> str:
    """`canonical` or `adhoc`; anything unrecognised, or absent, reads as adhoc.

    Absent means a version 1 manifest, written before roles existed. Defaulting
    those to adhoc is the safe direction: a capture that was never asked to
    claim a slot cannot be allowed to claim one retrospectively and displace the
    legacy bare file that has held it all along.
    """
    role = manifest.get("role")
    return ROLE_CANONICAL if role == ROLE_CANONICAL else ROLE_ADHOC


def uk_date(captured_at: datetime) -> date:
    """The UK calendar day a capture belongs to. `captured_at` stays UTC."""
    return captured_at.astimezone(UK).date()


def canonical_slot(archive_dir: Path, captured_at: datetime) -> Path:
    """The one directory per UK date that automatic selection will consider."""
    return archive_dir / uk_date(captured_at).isoformat()


def legacy_slot_file(archive_dir: Path, captured_at: datetime) -> Path:
    """The pre-FU-41 bare file that competes for the same slot."""
    return archive_dir / f"bootstrap-{uk_date(captured_at).isoformat()}.json"


def _unused_path(base: Path) -> Path:
    """`base`, or `base-2`, `base-3`… — the first name nothing occupies.

    Both callers are places where reusing an occupied name would destroy a
    capture, and both key on a timestamp truncated to the second, so a
    collision needs only two captures in the same second.
    """
    destination = base
    attempt = 1
    while destination.exists():
        attempt += 1
        destination = base.with_name(f"{base.name}-{attempt}")
    return destination


def adhoc_path(archive_dir: Path, captured_at: datetime) -> Path:
    """Keyed by the instant, not the day: an ad-hoc capture is not filed under a
    date at all, so two on the same day cannot collide."""
    return _unused_path(archive_dir / captured_at.astimezone(_UTC).strftime("%Y-%m-%dT%H%M%SZ"))


def inspect_capture(directory: Path) -> CaptureProblem | None:
    """`None` if `directory` is a usable capture, otherwise why it is not.

    The two kinds are kept apart because they call for opposite reactions. An
    unrecognised manifest version almost certainly means a *newer* build wrote
    it and this reader is behind — the data is probably fine and the operator
    should look before doing anything. Anything else means the capture does not
    verify: half-written, truncated, edited. Neither is ever deleted.
    """
    try:
        manifest = read_manifest(directory)
    except UnrecognisedManifestVersion as exc:
        return CaptureProblem(PROBLEM_UNRECOGNISED_VERSION, str(exc))
    except OSError as exc:
        return CaptureProblem(PROBLEM_UNVERIFIABLE, f"no readable manifest: {exc}")
    except ValueError as exc:
        return CaptureProblem(PROBLEM_UNVERIFIABLE, str(exc))
    for filename in (BOOTSTRAP_FILENAME, FIXTURES_FILENAME):
        try:
            recorded = recorded_sha256(manifest, filename)
            actual = sha256_file(directory / filename)
        except (OSError, ValueError) as exc:
            return CaptureProblem(PROBLEM_UNVERIFIABLE, f"{filename}: {exc}")
        if actual != recorded:
            return CaptureProblem(
                PROBLEM_UNVERIFIABLE,
                f"{filename} hashes to {actual}, manifest records {recorded}",
            )
    return None


def is_valid_capture(directory: Path) -> bool:
    """Present, readable, and hashing to what its own manifest records."""
    return inspect_capture(directory) is None


def slot_claimed(archive_dir: Path, captured_at: datetime) -> bool:
    """Whether anything at all already occupies this UK date's canonical slot.

    Occupancy, deliberately, not validity. A capture claims a slot only when the
    slot is *empty*: an unreadable capture blocks the claim rather than being
    cleared out of the way, because "this build cannot read it" and "this is
    rubbish" are indistinguishable from inside, and the difference between them
    is a day's snapshot that can never be fetched again.

    Legacy bare files compete on equal terms and are never migrated or
    displaced: `bootstrap-2026-08-28.json` was written at 00:32 and holds that
    day, whatever shape a later capture takes. Because the check is for
    occupancy rather than for a timer having run, the offline case needs no
    special handling — a sync that finds the slot empty simply claims it.
    """
    return (
        legacy_slot_file(archive_dir, captured_at).is_file()
        or canonical_slot(archive_dir, captured_at).exists()
    )


def quarantine(directory: Path, when: datetime) -> Path:
    """Rename an unusable capture aside, preserving every byte of it.

    A rename, never a delete and never an overwrite: whatever is in there
    cannot be fetched again, and the reason it is unreadable may well be that
    this build is the old one.
    """
    stamp = when.astimezone(_UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = _unused_path(directory.with_name(f"{directory.name}{QUARANTINE_INFIX}{stamp}"))
    os.rename(directory, destination)
    return destination


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
    next_event: dict[str, Any] | None,
    role: str,
) -> Path:
    """Write the two payloads and the manifest describing them, atomically.

    Everything is staged in a sibling directory and `os.replace`d into place, so
    the destination either does not exist or is a complete capture. A crashed
    or half-written run leaves a `.incoming-*` directory behind, never a partial
    capture squatting on a canonical slot it would then hold against the good
    run that follows.

    The digests are taken from the files as written rather than from the
    in-memory payloads, so the manifest attests to the bytes a reader will
    actually hash.
    """
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.parent / f".incoming-{uuid4().hex}"
    staging.mkdir()
    try:
        bootstrap_path = staging / BOOTSTRAP_FILENAME
        fixtures_path = staging / FIXTURES_FILENAME
        bootstrap_path.write_text(json.dumps(bootstrap, ensure_ascii=False), encoding="utf-8")
        fixtures_path.write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
        manifest = {
            "version": MANIFEST_VERSION,
            "captured_at": captured_at.isoformat(),
            "role": role,
            "current_event": current_event,
            "next_event": next_event,
            "files": {
                BOOTSTRAP_FILENAME: {"sha256": sha256_file(bootstrap_path)},
                FIXTURES_FILENAME: {"sha256": sha256_file(fixtures_path)},
            },
        }
        (staging / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if directory.exists():
            # No exceptions, and no inspection first: an existing capture is
            # never deleted or overwritten, whether or not this build can read
            # it. A caller that finds the slot occupied quarantines and writes
            # ad-hoc instead of coming here.
            raise FileExistsError(f"{directory} already exists; a capture is never overwritten")
        os.replace(staging, directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return directory
