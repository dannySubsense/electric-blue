# Drop-Folder Transcription

Drop a video or audio file into a folder; get back `.txt` / `.srt` / `.vtt` / `.json`
transcripts. One worker (`transcribe_watch.py`), two backends:

| Backend | Where | Cost | Speed | Use for |
|---------|-------|------|-------|---------|
| `api`   | Groq (or any OpenAI-compatible endpoint) | ~$0.04 / hr audio | seconds (faster than realtime) | "I want it now" |
| `local` | faster-whisper on the box (CPU or GPU) | free / offline | realtime-ish on CPU, fast on GPU | batch, offline, long files |

**Routing model (R630):** an always-on service watches `inbox/` using the **API**
backend; a nightly cron drains `batch/` using the **local** backend. Drop a file in
whichever folder matches how fast you need it.

---

## Files in this bundle

- `transcribe_watch.py` — the worker (both backends)
- `transcribe.service` — systemd unit for the R630 (API backend)
- `install_windows_service.ps1` — installs the worker as a Windows service on the ASUS (local GPU)
- `README.md` — this file

---

## Prerequisites (both machines)

- Python 3.10+
- `ffmpeg` on PATH
  - Linux: `sudo apt install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
- For the **api** backend: a Groq API key from <https://console.groq.com> (free tier works)

First run of the **local** backend downloads the model (~1.5 GB for `distil-large-v3`)
to `~/.cache/huggingface`; after that it is 100% offline.

---

## A. R630 — dual backend (API service + local cron)

```bash
# 1. Layout + venv
sudo mkdir -p /opt/transcribe && sudo chown $USER /opt/transcribe
cd /opt/transcribe
python3 -m venv venv
./venv/bin/pip install faster-whisper watchdog requests
sudo apt install -y ffmpeg

# 2. Worker + folders
cp ~/transcribe_watch.py .
mkdir -p data/inbox data/batch

# 3. Groq key (kept out of the unit file)
echo 'WHISPER_API_KEY=gsk_your_groq_key_here' > transcribe.env
chmod 600 transcribe.env

# 4. API service — watches inbox/, instant
cp ~/transcribe.service /etc/systemd/system/      # edit User= if not dclarke
sudo systemctl daemon-reload
sudo systemctl enable --now transcribe

# 5. Local batch — drains batch/ nightly at 02:00
crontab -e
```

Add this cron line (one line):

```cron
0 2 * * * cd /opt/transcribe && WHISPER_BACKEND=local TRANSCRIBE_BASE=/opt/transcribe/data TRANSCRIBE_INPUT=/opt/transcribe/data/batch WHISPER_MODEL=distil-large-v3 WHISPER_DEVICE=cpu ./venv/bin/python transcribe_watch.py --once >> /opt/transcribe/data/cron.log 2>&1
```

**Result:**
- `data/inbox/`  → Groq, transcript back in seconds
- `data/batch/`  → free local pass at 2am
- both write to `data/transcripts/`, sources move to `data/done/` (or `data/failed/`)
- the JSON output carries a `"backend"` field so you can tell which path produced it

---

## B. ASUS ROG (4090) — local GPU service

From an **elevated** PowerShell, in the folder containing both
`install_windows_service.ps1` and `transcribe_watch.py`:

```powershell
winget install Gyan.FFmpeg          # if ffmpeg isn't already on PATH
.\install_windows_service.ps1
```

This creates `C:\transcribe\`, builds a venv, installs faster-whisper + the CUDA
DLLs (cuDNN/cuBLAS), registers the `WhisperTranscribe` service via NSSM, and starts it.

- Drop files in `C:\transcribe\inbox`
- Outputs in `C:\transcribe\transcripts`, logs in `C:\transcribe\service.log`
- Defaults: `large-v3` on `cuda`. Manage with `nssm edit WhisperTranscribe`.

To point this box at the API instead of local GPU, add `WHISPER_BACKEND=api` and
`WHISPER_API_KEY=...` to the service environment (and `pip install requests` in the venv).

> The ASUS is a laptop, so the service only runs while it's awake — great for fast
> one-offs on the road, but the R630 is the always-on workhorse.

---

## Configuration reference (env vars)

| Variable | Default | Notes |
|----------|---------|-------|
| `WHISPER_BACKEND` | `local` | `local` or `api` |
| `TRANSCRIBE_BASE` | `~/transcribe` | root for inbox/transcripts/done/failed |
| `TRANSCRIBE_INPUT` | `<BASE>/inbox` | override to watch/drain a different folder |
| `WHISPER_LANG` | _(autodetect)_ | set `en` to skip detection |
| **local** | | |
| `WHISPER_MODEL` | `distil-large-v3` | `tiny`…`large-v3`, `distil-large-v3` |
| `WHISPER_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `WHISPER_COMPUTE` | `auto` | `float16` (GPU) / `int8` (CPU) |
| **api** | | |
| `WHISPER_API_BASE` | `https://api.groq.com/openai/v1` | any OpenAI-compatible endpoint |
| `WHISPER_API_MODEL` | `whisper-large-v3-turbo` | OpenAI: `whisper-1` |
| `WHISPER_API_KEY` | _(none)_ | required for api backend |

### Model cheat-sheet (local, CPU on the R630)
- `distil-large-v3` — best balance, ~5–6× faster than large-v3, English-focused. **Recommended.**
- `medium` — multilingual, slower.
- `large-v3` — highest accuracy, slow on CPU; fine for overnight.

---

## Run manually (no service)

```bash
python transcribe_watch.py                 # watch INPUT_DIR
python transcribe_watch.py --once          # process current folder, exit
python transcribe_watch.py --file clip.mp4  # single file
```

---

## Shared inbox over the network (optional)

Since the R630 runs TrueNAS, export an SMB/NFS share and point it at the queue so you
can drop files from your laptop or the NYC office straight into the R630's pipeline:

- Share `/opt/transcribe/data/inbox` (API/instant) and `/opt/transcribe/data/batch` (overnight).
- Or set `TRANSCRIBE_BASE` to a path on the NAS dataset to host the whole queue there.

---

## Verify / monitor

```bash
systemctl status transcribe          # service health
journalctl -u transcribe -f          # live service log (API path)
tail -f /opt/transcribe/data/cron.log  # nightly local-batch log
```

A successful run logs: `Done: <file> [en, 1830s audio, 6s wall] -> .../transcripts`.

---

## Troubleshooting

- **`ffmpeg: not found`** — install it, and make sure it's on the *service* PATH
  (Windows services don't inherit your user PATH; the installer handles this, or pass
  `-FfmpegDir`).
- **Windows GPU is slow / runs on CPU** — CTranslate2 can't find cuDNN. The installer
  injects the pip cuDNN/cuBLAS DLL paths into the service env; confirm via
  `nssm edit WhisperTranscribe` → Environment, or install the CUDA 12 toolkit + cuDNN 9 system-wide.
- **API error: file too large** — the 25 MB upload cap ≈ 50 min of audio. Route long
  files to `batch/` (local has no cap).
- **NSSM env didn't stick** — `nssm edit WhisperTranscribe` → Environment tab, paste the
  `KEY=VALUE` lines, restart the service.
- **Nothing happens on drop** — the worker waits ~2s for file size to stabilize (so it
  doesn't grab a half-copied file); large copies just take a moment.

---

## Optional next steps
- **Speaker labels** — swap the local core for WhisperX (word alignment + diarization).
- **Cheaper bulk** — add a Groq Batch API backend (50% off, ~1-day turnaround) for big overnight loads.
- **Completion ping** — notify on OpenClaw/Teams when a transcript lands.
