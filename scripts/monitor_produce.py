#!/usr/bin/env python3
"""监控单次 produce job 直至结束。"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:8000/api/v1"
STORY_ID = "97d6f57696da48a5a2e0a1bff564b00f"
JOB_ID = sys.argv[1] if len(sys.argv) > 1 else ""


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    if not JOB_ID:
        print("usage: monitor_produce.py <job_id>")
        return 1
    start = time.time()
    while True:
        job = get(f"/jobs/{JOB_ID}")
        ps = get(f"/stories/{STORY_ID}/produce")
        elapsed = int(time.time() - start)
        print(
            f"[{elapsed:5d}s] job={job['status']:9s} produce={ps['produce_status']:8s} "
            f"chars={ps['characters']['ready']}/{ps['characters']['total']} "
            f"scenes={ps['scenes']['ready']}/{ps['scenes']['total']} "
            f"prompts={ps['shot_prompts']['ready']}/{ps['shot_prompts']['total']} "
            f"videos={ps['videos']['ready']}/{ps['videos']['total']} "
            f"qc_pass={ps['qc']['pass']}",
            flush=True,
        )
        if job["status"] in ("succeeded", "failed", "paused"):
            print("\n=== FINAL ===", flush=True)
            print(json.dumps({"job": job, "produce": ps}, ensure_ascii=False, indent=2))
            return 0 if job["status"] == "succeeded" else 1
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
