# AI and reuse note

**Tools used.** I used Claude to help with the initial code and tests. I then reviewed the implementation, made changes where needed, and tested it myself. No existing or employer code was reused. The main libraries used are FastAPI, Uvicorn, pytest, and httpx.

**Changes and checks.**
- I went through the requirements and checked the main cases, including validation before duplicate checking and using the highest sequence number for the latest status.
- I specifically checked that `"sequence": true` is rejected, because Python treats booleans as integers.
- I used HTTP 503 when the input file cannot be read, rather than returning an empty summary.
- I also tested the application on Windows and added the required PowerShell commands to the README.
- The draft used `errors="replace"` when decoding the file, which could replace invalid bytes and still let the line be processed under a changed device ID. It was changed to strict decoding, so the affected line is reported as `BAD_JSON`; this is covered by a test.

**Defect found and fixed.** While testing manually I opened the bare URL (`http://127.0.0.1:8000/`) and got a 404, since the only route was `/summary`. I added a redirect from `/` to `/summary` (307) and a test that checks the redirect itself.

**Verification.** I ran the test suite with `pytest -v` and checked that the sample returns the expected summary. I also tested the API response for a missing input file.