"""HTTP layer: exposes GET /summary for the configured JSON Lines file."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from device_summary.summarizer import summarize_file

DEFAULT_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "sample.jsonl"


def data_file_path() -> Path:
    """Path of the input file. Override with the DEVICE_DATA_FILE env var."""
    return Path(os.environ.get("DEVICE_DATA_FILE", DEFAULT_DATA_FILE))


app = FastAPI(title="Device message summary")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send visitors of the bare URL to the summary instead of a 404."""
    return RedirectResponse(url="/summary")


@app.get("/summary")
def get_summary() -> JSONResponse:
    path = data_file_path()
    try:
        return JSONResponse(summarize_file(path))
    except OSError as exc:
        # Missing file, permission denied, path is a directory, etc.
        # Report a failure, never an empty "successful" summary.
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "DATA_FILE_UNREADABLE",
                    "message": f"Could not read input file '{path.name}': "
                    f"{exc.strerror or type(exc).__name__}",
                }
            },
        )
