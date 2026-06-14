"""Output writers — txt, srt, vtt, json."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .models import Segment, TranscriptInfo


def fmt_ts(seconds: float, sep: str) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_outputs(
    cfg: Config,
    out_dir: Path,
    stem: str,
    segments: list[Segment],
    info: TranscriptInfo,
) -> None:
    """Write all enabled output formats to *out_dir*."""
    seg_dicts = [s.to_dict() for s in segments]
    full = " ".join(s.text for s in segments).strip()

    if "txt" in cfg.output_formats:
        (out_dir / f"{stem}.txt").write_text(full + "\n", encoding="utf-8")

    if "srt" in cfg.output_formats:
        lines = []
        for i, s in enumerate(segments, 1):
            lines += [
                str(i),
                f"{fmt_ts(s.start, ',')} --> {fmt_ts(s.end, ',')}",
                s.text,
                "",
            ]
        (out_dir / f"{stem}.srt").write_text("\n".join(lines), encoding="utf-8")

    if "vtt" in cfg.output_formats:
        lines = ["WEBVTT", ""]
        for s in segments:
            lines += [f"{fmt_ts(s.start, '.')} --> {fmt_ts(s.end, '.')}", s.text, ""]
        (out_dir / f"{stem}.vtt").write_text("\n".join(lines), encoding="utf-8")

    if "json" in cfg.output_formats:
        payload = {**info.to_dict(), "text": full, "segments": seg_dicts}
        (out_dir / f"{stem}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
