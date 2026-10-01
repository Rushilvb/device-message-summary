"""Core logic: turn JSON Lines device messages into a summary.

Pure functions only (no I/O except `summarize_file`), so the logic can be
tested without the HTTP layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

BAD_JSON = "BAD_JSON"
INVALID_RECORD = "INVALID_RECORD"

REQUIRED_KEYS = {"device_id", "sequence", "status"}
VALID_STATUSES = {"ok", "error"}


class _DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key (e.g. two "status" fields)."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise _DuplicateKeyError(key)
        obj[key] = value
    return obj


def _is_valid_record(obj: Any) -> bool:
    """Apply the record rules from the spec. Returns True only for a fully valid record."""
    if not isinstance(obj, dict) or set(obj.keys()) != REQUIRED_KEYS:
        return False

    device_id = obj["device_id"]
    if not isinstance(device_id, str) or device_id.strip() == "":
        return False

    sequence = obj["sequence"]
    # bool is a subclass of int in Python, so it must be excluded explicitly.
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        return False

    if obj["status"] not in VALID_STATUSES:
        return False

    return True


@dataclass
class _DeviceState:
    ok: int = 0
    error: int = 0
    last_sequence: int = -1
    last_status: str | None = None


def summarize_lines(lines: Iterable[str]) -> dict[str, Any]:
    """Summarize an iterable of text lines (without trailing newlines).

    Line numbers are 1-based and follow the order of `lines`.
    """
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    devices: dict[str, _DeviceState] = {}
    accepted = 0
    duplicates = 0

    for line_no, raw in enumerate(lines, start=1):
        # 1. Parse. Blank / whitespace-only lines are BAD_JSON per the spec.
        if raw.strip() == "":
            errors.append({"line": line_no, "code": BAD_JSON})
            continue
        try:
            obj = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        except _DuplicateKeyError:
            # Syntactically JSON, but not a well-formed record.
            errors.append({"line": line_no, "code": INVALID_RECORD})
            continue
        except ValueError:  # json.JSONDecodeError is a subclass of ValueError
            errors.append({"line": line_no, "code": BAD_JSON})
            continue

        # 2. Validate before checking duplicates.
        if not _is_valid_record(obj):
            errors.append({"line": line_no, "code": INVALID_RECORD})
            continue

        device_id: str = obj["device_id"]  # preserved exactly as supplied
        sequence: int = obj["sequence"]
        status: str = obj["status"]

        # 3. First occurrence of (device_id, sequence) wins, regardless of status.
        key = (device_id, sequence)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        accepted += 1

        # 4. Update per-device state. Latest status = highest accepted sequence,
        #    independent of arrival order.
        state = devices.setdefault(device_id, _DeviceState())
        if status == "ok":
            state.ok += 1
        else:
            state.error += 1
        if sequence > state.last_sequence:
            state.last_sequence = sequence
            state.last_status = status

    return {
        "totals": {
            "accepted": accepted,
            "duplicates": duplicates,
            "errors": len(errors),
        },
        "errors": errors,
        "devices": [
            {
                "device_id": device_id,
                "ok": s.ok,
                "error": s.error,
                "last_sequence": s.last_sequence,
                "last_status": s.last_status,
            }
            for device_id, s in sorted(devices.items())
        ],
    }


# Stands in for a line whose bytes are not valid UTF-8. It is not valid JSON,
# so the line is reported as BAD_JSON without failing the rest of the file.
_UNDECODABLE_LINE = "\x00<undecodable>"


def summarize_file(path: str | Path) -> dict[str, Any]:
    """Read a JSON Lines file and summarize it.

    Raises OSError if the file cannot be read, so callers can report a real
    failure instead of an empty result.

    Lines are decoded one at a time (strict UTF-8). An undecodable line becomes
    BAD_JSON on its own; we never substitute replacement characters, because
    that could silently alter a device_id that must be preserved as supplied.
    """
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):  # tolerate a UTF-8 BOM
        data = data[3:]

    lines: list[str] = []
    for raw in split_lines_bytes(data):
        try:
            lines.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            lines.append(_UNDECODABLE_LINE)
    return summarize_lines(lines)


def split_lines_bytes(data: bytes) -> list[bytes]:
    """Split file bytes into lines.

    Only "\\n" (with an optional preceding "\\r") ends a line. A single trailing
    newline at end of file does not create an extra blank line, so a normally
    terminated file is not reported as having a BAD_JSON last line. Empty
    content yields no lines at all.
    """
    if data == b"":
        return []
    parts = data.split(b"\n")
    if parts[-1] == b"":
        parts.pop()
    return [p[:-1] if p.endswith(b"\r") else p for p in parts]
