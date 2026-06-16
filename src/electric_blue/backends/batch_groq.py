"""Async batch transcription backend for Groq Batch API.

AsyncBackend Protocol + GroqBatchBackend + make_groq_batch_backend factory.

NOT registered in _REGISTRY — constructed directly by handle_batch() and drain_batch() (A6).
If WHISPER_BACKEND=batch is set, get_backend() raises RuntimeError — correct INV-2 behavior.

HTTP mock seam: module-level ``import requests``; tests patch:
    electric_blue.backends.batch_groq.requests.post
    electric_blue.backends.batch_groq.requests.get

Audio mock seam: ``from .. import audio``; tests patch:
    electric_blue.backends.batch_groq.audio.extract
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Protocol

import requests

from .. import audio
from ..backends.base import Capabilities, Transcript
from ..batch_store import JobRef, JobStatus
from ..config import Config
from ..models import Segment, TranscriptInfo
from ..staging import UrlStager, make_stager

log = logging.getLogger(__name__)


class AsyncBackend(Protocol):
    """Structural protocol for asynchronous transcription backends.

    Implementors require no explicit inheritance — structural match suffices.
    Callers of the async path (handle_batch, drain_batch) use this type for injection points.
    """

    name: str
    capabilities: Capabilities

    def submit(self, cfg: Config, src: Path) -> JobRef: ...

    def poll(self, cfg: Config, job: JobRef) -> JobStatus: ...

    def fetch(self, cfg: Config, job: JobRef) -> Transcript: ...


class GroqBatchBackend:
    """Concrete AsyncBackend implementation.

    Constructor takes a UrlStager (dependency injection for testability).
    Production callers use make_groq_batch_backend(cfg) which constructs FunnelStager internally.
    Not registered in _REGISTRY; never dispatched via transcribe() (A6).
    """

    name: str = "batch"
    capabilities: Capabilities = Capabilities(
        supports_diarization=False,
        max_upload_mb=None,  # size cap enforced internally via cfg.batch_max_mb
        needs_network=True,
        needs_gpu_recommended=False,
        is_async=True,
    )

    def __init__(self, stager: UrlStager) -> None:
        self.stager = stager

    def submit(self, cfg: Config, src: Path) -> JobRef:
        """Encode source → stage MP3 → upload JSONL → create batch → return JobRef.

        Steps follow 02-ARCHITECTURE §5 (URL-only input — D6 correction; no audio file upload).
        """
        # Step 1: API key guard — before any network call (ASYNC-9, INV-2)
        if not cfg.batch_api_key:
            raise RuntimeError(
                "GROQ_BATCH_API_KEY (or WHISPER_API_KEY) is not set — "
                "batch submission requires a batch API key."
            )

        # Step 2: Funnel URL guard (A3, INV-2)
        if not cfg.batch_funnel_base_url:
            raise RuntimeError(
                "TRANSCRIBE_BATCH_FUNNEL_URL is not set — "
                "batch submission requires a public staging base URL."
            )

        # Steps 3–5: encode, size-check, and stage inside a TemporaryDirectory.
        # The TemporaryDirectory is exited after stage() copies the file to batch_stage_dir;
        # the staged copy persists there until stager.unstage() is called.
        with tempfile.TemporaryDirectory() as tmp:
            # Step 3: encode to compressed mono MP3 (mirrors api.py path)
            # Named f"{src.stem}.mp3" (B3/STAG-7): unique per source, no filename collisions.
            mp3_tmp = Path(tmp) / f"{src.stem}.mp3"
            audio.extract(cfg, src, mp3_tmp, compressed=True)

            # Step 4: size check — before any requests.post (ASYNC-11)
            size_mb = mp3_tmp.stat().st_size / 1e6
            if size_mb > cfg.batch_max_mb:
                raise RuntimeError(
                    f"{src.name}: encoded audio is {size_mb:.0f} MB "
                    f"(> {cfg.batch_max_mb} MB batch cap). "
                    "Reduce the file or raise TRANSCRIBE_BATCH_MAX_MB."
                )

            # Step 5: stage MP3 to public URL — errors propagate to caller (STAG-6)
            staged_url = self.stager.stage(mp3_tmp)
        # mp3_tmp deleted here; staged copy in batch_stage_dir persists.

        # Step 6: build the JSONL request line (D6: "url" key, no "file" key)
        body: dict = {
            "url": staged_url,
            "model": cfg.api_model,
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
        }
        if cfg.language:  # ASYNC-10: include "language" only when set
            body["language"] = cfg.language

        request_obj: dict = {
            "custom_id": f"eb-{src.stem}",
            "method": "POST",
            "url": "/v1/audio/transcriptions",
            "body": body,
        }
        jsonl_bytes = (json.dumps(request_obj) + "\n").encode("utf-8")

        # Step 7: upload JSONL to /files
        files_resp = requests.post(
            f"{cfg.api_base_url}/files",
            headers={"Authorization": f"Bearer {cfg.batch_api_key}"},
            files={"file": ("requests.jsonl", jsonl_bytes, "application/jsonl")},
            data={"purpose": "batch"},
            timeout=60,
        )
        files_resp.raise_for_status()
        jsonl_file_id: str = files_resp.json()["id"]

        # Step 8: create the batch job
        batch_resp = requests.post(
            f"{cfg.api_base_url}/batches",
            headers={"Authorization": f"Bearer {cfg.batch_api_key}"},
            json={
                "input_file_id": jsonl_file_id,
                "endpoint": "/v1/audio/transcriptions",
                "completion_window": cfg.batch_completion_window,
            },
            timeout=60,
        )
        batch_resp.raise_for_status()
        batch_id: str = batch_resp.json()["id"]

        # Step 9: return JobRef (output_file_id is None until poll() returns succeeded=True)
        return JobRef(
            job_id=batch_id,
            jsonl_file_id=jsonl_file_id,
            staged_url=staged_url,
        )

    def poll(self, cfg: Config, job: JobRef) -> JobStatus:
        """Poll Groq Batch API for job status and map to JobStatus.

        Status mapping (02-ARCHITECTURE §5):
          "completed"          → terminal=True,  succeeded=True,  output_file_id=<id>
          "failed"             → terminal=True,  succeeded=False, output_file_id=None
          "expired"            → terminal=True,  succeeded=False, output_file_id=None
          "cancelled"          → terminal=True,  succeeded=False, output_file_id=None
          any other / unknown  → terminal=False, succeeded=False  (ASYNC-12 conservative)
        """
        resp = requests.get(
            f"{cfg.api_base_url}/batches/{job.job_id}",
            headers={"Authorization": f"Bearer {cfg.batch_api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        raw: str = data.get("status", "")

        if raw == "completed":
            return JobStatus(
                raw=raw,
                terminal=True,
                succeeded=True,
                output_file_id=data.get("output_file_id"),
                error=None,
            )
        if raw == "failed":
            return JobStatus(
                raw=raw,
                terminal=True,
                succeeded=False,
                output_file_id=None,
                error=str(data.get("errors") or "batch job failed"),
            )
        if raw == "expired":
            return JobStatus(
                raw=raw,
                terminal=True,
                succeeded=False,
                output_file_id=None,
                error="expired",
            )
        if raw == "cancelled":
            return JobStatus(
                raw=raw,
                terminal=True,
                succeeded=False,
                output_file_id=None,
                error="cancelled",
            )
        # Conservative: any unknown or in-progress status → not terminal; drain retries (ASYNC-12)
        return JobStatus(
            raw=raw,
            terminal=False,
            succeeded=False,
            output_file_id=None,
            error=None,
        )

    def fetch(self, cfg: Config, job: JobRef) -> Transcript:
        """Fetch output file content and parse JSONL into Transcript.

        job.output_file_id must be set by the caller (drain sets it from the poll result).
        Segment parsing mirrors api.py verbose_json handling exactly (ASYNC-8 fallback included).
        """
        resp = requests.get(
            f"{cfg.api_base_url}/files/{job.output_file_id}/content",
            headers={"Authorization": f"Bearer {cfg.batch_api_key}"},
            timeout=120,
        )
        resp.raise_for_status()

        # Parse the first line of the JSONL output
        first_line = resp.text.strip().splitlines()[0]
        line_data = json.loads(first_line)
        body: dict = line_data["response"]["body"]

        # Mirror api.py segment parsing exactly
        segs = body.get("segments") or []
        segments = [
            Segment(
                start=s.get("start", 0.0),
                end=s.get("end", 0.0),
                text=(s.get("text") or "").strip(),
            )
            for s in segs
        ]
        # ASYNC-8: fallback to single synthetic segment when no segments but text is present
        if not segments and body.get("text"):
            segments = [
                Segment(
                    start=0.0,
                    end=float(body.get("duration") or 0.0),
                    text=body["text"].strip(),
                )
            ]

        info = TranscriptInfo(
            language=body.get("language") or cfg.language or "unknown",
            language_probability=None,
            duration=round(
                float(body.get("duration") or 0.0), 2
            ),  # mirrors api.py round(float(...), 2)
            backend=f"batch:{cfg.api_model}",
        )
        return Transcript(segments=segments, info=info)


def make_groq_batch_backend(cfg: Config) -> GroqBatchBackend:
    """Factory: construct GroqBatchBackend with FunnelStager from cfg.

    Raises RuntimeError if cfg.batch_funnel_base_url is empty (propagated from make_stager).
    """
    stager = make_stager(cfg)
    return GroqBatchBackend(stager)
