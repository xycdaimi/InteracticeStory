from __future__ import annotations

import json
import re
from typing import Any

from backend.app.agents.compliance_prompts import SYSTEM, build_batch_user
from backend.app.ai.geekai_client import GeekAIClient
from backend.app.config import get_settings
from backend.app.models.enums import ComplianceStatus
from backend.app.models.story_graph import PlotLine, StoryGraph

_BATCH_SIZE = 6
_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def extract_json_object(text: str) -> dict[str, Any]:
    """从模型输出中抽出 JSON 对象；失败抛 ValueError。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty model content")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJ_RE.search(raw)
    if not m:
        raise ValueError("no JSON object found in model content")
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be object")
    return data


def normalize_status(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in {"pass", "passed", "ok", "accept", "accepted"}:
        return ComplianceStatus.passed.value
    if s in {"reject", "rejected", "fail", "failed"}:
        return ComplianceStatus.rejected.value
    raise ValueError(f"invalid compliance status: {raw!r}")


def apply_batch_results(lines: list[PlotLine], payload: dict[str, Any]) -> None:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("results must be a non-empty list")
    # 模型常把 line_index 标错；本批顺序与 lines 一致时按序覆盖索引
    if len(results) == len(lines):
        results = [
            {**item, "line_index": i}
            for i, item in enumerate(results)
            if isinstance(item, dict)
        ]
        payload = {**payload, "results": results}
    elif len(lines) == 1 and results:
        first = results[0]
        if isinstance(first, dict):
            results = [{**first, "line_index": 0}]
            payload = {**payload, "results": results}
    seen: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            raise ValueError("result item must be object")
        raw_idx = item.get("line_index")
        if not isinstance(raw_idx, int) or raw_idx < 0 or raw_idx >= len(lines):
            raise ValueError(f"invalid line_index in results: {raw_idx!r}")
        status = normalize_status(str(item.get("status") or ""))
        reasons = item.get("reasons") or []
        if not isinstance(reasons, list):
            raise ValueError("reasons must be a list")
        reason_strs = [str(r) for r in reasons]
        if status == ComplianceStatus.rejected.value and not reason_strs:
            raise ValueError(f"reject line_index {raw_idx} must include reasons")
        pl = lines[raw_idx]
        pl.compliance_status = status
        pl.reasons = reason_strs
        seen.add(raw_idx)
    missing = [i for i in range(len(lines)) if i not in seen]
    if missing:
        raise ValueError(f"results missing line_indices: {missing}")


def path_text_for_line(graph: StoryGraph, line: PlotLine) -> str:
    parts: list[str] = []
    for nid in line.node_path:
        node = graph.nodes.get(nid)
        if node is None:
            parts.append(f"- ({nid}) <missing>")
            continue
        summary = (node.summary or "").strip()
        if summary:
            parts.append(f"- [{node.kind.value}] {node.title}: {summary}")
        else:
            parts.append(f"- [{node.kind.value}] {node.title}")
        if node.script:
            parts.append(
                f"  script: in={node.script.dramatic_state_in[:60]} | "
                f"out={node.script.dramatic_state_out[:60]}"
            )
            for beat in node.script.beats[:3]:
                dlg = " / ".join(f"{d.speaker}「{d.line}」" for d in beat.dialogue) or "（无对白）"
                parts.append(
                    f"  第{beat.t_start:g}~{beat.t_end:g}s {beat.shot} {beat.action} {dlg}"
                )
        elif nid != graph.root_id:
            parts.append("  script: <缺失>")
    return "\n".join(parts)


async def review_plot_lines(
    graph: StoryGraph,
    inspiration: str,
    geekai: GeekAIClient,
) -> list[PlotLine]:
    """逐条剧情线 LLM 合规（遗留实现；裂变流水线已改为一轮 DAG，不再调用）。"""
    settings = get_settings()
    lines = graph.iter_plot_lines()
    if not lines:
        return []

    out: list[PlotLine] = []

    for batch in chunked(lines, _BATCH_SIZE):
        user_payload = [
            {
                "line_index": i,
                "path_text": path_text_for_line(graph, pl),
                "outcome": pl.outcome,
            }
            for i, pl in enumerate(batch)
        ]
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_batch_user(inspiration, user_payload)},
        ]
        last_err: Exception | None = None
        for _attempt in range(2):
            try:
                data = await geekai.chat(
                    messages,
                    model=settings.compliance_model,
                    tools=None,
                    tool_choice=None,
                )
                content = (
                    ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                    or ""
                )
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    )
                payload = extract_json_object(str(content))
                apply_batch_results(batch, payload)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001 — 解析或网络失败后重试
                last_err = exc
        if last_err is not None:
            raise RuntimeError(f"compliance batch failed: {last_err}") from last_err
        out.extend(batch)
    return out
