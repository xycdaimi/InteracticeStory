#!/usr/bin/env python3
"""从灵感创建故事起，跑裂变 → 生产，打印阶段性进度。"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:8000/api/v1"
INSPIRATION = "讲一个桃园三结义的故事"


def api(method: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            detail = json.loads(raw).get("detail", raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e


def poll_fission(story_id: str, job_id: str, max_wait_s: int = 7200) -> str:
    start = time.time()
    last_phase = ""
    while time.time() - start < max_wait_s:
        story = api("GET", f"/stories/{story_id}")
        meta = story["meta"]
        phase = meta["phase"]
        if phase != last_phase:
            print(
                f"[裂变] phase={phase} lines={meta['line_count']} "
                f"endings={meta['ending_count']}",
                flush=True,
            )
            last_phase = phase
        if phase in ("done", "failed"):
            job = api("GET", f"/jobs/{job_id}")
            if job["status"] == "failed":
                raise RuntimeError(f"裂变 job 失败: {job.get('error')}")
            return phase
        time.sleep(15)
    raise TimeoutError("裂变超时")


def poll_produce(story_id: str, job_id: str, max_wait_s: int = 14400) -> dict:
    start = time.time()
    while time.time() - start < max_wait_s:
        job = api("GET", f"/jobs/{job_id}")
        ps = api("GET", f"/stories/{story_id}/produce")
        print(
            f"[生产] job={job['status']} produce={ps['produce_status']} "
            f"chars={ps['characters']['ready']}/{ps['characters']['total']} "
            f"scenes={ps['scenes']['ready']}/{ps['scenes']['total']} "
            f"prompts={ps['shot_prompts']['ready']}/{ps['shot_prompts']['total']} "
            f"videos={ps['videos']['ready']}/{ps['videos']['total']} "
            f"frames={ps.get('frames', {}).get('ready', 0)}/{ps.get('frames', {}).get('total', 0)} "
            f"qc_pass={ps['qc']['pass']}",
            flush=True,
        )
        if job["status"] in ("succeeded", "failed", "paused"):
            return {"job": job, "produce": ps}
        time.sleep(20)
    raise TimeoutError("生产超时")


def main() -> int:
    print("=== 1. 创建故事（灵感输入）===", flush=True)
    created = api("POST", "/stories", {"inspiration": INSPIRATION})
    story_id = created["story_id"]
    print(f"story_id={story_id} phase={created['phase']}", flush=True)

    print("=== 2. 启动裂变 ===", flush=True)
    fission = api("POST", f"/stories/{story_id}/fission")
    job_id = fission["job_id"]
    print(f"fission_job={job_id}", flush=True)

    print("=== 3. 等待裂变完成（MIN_STORY_LINES=30，可能较久）===", flush=True)
    phase = poll_fission(story_id, job_id)
    if phase != "done":
        print("裂变未成功结束", flush=True)
        return 1

    story = api("GET", f"/stories/{story_id}")
    print(
        f"裂变完成: lines={story['meta']['line_count']} "
        f"endings={story['meta']['ending_count']}",
        flush=True,
    )

    try:
        api("GET", f"/stories/{story_id}/production-blueprint")
    except RuntimeError as e:
        print(f"blueprint 不可用: {e}", flush=True)
        return 1

    print("=== 4. 启动生产 ===", flush=True)
    produce = api("POST", f"/stories/{story_id}/produce")
    produce_job = produce["job_id"]
    print(f"produce_job={produce_job}", flush=True)

    print("=== 5. 等待生产 ===", flush=True)
    result = poll_produce(story_id, produce_job)
    job = result["job"]
    ps = result["produce"]
    print("=== 结果 ===", flush=True)
    print(json.dumps({"story_id": story_id, "job": job, "produce": ps}, ensure_ascii=False, indent=2))
    return 0 if job["status"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
