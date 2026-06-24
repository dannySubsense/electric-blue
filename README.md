# electric-blue


Blue, blue
I will sit right down
Waiting for the gift of sound and vision
And I will sing
Waiting for the gift of sound and vision
Drifting into my solitude
Over my head

Don't you wonder sometimes
'Bout sound and vision?

Drop a video or audio file into a watched folder; get back `.txt` / `.srt` / `.vtt` / `.json`
transcripts. Two interchangeable backends:

| Backend | Where it runs | Cost | Speed | Best for |
|---------|--------------|------|-------|----------|
| `api` | Any OpenAI-compatible endpoint (Groq, OpenAI, etc.) | API pricing | Seconds (faster than realtime) | "I want it now" |
| `local` | faster-whisper on any server or workstation | Free / offline | Realtime-ish on CPU, fast on GPU | Batch, offline, long files |

A common pattern: an always-on service watches an inbox with the **API** backend for instant
results; a nightly cron drains a batch folder with the **local** backend for free processing.

> This README is evolving. Deploy examples live in `deploy/`.

---

## Install

```bash
pip install electric-blue               # base install (api backend)
pip install "electric-blue[local]"      # + faster-whisper for local/GPU backend
```

**System requirement:** `ffmpeg` must be on `PATH` (or set `FFMPEG_BIN` to its path).

- Linux: `sudo apt install ffmpeg`
- macOS: `brew install ffmpeg`
- Windows: `winget install Gyan.FFmpeg`

> **Diarization (speaker-labelled transcripts):** deferred to 0.2.0.

### Development setup

```bash
make dev   # editable install (.[local,dev]) + activate black/ruff pre-commit hooks
make gate  # black --check + ruff + pytest (non-smoke); the merge gate
make smoke # real tiny-model end-to-end (needs ffmpeg + faster-whisper)
```

`make dev` installs the package **editable** so the test suite runs against this checkout's
`src/`. A gate test (`tests/test_install_editable.py`) enforces this — a non-editable/stale
install fails `make gate` rather than silently verifying a copy (see `docs/INVARIANTS.md` INV-14).

---

## Quickstart

### Drop-folder watch (daemon / service)

```bash
# Set your backend and drop-folder root, then start watching:
export WHISPER_BACKEND=api
export WHISPER_API_KEY=your_key_here
export TRANSCRIBE_BASE=/path/to/transcribe

electric-blue
# or: python -m electric_blue
```

Drop any media file into `$TRANSCRIBE_BASE/inbox/`. Transcripts appear in
`$TRANSCRIBE_BASE/transcripts/`. Processed files move to `done/` (or `failed/` on error).

### One-shot (cron / CI)

```bash
WHISPER_BACKEND=local TRANSCRIBE_INPUT=/data/batch electric-blue --once
```

### Single file

```bash
electric-blue --file clip.mp4
```

---

## Configuration

All settings are env vars — no config file needed.

| Variable | Default | Notes |
|----------|---------|-------|
| `WHISPER_BACKEND` | `local` | `local` or `api` |
| `TRANSCRIBE_BASE` | `~/transcribe` | Root for inbox/transcripts/done/failed |
| `TRANSCRIBE_INPUT` | `<BASE>/inbox` | Watch/drain this folder |
| `TRANSCRIBE_OUTPUT` | `<BASE>/transcripts` | Write transcripts here |
| `TRANSCRIBE_DONE` | `<BASE>/done` | Processed files land here |
| `TRANSCRIBE_FAILED` | `<BASE>/failed` | Failed files land here |
| `WHISPER_LANG` | _(autodetect)_ | Set `en` to skip language detection |
| `FFMPEG_BIN` | `ffmpeg` | Path to ffmpeg binary if not on PATH |
| **local backend** | | |
| `WHISPER_MODEL` | `distil-large-v3` | `tiny` … `large-v3`, `distil-large-v3` |
| `WHISPER_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `WHISPER_COMPUTE` | `auto` | `float16` (GPU) / `int8` (CPU) |
| **api backend** | | |
| `WHISPER_API_BASE` | `https://api.groq.com/openai/v1` | Any OpenAI-compatible endpoint |
| `WHISPER_API_MODEL` | `whisper-large-v3-turbo` | Model name for the endpoint |
| `WHISPER_API_KEY` | _(none — required)_ | API key |
| **notifications** | | |
| `NOTIFY_WEBHOOK` | _(off)_ | POST a structured JSON event (`started`/`done`/`failed`) here; empty = disabled |
| `NOTIFY_FORMAT` | `generic` | `generic` (raw v1 payload) or `ntfy` (ntfy.sh envelope) |
| `NOTIFY_TIMEOUT_SEC` | `5.0` | Per-request timeout for the webhook POST (bounded, non-blocking) |
| `NOTIFY_RETRIES` | `0` | Extra attempts on network error / HTTP 5xx (4xx is never retried) |
| `NOTIFY_HMAC_SECRET` | _(off)_ | If set, signs the body with an `X-Electric-Blue-Signature: sha256=…` header |

The webhook is strictly optional and never blocks or fails the pipeline. The payload carries
`schema_version`, `event`, `file` (name only), `backend`, `started_at`/`finished_at` (UTC ISO-8601),
`wall_sec`, and per-event fields — never absolute paths or secrets.

---

## Deploy examples

See `deploy/` for generalized service templates:

- `deploy/transcribe.service` — systemd unit (Linux, API backend)
- `deploy/install_windows_service.ps1` — NSSM Windows service installer (local GPU)

Both are example templates. Replace the placeholder values before use.

---

## License

MIT — see `LICENSE`.
