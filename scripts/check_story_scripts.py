#!/usr/bin/env python3
"""故事剧本质量门禁：missing_script / no_dialogue / STATE_BREAK / dead_end / unreachable_ending。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.models.enums import NodeKind
from backend.app.services.consistency_check import check_consistency
from backend.app.services.script_continuity import check_node_script
from backend.app.services.story_repository import StoryRepository


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("用法: venv/bin/python scripts/check_story_scripts.py <story_id>", file=sys.stderr)
        return 2
    story_id = args[0]
    repo = StoryRepository()
    graph = repo.load_graph(story_id)

    findings: list[str] = []

    for nid, node in graph.nodes.items():
        if nid == graph.root_id:
            continue
        if node.script is None:
            findings.append(f"missing_script\t{nid}")
            continue
        for issue in check_node_script(nid, node.script):
            if issue.code == "NO_DIALOGUE":
                findings.append(f"no_dialogue\t{nid}\t{issue.message}")

    for item in check_consistency(story_id):
        code = item.get("code") or ""
        if code in {
            "missing_script",
            "dead_end",
            "unreachable_ending",
            "STATE_BREAK",
            "CHOICE_NOT_GROUNDED",
        }:
            findings.append(
                f"{code}\t{item.get('node_id')}\t{item.get('message')}"
            )

    # dedupe
    seen: set[str] = set()
    uniq: list[str] = []
    for line in findings:
        if line in seen:
            continue
        seen.add(line)
        uniq.append(line)

    for line in uniq:
        print(line)

    if uniq:
        print(f"FAIL: {len(uniq)} issue(s)", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
