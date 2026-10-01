# Device message summary

Reads a JSON Lines file of simulated device messages and returns a summary. The summary has accepted/duplicate/error totals, an ordered error list and per-device stats. It is available from Python and over `GET /summary` (FastAPI).

## Prerequisites

- Python 3.10+ (tested on 3.13 on Windows and 3.10 on Linux)
- `pip`; no database, hardware or network services needed

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Run

```bash
uvicorn device_summary.api:app --reload
# then open http://127.0.0.1:8000/summary
```

Opening `http://127.0.0.1:8000/` redirects (307) to `/summary`.

The endpoint reads `data/sample.jsonl` by default. To point it at another file:

```bash
DEVICE_DATA_FILE=path/to/other.jsonl uvicorn device_summary.api:app
```

To see the failure case, point it at a missing file. It returns HTTP 503 with an error body:

```bash
DEVICE_DATA_FILE=missing.jsonl uvicorn device_summary.api:app
curl -i http://127.0.0.1:8000/summary
```

## Test

```bash
pytest -v
```

26 tests. The three required by the brief come first in `tests/test_summary.py`: the sample, a later-arriving lower sequence, and empty input. The remaining tests cover validation edge cases, line endings, bad bytes, the endpoint's success and failure responses, and the `/` redirect.

## Windows (PowerShell)

The commands above are for macOS/Linux. On Windows, from the project folder:

```powershell
# Setup
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

# Run, then open http://127.0.0.1:8000/summary
uvicorn device_summary.api:app --reload

# Test
pytest -v

# Failure case: point at a missing file (expect HTTP 503)
$env:DEVICE_DATA_FILE="missing.jsonl"; uvicorn device_summary.api:app

# Clear the variable afterwards so the sample file is used again
Remove-Item Env:DEVICE_DATA_FILE
```

If activation fails with "running scripts is disabled on this system", allow local scripts for your user once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Response shape

```json
{
  "totals": {"accepted": 3, "duplicates": 1, "errors": 1},
  "errors": [{"line": 4, "code": "BAD_JSON"}],
  "devices": [
    {"device_id": "D01", "ok": 1, "error": 1, "last_sequence": 3, "last_status": "error"},
    {"device_id": "D02", "ok": 0, "error": 1, "last_sequence": 2, "last_status": "error"}
  ]
}
```

Unreadable file → `503 {"error": {"code": "DATA_FILE_UNREADABLE", "message": "..."}}`

## Project layout

```
device_summary/summarizer.py   core logic (pure, no HTTP)
device_summary/api.py          FastAPI app exposing GET /summary
data/sample.jsonl              sample from the brief
tests/test_summary.py          pytest suite
```

## Assumptions

- **Error totals.** `totals.errors` is included because the brief's expected totals list "errors 1". It always equals `len(errors)`.
- **Non-object JSON is `INVALID_RECORD`.** A line like `[1,2]` or `"D01"` is valid JSON, so it is not `BAD_JSON`, but it is not a valid record either.
- **Repeated keys are `INVALID_RECORD`.** Python's `json` normally keeps the last value when a key repeats. That would silently turn a line with two `status` fields into a "valid" record, so these lines are rejected.
- **Line numbering.** Only `\n` ends a line, and `\r\n` is accepted. A final trailing newline does not count as an extra blank line, and an empty file has zero lines.
- **Invalid UTF-8 is `BAD_JSON`.** A line that is not valid UTF-8 is reported as `BAD_JSON` for that line only. Bytes are never replaced, because that could alter a `device_id`.
- **Device IDs.** IDs are kept exactly as supplied, including surrounding spaces, as long as they are not whitespace-only. Sorting is plain case-sensitive string order, so `"A" < "b"`.
- **Status code for an unreadable file.** 503 was chosen because the service is up but cannot reach its data. A 500 would also be defensible.
- **Status values.** `sequence` may be any integer ≥ 0 (not bool, float or numeric string). `status` must be exactly `ok` or `error`, and is case-sensitive.

## Known limitation

The whole file is read into memory, and the set of seen `(device_id, sequence)` pairs grows with input size. That is fine for the sample and for files of a few hundred MB. A continuous or very large stream would need line-by-line reading and a bounded or persistent dedup store.

## Unfinished work

- No request-level caching: the file is re-read and re-summarized on every request.
- The React page was not built; it is described below as the brief asks.

## Time spent

~1h 47m

## React page (not built)

- Fetch in a `useEffect` with `fetch("/summary")`, keeping a single state value such as `{status: "loading" | "error" | "success", data, error}`. Start as `loading` and show a spinner.
- Treat any non-2xx response (for example the 503 above) or a network exception as `error`. Show `error.message` from the body with a Retry button. Check `res.ok` before calling `res.json()`, because `fetch` does not reject on HTTP errors.
- On 200, show an "empty data" message ("No messages yet") when `totals.accepted === 0 && errors.length === 0`. A failed request must never fall through to this state.
- Otherwise render the totals, the device table (already sorted by the API) and the error list with line numbers.
- Use an `AbortController` in the effect cleanup so an unmounted page doesn't set state from a late response.
