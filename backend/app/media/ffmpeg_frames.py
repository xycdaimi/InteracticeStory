from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found in PATH; required for last-frame extraction")
    return path


def extract_last_frame(video_path: Path, dest: Path) -> Path:
    """从视频末尾抽取一帧写入 dest。"""
    ffmpeg = _require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-sseof",
        "-0.1",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg extract_last_frame failed: {proc.stderr[:500]}")
    if not dest.exists():
        raise RuntimeError("ffmpeg did not produce last frame output")
    return dest


async def extract_last_frame_async(video_path: Path, dest: Path) -> Path:
    return await asyncio.to_thread(extract_last_frame, video_path, dest)
