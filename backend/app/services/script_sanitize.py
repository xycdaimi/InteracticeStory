from __future__ import annotations

from typing import Any


def _coerce_bool(val: Any, *, default: bool = True) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        s = val.strip().lower()
        if s in {"true", "1", "yes", "是", "y"}:
            return True
        if s in {"false", "0", "no", "否", "n"}:
            return False
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return bool(val)
    return default


def sanitize_script_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """修正模型常见 visual_plan 冲突与类型错误。"""
    data = dict(raw)
    if "duration_seconds" in data:
        try:
            data["duration_seconds"] = int(data["duration_seconds"])
        except (TypeError, ValueError):
            pass
    vp = dict(data.get("visual_plan") or {})
    hidden = {str(x).strip() for x in (vp.get("hidden_or_pov_only_ids") or []) if str(x).strip()}
    first = dict(vp.get("first_frame") or {})
    if "required" in first:
        first["required"] = _coerce_bool(first.get("required"), default=True)
    covered = {
        str(x).strip() for x in (first.get("covers_character_ids") or []) if str(x).strip()
    }
    refs_raw = list(vp.get("character_refs") or [])
    refs: list[dict[str, Any]] = []
    ref_ids: set[str] = set()
    for r in refs_raw:
        if isinstance(r, str):
            r = {"character_id": r}
        if not isinstance(r, dict):
            continue
        cid = str(r.get("character_id") or r.get("id") or "").strip()
        if not cid or cid in hidden or cid in covered or cid in ref_ids:
            continue
        ref_ids.add(cid)
        refs.append({**r, "character_id": cid})
    # 双向去重：首帧已出镜的不进 refs；refs 里有的也不重复进 covers
    covered -= hidden
    covered -= ref_ids
    first["covers_character_ids"] = sorted(covered)
    vp["character_refs"] = refs
    vp["hidden_or_pov_only_ids"] = sorted(hidden)
    vp["first_frame"] = first
    data["visual_plan"] = vp
    return data


def sanitize_beat_node(row: dict[str, Any]) -> dict[str, Any]:
    """裂变/延长工具入参：对每个节点的 script 做 sanitize。"""
    out = dict(row)
    script = out.get("script")
    if isinstance(script, dict):
        out["script"] = sanitize_script_dict(script)
    return out


def ground_branch_script(
    *,
    parent_dramatic_state_out: str,
    label: str,
    script: dict[str, Any],
) -> dict[str, Any]:
    """分支剧本结构接地：承接父节点 out，首拍体现玩家选项（非绕过质检，是补齐硬约束）。"""
    data = sanitize_script_dict(script)
    pout = parent_dramatic_state_out.strip()
    opt = label.strip()
    cin = str(data.get("dramatic_state_in") or "").strip()
    if pout:
        head = pout[: min(20, len(pout))]
        if not (cin.startswith(head) or (head and head in cin)):
            data["dramatic_state_in"] = (
                f"{pout}；{opt}" if opt else pout
            )[:240]

    beats = data.get("beats")
    if not isinstance(beats, list) or not beats:
        return data
    first = dict(beats[0]) if isinstance(beats[0], dict) else {}
    blob_parts = [str(first.get("action") or ""), str(first.get("shot") or "")]
    for d in first.get("dialogue") or []:
        if isinstance(d, dict):
            blob_parts.append(str(d.get("line") or ""))
    blob = "".join(blob_parts)
    if opt and opt not in blob:
        dlg = list(first.get("dialogue") or [])
        if dlg and isinstance(dlg[0], dict):
            line = str(dlg[0].get("line") or "").strip()
            dlg[0] = {**dlg[0], "line": f"{opt}，{line}" if line else opt}
        else:
            dlg = [{"speaker": "主角", "line": opt}]
        first["dialogue"] = dlg
        beats = [first, *beats[1:]]
        data["beats"] = beats
    return data
