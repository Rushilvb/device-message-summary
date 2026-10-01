"""Tests for the summarizer and the /summary endpoint.

The first three tests are the minimum set required by the brief.
The rest pin down validation edge cases and the HTTP failure path.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from device_summary.api import app
from device_summary.summarizer import summarize_file, summarize_lines

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample.jsonl"


def rec(device_id, sequence, status):
    return json.dumps({"device_id": device_id, "sequence": sequence, "status": status})


# --- Required test 1: the supplied sample ---------------------------------

def test_sample_file_matches_expected_summary():
    result = summarize_file(SAMPLE)

    assert result["totals"] == {"accepted": 3, "duplicates": 1, "errors": 1}
    assert result["errors"] == [{"line": 4, "code": "BAD_JSON"}]
    assert result["devices"] == [
        {"device_id": "D01", "ok": 1, "error": 1, "last_sequence": 3, "last_status": "error"},
        {"device_id": "D02", "ok": 0, "error": 1, "last_sequence": 2, "last_status": "error"},
    ]


# --- Required test 2: out-of-order arrival --------------------------------

def test_later_arriving_lower_sequence_does_not_replace_latest_status():
    result = summarize_lines([
        rec("D01", 5, "error"),
        rec("D01", 2, "ok"),  # arrives later, but is older
    ])

    (d01,) = result["devices"]
    assert d01["last_sequence"] == 5
    assert d01["last_status"] == "error"
    assert (d01["ok"], d01["error"]) == (1, 1)  # still counted


# --- Required test 3: empty input -----------------------------------------

def test_empty_input_returns_zero_totals_and_empty_lists(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")

    expected = {
        "totals": {"accepted": 0, "duplicates": 0, "errors": 0},
        "errors": [],
        "devices": [],
    }
    assert summarize_file(empty) == expected
    assert summarize_lines([]) == expected


# --- Validation edge cases ------------------------------------------------

@pytest.mark.parametrize(
    "line",
    [
        rec("", 1, "ok"),                 # empty id
        rec("   ", 1, "ok"),              # whitespace-only id
        rec(7, 1, "ok"),                  # id not a string
        rec("D01", -1, "ok"),             # negative sequence
        rec("D01", True, "ok"),           # bool is not an integer here
        rec("D01", 1.0, "ok"),            # float
        rec("D01", "1", "ok"),            # numeric string
        rec("D01", 1, "OK"),              # status is case-sensitive
        rec("D01", 1, None),
        '{"device_id": "D01", "sequence": 1}',                            # missing key
        '{"device_id": "D01", "sequence": 1, "status": "ok", "x": 1}',    # extra key
        '{"device_id": "D01", "sequence": 1, "status": "ok", "status": "error"}',  # repeated key
        "[1, 2, 3]",                      # valid JSON, not an object
        '"D01"',
    ],
)
def test_invalid_records_are_reported_and_skipped(line):
    result = summarize_lines([line, rec("D09", 0, "ok")])

    assert result["errors"] == [{"line": 1, "code": "INVALID_RECORD"}]
    assert result["totals"] == {"accepted": 1, "duplicates": 0, "errors": 1}


def test_blank_lines_are_bad_json_and_processing_continues():
    result = summarize_lines(["", "   ", "{not json", rec("D01", 0, "ok")])

    assert result["errors"] == [
        {"line": 1, "code": "BAD_JSON"},
        {"line": 2, "code": "BAD_JSON"},
        {"line": 3, "code": "BAD_JSON"},
    ]
    assert result["totals"]["accepted"] == 1


def test_duplicate_with_different_status_is_still_a_duplicate():
    result = summarize_lines([rec("D01", 1, "ok"), rec("D01", 1, "error")])

    assert result["totals"] == {"accepted": 1, "duplicates": 1, "errors": 0}
    assert result["devices"][0]["last_status"] == "ok"


def test_invalid_record_does_not_claim_the_pair_for_duplicate_checking():
    # Validate first: an invalid line must not make a later valid one a duplicate.
    bad = '{"device_id": "D01", "sequence": 1, "status": "maybe"}'
    result = summarize_lines([bad, rec("D01", 1, "ok")])

    assert result["totals"] == {"accepted": 1, "duplicates": 0, "errors": 1}


def test_device_ids_preserved_as_supplied_and_sorted():
    result = summarize_lines([rec("b", 0, "ok"), rec(" D01 ", 0, "ok"), rec("A", 0, "ok")])

    assert [d["device_id"] for d in result["devices"]] == [" D01 ", "A", "b"]


def test_file_line_endings(tmp_path):
    f = tmp_path / "crlf.jsonl"
    # CRLF endings and a trailing newline must not produce a phantom blank line.
    f.write_bytes((rec("D01", 0, "ok") + "\r\n" + rec("D01", 1, "ok") + "\r\n").encode())

    assert summarize_file(f)["totals"] == {"accepted": 2, "duplicates": 0, "errors": 0}


def test_undecodable_line_is_bad_json_without_failing_file(tmp_path):
    f = tmp_path / "bad_bytes.jsonl"
    f.write_bytes(b'{"device_id": "D\xff", "sequence": 0, "status": "ok"}\n'
                  + rec("D01", 0, "ok").encode() + b"\n")

    result = summarize_file(f)
    assert result["errors"] == [{"line": 1, "code": "BAD_JSON"}]
    assert result["totals"]["accepted"] == 1


# --- HTTP endpoint --------------------------------------------------------

def test_get_summary_returns_sample_result(monkeypatch):
    monkeypatch.delenv("DEVICE_DATA_FILE", raising=False)
    response = TestClient(app).get("/summary")

    assert response.status_code == 200
    assert response.json() == summarize_file(SAMPLE)


def test_get_summary_reports_unreadable_file_as_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_DATA_FILE", str(tmp_path / "does_not_exist.jsonl"))
    response = TestClient(app).get("/summary")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DATA_FILE_UNREADABLE"
    assert "totals" not in body  # never disguised as an empty success


def test_root_redirects_to_summary():
    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/summary"
