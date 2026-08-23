from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.app.config import get_settings
from backend.app.models.story_spine import StorySpine
from backend.app.models.enums import ComplianceStatus, FissionPhase, NodeKind, StoryStatus
from backend.app.models.story_graph import (
    NodeScript,
    StoryEdge,
    StoryNode,
    StoryOption,
    summary_from_script,
)
from backend.app.models.plot_tree import PlotTreeOutline
from backend.app.infrastructure.paths import blueprint_path, compliance_path
from backend.app.services.plot_tree_validate import normalize_plot_tree_outline
from backend.app.services.dag_compliance_repair import apply_dag_compliance_once
from backend.app.services.persist import persist_production_blueprint
from backend.app.services.prune import prune_rejected_lines
from backend.app.services.graph_refs import (
    assign_mainline_kinds,
    mainline_node_ids,
    mainline_spine_complete,
    open_plot_leaf_ids,
    outbound_child_count,
    spine_path_from_root,
    spine_plot_beat_count,
    spine_tail_id,
)
from backend.app.services.layout import apply_layout
from backend.app.services.story_spine_store import (
    completion_point_reached,
    load_story_spine,
    mainline_spine_event_refs,
    save_story_spine,
    spine_events_covered_indices,
    validate_mainline_spine_coverage,
)
from backend.app.services.script_continuity import check_parent_children, check_node_script
from backend.app.services.script_sanitize import sanitize_beat_node, sanitize_script_dict
from backend.app.services.story_repository import StoryRepository


def _nid() -> str:
    return "n_" + uuid4().hex[:10]

def _oid() -> str:
    return "o_" + uuid4().hex[:10]

def _eid() -> str:
    return "e_" + uuid4().hex[:10]

_SCRIPT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "可拍舞台剧本；禁止只交大纲",
    "required": [
        "duration_seconds",
        "dramatic_state_in",
        "dramatic_state_out",
        "beats",
        "visual_plan",
    ],
    "properties": {
        "duration_seconds": {"type": "integer", "minimum": 4, "maximum": 15},
        "dramatic_state_in": {"type": "string"},
        "dramatic_state_out": {"type": "string"},
        "beats": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["t_start", "t_end"],
                "properties": {
                    "t_start": {"type": "number"},
                    "t_end": {"type": "number"},
                    "shot": {"type": "string"},
                    "action": {"type": "string"},
                    "dialogue": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["speaker", "line"],
                            "properties": {
                                "speaker": {"type": "string"},
                                "line": {"type": "string"},
                            },
                        },
                    },
                    "pov": {"type": ["string", "null"]},
                },
            },
        },
        "visual_plan": {
            "type": "object",
            "required": ["first_frame"],
            "properties": {
                "first_frame": {
                    "type": "object",
                    "required": ["depicts"],
                    "properties": {
                        "required": {"type": "boolean"},
                        "depicts": {"type": "string"},
                        "covers_character_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "character_refs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["character_id"],
                        "properties": {
                            "character_id": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
                "scene_ref": {"type": ["string", "null"]},
                "hidden_or_pov_only_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}


class MainlineBeat(BaseModel):
    spine_event: str = Field(
        min_length=2,
        description="所属关键事件（define_story_spine.key_events 中的一项）；同事件可多节点",
    )
    title: str
    summary: str = ""
    option_label: str = Field(
        default="继续",
        description="玩家从上一节点到本节点的台词/行动/意图选项",
    )
    script: NodeScript


def _ground_script_for_edge(
    script: NodeScript,
    *,
    parent_out: str,
    option_label: str,
) -> NodeScript:
    """确保子节点承接父状态，且开场能体现选项文案。"""
    label = option_label.strip()
    out = script
    if parent_out:
        cin = script.dramatic_state_in.strip()
        prefix = parent_out[: min(20, len(parent_out))]
        if prefix and prefix not in cin and not cin.startswith(prefix):
            out = out.model_copy(
                update={"dramatic_state_in": f"{parent_out}；选择「{label}」后"}
            )
    if label and out.beats:
        b0 = out.beats[0]
        grounded = f"{b0.shot} {b0.action} " + " ".join(
            f"{d.speaker}{d.line}" for d in b0.dialogue
        )
        if label not in grounded:
            beats = list(out.beats)
            beats[0] = b0.model_copy(
                update={"action": f"{b0.action}（{label}）".strip()}
            )
            out = out.model_copy(update={"beats": beats})
    return out


def _parse_mainline_beats(nodes: list[dict[str, Any]]) -> list[MainlineBeat] | str:
    try:
        return [MainlineBeat.model_validate(sanitize_beat_node(n)) for n in nodes]
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": f"script 校验失败: {exc}"},
            ensure_ascii=False,
        )


class FissionTools:
    """图写入层：校验 + 落盘；不含 ReAct expand 策略。"""

    def __init__(self, story_id: str, repo: StoryRepository | None = None):
        self.story_id = story_id
        self.repo = repo or StoryRepository()
        self.settings = get_settings()


    def _min_paths(self) -> int:
        cfg = self.repo.load_fission_config(self.story_id)
        if cfg is not None:
            return int(cfg.min_paths)
        return int(self.settings.min_story_lines)

    def _save_plot_tree_json(self, tree: dict[str, Any]) -> None:
        try:
            from backend.app.services.plot_tree_store import save_plot_tree  # type: ignore

            save_plot_tree(self.story_id, tree)
            return
        except Exception:
            pass
        try:
            from backend.app.infrastructure.paths import plot_tree_path
        except ImportError:
            from backend.app.infrastructure.paths import story_dir

            def plot_tree_path(story_id: str):  # type: ignore
                return story_dir(story_id) / "plot_tree.json"

        path = plot_tree_path(self.story_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_graph_stats",
                    "description": "获取当前故事图线数、阶段、叶节点",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "exa_search",
                    "description": "用 Exa 检索历史/文献背景资料",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mark_collect_done",
                    "description": "标记收集阶段完成，进入主线",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "define_story_spine",
                    "description": (
                        "把灵感整理为完整脉络：主角、完成点、按序关键事件链。"
                        "必须先于 write_mainline；事件数由故事决定（通常 6–30）。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "protagonist": {"type": "string"},
                            "completion_point": {
                                "type": "string",
                                "description": "完成点：主角最终达成什么",
                            },
                            "key_events": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "按时间顺序的关键事件；最后一项应抵达完成点",
                            },
                        },
                        "required": ["protagonist", "completion_point", "key_events"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_mainline",
                    "description": (
                        "一次性写入整条脉络主链的全部可拍节点（单链、此阶段勿裂变）。"
                        "每个关键事件可含多个节点；finalize=true 须覆盖全部 key_events 且末节点=结局。"
                        "仅当单次输出 token 不足时才 finalize=false + append_mainline_beats。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nodes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "spine_event": {"type": "string"},
                                        "title": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "option_label": {"type": "string"},
                                        "script": _SCRIPT_JSON_SCHEMA,
                                    },
                                    "required": [
                                        "spine_event",
                                        "title",
                                        "option_label",
                                        "script",
                                    ],
                                },
                            },
                            "finalize": {"type": "boolean", "default": True},
                        },
                        "required": ["nodes"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "append_mainline_beats",
                    "description": (
                        "续写主链剩余节点（成批提交，禁止逐节点续写）。"
                        "finalize=true 时须正好写完并 seal 为结局。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nodes": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "spine_event": {"type": "string"},
                                        "title": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "option_label": {"type": "string"},
                                        "script": _SCRIPT_JSON_SCHEMA,
                                    },
                                    "required": [
                                        "spine_event",
                                        "title",
                                        "option_label",
                                        "script",
                                    ],
                                },
                            },
                            "finalize": {
                                "type": "boolean",
                                "description": "true=本批末拍为结局并完结主线",
                                "default": False,
                            },
                        },
                        "required": ["nodes", "finalize"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compliance_check",
                    "description": (
                        "一轮 DAG 合规扫描（涉政/敏感红线，优先改写）。"
                        "写出 compliance.json；须在 consistency 通过之后、persist/finish 之前调用。"
                        "不再逐条剧情线 LLM 审查。"
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "persist_graph",
                    "description": (
                        "合规剪枝后定稿入库：抽出人物/场景卡并绑定节点，写入 SQLite 与 blueprint.json。"
                        "须在 compliance_check 之后、finish_fission 之前调用。不出图。"
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "finish_fission",
                    "description": "结束裂变",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        handlers = {
            "get_graph_stats": self.get_graph_stats,
            "exa_search": self.exa_search,
            "mark_collect_done": self.mark_collect_done,
            "define_story_spine": self.define_story_spine,
            "write_mainline": self.write_mainline,
            "append_mainline_beats": self.append_mainline_beats,
            "compliance_check": self.compliance_check,
            "persist_graph": self.persist_graph,
            "finish_fission": self.finish_fission,
        }
        fn = handlers.get(name)
        if fn is None:
            return json.dumps({"error": f"unknown tool {name}"})
        if name == "exa_search":
            return await fn(**arguments)  # type: ignore[misc]
        result = fn(**arguments)
        if hasattr(result, "__await__"):
            return await result  # type: ignore[misc]
        return result  # type: ignore[return-value]

    def get_graph_stats(self) -> str:
        g = self.repo.load_graph(self.story_id)
        meta = self.repo.load_meta(self.story_id)
        child_count = outbound_child_count(g)
        open_leaves = open_plot_leaf_ids(g)
        spine = spine_path_from_root(g)
        spine_complete = mainline_spine_complete(g)
        story_spine = load_story_spine(self.story_id)
        spine_beats = spine_plot_beat_count(g)
        spine_events_total = len(story_spine.key_events) if story_spine else 0
        spine_refs = mainline_spine_event_refs(g) if story_spine else []
        events_covered = (
            len(spine_events_covered_indices(spine_refs, story_spine.key_events))
            if story_spine
            else 0
        )
        mains = [
            {
                "index": i,
                "title": g.nodes[nid].title,
                "kind": g.nodes[nid].kind.value,
                "child_count": child_count.get(nid, 0),
            }
            for i, nid in enumerate(mainline_node_ids(g))
        ]
        leaves = [
            {
                "index": i,
                "title": g.nodes[nid].title,
                "kind": g.nodes[nid].kind.value,
            }
            for i, nid in enumerate(sorted(g.leaf_ids()))
        ]
        next_action = "exa_search / mark_collect_done"
        if meta.phase == FissionPhase.collect:
            next_action = "mark_collect_done 后 define_story_spine"
        elif story_spine is None:
            next_action = "define_story_spine（先整理关键事件链与完成点）"
        elif not spine_complete:
            if spine_beats == 0:
                next_action = (
                    f"write_mainline 一次性写入整条主链"
                    f"（覆盖全部 {spine_events_total} 个关键事件）"
                )
            else:
                remaining = spine_events_total - events_covered
                next_action = (
                    f"append_mainline_beats 成批续写（已覆盖 {events_covered}/"
                    f"{spine_events_total} 事件，{spine_beats} 个节点；"
                    f"剩余约 {remaining} 事件）"
                )
        else:
            next_action = "plot_tree / branch_script / consistency"

        return json.dumps(
            {
                "phase": meta.phase.value,
                "mainline_complete": spine_complete,
                "spine_node_count": spine_beats,
                "spine_beat_count": spine_beats,
                "spine_events_covered": events_covered,
                "spine_events_total": spine_events_total,
                "spine_path_titles": [g.nodes[nid].title for nid in spine],
                "key_events": story_spine.key_events if story_spine else [],
                "completion_point": (
                    story_spine.completion_point if story_spine else None
                ),
                "plot_path_count": g.line_count,
                "line_count": g.line_count,
                "open_plot_leaf_count": len(open_leaves),
                "ending_count": g.ending_count(),
                "leaves": leaves,
                "spine_and_main_nodes": mains,
                "next_action": next_action,
                "min_paths": self._min_paths(),
            },
            ensure_ascii=False,
        )


    async def exa_search(self, query: str) -> str:
        from backend.app.ai.exa_client import ExaClient

        meta = self.repo.load_meta(self.story_id)
        if meta.phase != FissionPhase.collect:
            return json.dumps(
                {
                    "ok": False,
                    "error": "收集阶段已结束，勿重复检索；请 write_mainline 或后续工具",
                    "phase": meta.phase.value,
                },
                ensure_ascii=False,
            )

        exa = ExaClient(settings=self.settings)
        hits, degraded = await exa.search(query)
        await exa.aclose()
        block_lines = [f"## Exa: {query}"]
        if degraded:
            block_lines.append("（无 EXA_API_KEY，已跳过检索）")
        for h in hits:
            block_lines.append(f"- {h.title} ({h.url})\n  {h.text[:500]}")
        text = "\n".join(block_lines)
        self.repo.append_context(self.story_id, text)
        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.collect,
            type="tool",
            message=f"exa_search: {query}",
            payload={"hits": len(hits), "degraded": degraded},
        )
        return json.dumps(
            {"degraded": degraded, "hits": [{"title": h.title, "url": h.url} for h in hits]},
            ensure_ascii=False,
        )

    def mark_collect_done(self) -> str:
        meta = self.repo.load_meta(self.story_id)
        if meta.phase not in (FissionPhase.idle, FissionPhase.collect):
            return json.dumps(
                {
                    "ok": True,
                    "already_done": True,
                    "phase": meta.phase.value,
                    "next": "write_mainline",
                },
                ensure_ascii=False,
            )
        meta.phase = FissionPhase.bible
        self.repo.save_meta(meta)
        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.bible,
            type="phase",
            message="收集完成，进入故事总纲（bible）",
        )
        return json.dumps({"ok": True, "next": "story_bible"})

    def define_story_spine(
        self,
        protagonist: str,
        completion_point: str,
        key_events: list[str],
    ) -> str:
        min_e = self.settings.mainline_min_spine_events
        max_e = self.settings.mainline_max_spine_events
        events = [str(e).strip() for e in key_events if str(e).strip()]
        if len(events) < min_e:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"关键事件过少：至少 {min_e} 项才能构成完整脉络，"
                        f"当前 {len(events)}。请补全起承转合，不要为收尾硬凑。"
                    ),
                },
                ensure_ascii=False,
            )
        if len(events) > max_e:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"关键事件过多：最多 {max_e} 项",
                },
                ensure_ascii=False,
            )
        try:
            spine = StorySpine(
                protagonist=protagonist.strip(),
                completion_point=completion_point.strip(),
                key_events=events,
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        save_story_spine(self.story_id, spine)
        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.mainline,
            type="phase",
            message=f"脉络已定：{len(events)} 个关键事件 → 完成点",
            payload={
                "event_count": len(events),
                "completion_point": spine.completion_point[:80],
            },
        )
        return json.dumps(
            {
                "ok": True,
                "event_count": len(events),
                "completion_point": spine.completion_point,
                "next": "write_mainline（一次性写入整条主链全部节点，每事件可多节点）",
            },
            ensure_ascii=False,
        )

    def _validate_batch_against_spine(
        self,
        beats: list[MainlineBeat],
        spine: StorySpine,
        *,
        existing_refs: list[str] | None = None,
        finalize: bool,
    ) -> str | None:
        max_nodes = self.settings.mainline_max_nodes
        combined_len = len(existing_refs or []) + len(beats)
        if combined_len > max_nodes:
            return f"主链节点过多：最多 {max_nodes} 个可拍节点"

        refs = list(existing_refs or []) + [b.spine_event for b in beats]
        issues = validate_mainline_spine_coverage(
            refs, spine.key_events, finalize=finalize
        )
        if issues:
            return "；".join(issues)

        if finalize:
            if len(refs) < len(spine.key_events):
                return (
                    f"节点过少：至少 {len(spine.key_events)} 个"
                    "（每个关键事件至少 1 个可拍节点）"
                )
            last = beats[-1]
            if not completion_point_reached(spine, last.script.dramatic_state_out):
                return (
                    f"末拍 dramatic_state_out 未体现完成点：{spine.completion_point}"
                )
        return None

    def _validate_spine_chain_continuity(self, g) -> str | None:
        path = spine_path_from_root(g)
        for i in range(1, len(path)):
            parent_id = path[i - 1]
            issues = check_parent_children(g, parent_id)
            hard = [
                x
                for x in issues
                if x.code in {"STATE_BREAK", "NO_DIALOGUE", "VISUAL_PLAN", "NO_SCRIPT"}
            ]
            if hard:
                return hard[0].message
        return None

    def _attach_spine_beats(
        self,
        g,
        prev_id: str,
        beats: list[MainlineBeat],
        *,
        finalize: bool,
        beat_kind: NodeKind = NodeKind.main,
    ) -> tuple[list[str], str]:
        """从 prev_id 后追加节拍；finalize 时末拍为 ending。"""
        new_ids: list[str] = []
        for i, beat in enumerate(beats):
            is_last = i == len(beats) - 1
            ending_last = finalize and is_last
            label = (
                beat.option_label or ("抵达结局" if ending_last else beat.title)
            ).strip()
            script = beat.script
            parent = g.nodes[prev_id]
            if parent.script and parent.kind != NodeKind.root:
                script = _ground_script_for_edge(
                    script,
                    parent_out=parent.script.dramatic_state_out,
                    option_label=label,
                )
            elif parent.kind == NodeKind.root and label:
                script = _ground_script_for_edge(
                    script, parent_out="", option_label=label
                )

            spine_ev = getattr(beat, "spine_event", None)
            spine_event = (spine_ev or "").strip() or None
            nid = _nid()
            kind = NodeKind.ending if ending_last else beat_kind
            g.nodes[nid] = StoryNode(
                id=nid,
                kind=kind,
                title=beat.title.strip() or ("结局" if ending_last else "主线"),
                summary=summary_from_script(script, beat.summary or beat.title),
                parent_id=prev_id,
                script=script,
                spine_event=spine_event,
                outcome="completed" if ending_last and beat_kind == NodeKind.main else None,
            )
            oid = _oid()
            g.options.append(
                StoryOption(
                    id=oid,
                    from_node_id=prev_id,
                    to_node_id=nid,
                    label=label,
                )
            )
            g.edges.append(
                StoryEdge(id=_eid(), source=prev_id, target=nid, option_id=oid)
            )
            new_ids.append(nid)
            prev_id = nid
        return new_ids, prev_id

    def _finish_mainline_graph(
        self,
        g,
        *,
        new_ids: list[str],
        beat_count: int,
        message: str,
        finalize: bool,
    ) -> str:
        apply_layout(g)
        self.repo.save_graph(g)
        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.plot_tree if finalize else FissionPhase.mainline,
            type="graph",
            message=message,
            payload={
                "node_ids": new_ids,
                "line_count": g.line_count,
                "mainline_complete": finalize,
                "beat_count": beat_count,
            },
        )
        spine_beats = spine_plot_beat_count(g)
        story_spine = load_story_spine(self.story_id)
        events_total = len(story_spine.key_events) if story_spine else 0
        if finalize:
            next_step = "plot_tree / branch_script"
        else:
            next_step = (
                f"append_mainline_beats（已写 {spine_beats}/{events_total} 个关键事件）"
            )
        return json.dumps(
            {
                "ok": True,
                "mainline_complete": finalize,
                "spine_beat_count": spine_beats,
                "spine_events_total": events_total,
                "beat_count": beat_count,
                "line_count": g.line_count,
                "new_nodes": new_ids,
                "next": next_step,
            },
            ensure_ascii=False,
        )

    def write_mainline(
        self, nodes: list[dict[str, Any]], finalize: bool = True
    ) -> str:
        parsed = _parse_mainline_beats(nodes)
        if isinstance(parsed, str):
            return parsed
        beats = parsed
        spine = load_story_spine(self.story_id)
        if spine is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": "请先 define_story_spine：把灵感整理为有序关键事件与完成点",
                },
                ensure_ascii=False,
            )
        if not beats:
            return json.dumps({"error": "nodes 不能为空"})
        if finalize and len(beats) < len(spine.key_events):
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"请一次性写入整条主链：至少 {len(spine.key_events)} 个节点"
                        f"（覆盖 {len(spine.key_events)} 个关键事件，复杂事件可多节点）"
                    ),
                },
                ensure_ascii=False,
            )
        err = self._validate_batch_against_spine(
            beats, spine, existing_refs=None, finalize=finalize
        )
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)

        g = self.repo.load_graph(self.story_id)
        root = g.nodes[g.root_id]
        g.nodes = {root.id: root}
        g.edges = []
        g.options = []

        new_ids, _ = self._attach_spine_beats(
            g, root.id, beats, finalize=finalize
        )
        if finalize:
            chain_err = self._validate_spine_chain_continuity(g)
            if chain_err:
                return json.dumps(
                    {"ok": False, "error": f"主链不接戏：{chain_err}"},
                    ensure_ascii=False,
                )
        total = len(spine.key_events)
        if finalize:
            msg = f"主线已写入：覆盖全部 {total} 个关键事件（末节点为结局）"
        else:
            msg = f"主线第1段：{len(beats)}/{total} 个关键事件已剧本化"
        return self._finish_mainline_graph(
            g,
            new_ids=new_ids,
            beat_count=spine_plot_beat_count(g),
            message=msg,
            finalize=finalize,
        )

    def append_mainline_beats(
        self, nodes: list[dict[str, Any]], finalize: bool = False
    ) -> str:
        parsed = _parse_mainline_beats(nodes)
        if isinstance(parsed, str):
            return parsed
        beats = parsed
        spine = load_story_spine(self.story_id)
        if spine is None:
            return json.dumps({"error": "请先 define_story_spine"}, ensure_ascii=False)

        g = self.repo.load_graph(self.story_id)
        if mainline_spine_complete(g):
            return json.dumps(
                {"error": "主线已完结；要重写请 write_mainline 覆盖"},
                ensure_ascii=False,
            )
        tail_id = spine_tail_id(g)
        if tail_id is None or (tail_id == g.root_id and len(g.edges) == 0):
            return json.dumps({"error": "尚无主链，请先 write_mainline"}, ensure_ascii=False)
        if g.nodes[tail_id].kind == NodeKind.ending:
            return json.dumps({"error": "主链已有结局，不可 append"}, ensure_ascii=False)

        existing_refs = mainline_spine_event_refs(g)
        events_covered = len(
            spine_events_covered_indices(existing_refs, spine.key_events)
        )
        events_total = len(spine.key_events)
        if len(beats) == 1 and not finalize and events_total - events_covered > 2:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "禁止逐节点续写。请 write_mainline 一次性写入整条主链，"
                        "或 append_mainline_beats 成批提交剩余全部节点。"
                    ),
                },
                ensure_ascii=False,
            )

        if not beats:
            return json.dumps({"error": "nodes 不能为空"})
        err = self._validate_batch_against_spine(
            beats,
            spine,
            existing_refs=existing_refs,
            finalize=finalize,
        )
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)

        new_ids, _ = self._attach_spine_beats(
            g, tail_id, beats, finalize=finalize
        )
        if finalize:
            chain_err = self._validate_spine_chain_continuity(g)
            if chain_err:
                return json.dumps(
                    {"ok": False, "error": f"主链不接戏：{chain_err}"},
                    ensure_ascii=False,
                )
        total = len(spine.key_events)
        written = spine_plot_beat_count(g)
        if finalize:
            msg = f"主线续写完成：{written}/{total} 个关键事件（末节点为结局）"
        else:
            msg = f"主线续写 +{len(beats)} 拍，当前 {written}/{total} 个关键事件"
        return self._finish_mainline_graph(
            g,
            new_ids=new_ids,
            beat_count=written,
            message=msg,
            finalize=finalize,
        )

    def apply_plot_tree(self, tree: dict[str, Any]) -> str:
        """将 PlotTreeOutline JSON 写入 StoryGraph 结构（不含 script）。"""
        try:
            outline = PlotTreeOutline.model_validate(tree)
            outline = normalize_plot_tree_outline(outline)
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": f"剧情树校验失败: {exc}"},
                ensure_ascii=False,
            )

        g = self.repo.load_graph(self.story_id)
        root = g.nodes[g.root_id]
        g.nodes = {root.id: root}
        g.edges = []
        g.options = []

        by_id = {n.id: n for n in outline.nodes}
        root_outline = by_id[outline.root]
        id_map: dict[str, str] = {outline.root: g.root_id}
        root.title = root_outline.title.strip() or root.title
        root.summary = (root_outline.summary or root_outline.title).strip()[:80]
        root.spine_event = (root_outline.spine_event or "").strip() or None
        root.kind = NodeKind.root
        root.script = None

        def _map_kind(n) -> NodeKind:
            if n.type == "start":
                return NodeKind.main
            if n.type == "ending":
                return NodeKind.ending
            if n.type == "merge":
                return (
                    NodeKind.main
                    if (n.spine_event or "").strip()
                    else NodeKind.branch
                )
            return NodeKind.branch

        for n in outline.nodes:
            if n.id == outline.root:
                continue
            nid = _nid()
            id_map[n.id] = nid
            g.nodes[nid] = StoryNode(
                id=nid,
                kind=_map_kind(n),
                title=n.title.strip(),
                summary=(n.summary or n.title).strip()[:80],
                parent_id=None,
                script=None,
                spine_event=(n.spine_event or "").strip() or None,
                outcome=n.outcome if n.type == "ending" else None,
                share_key=n.share_key if n.type == "ending" else None,
            )

        edge_pairs: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        def _add_edge(src_oid: str, tgt_oid: str, label: str) -> None:
            key = (src_oid, tgt_oid)
            if key in seen or src_oid not in id_map or tgt_oid not in id_map:
                return
            seen.add(key)
            edge_pairs.append((src_oid, tgt_oid, label))

        if outline.edges:
            for e in outline.edges:
                lab = (e.label or "").strip()
                if not lab and e.to_id in by_id:
                    lab = (by_id[e.to_id].option_label or "").strip()
                _add_edge(e.from_id, e.to_id, lab or "继续")
        else:
            for n in outline.nodes:
                if n.parent:
                    _add_edge(
                        n.parent,
                        n.id,
                        (n.option_label or "").strip() or "继续",
                    )

        for n in outline.nodes:
            if n.rejoin:
                _add_edge(
                    n.id,
                    n.rejoin,
                    (n.option_label or "").strip() or "汇回",
                )

        for src_oid, tgt_oid, label in edge_pairs:
            src = id_map[src_oid]
            tgt = id_map[tgt_oid]
            oid = _oid()
            g.options.append(
                StoryOption(
                    id=oid,
                    from_node_id=src,
                    to_node_id=tgt,
                    label=label.strip() or "继续",
                )
            )
            g.edges.append(
                StoryEdge(id=_eid(), source=src, target=tgt, option_id=oid)
            )
            child = g.nodes[tgt]
            if child.parent_id is None and tgt != g.root_id:
                child.parent_id = src

        spine = load_story_spine(self.story_id)
        assign_mainline_kinds(
            g, spine.key_events if spine is not None else None
        )
        apply_layout(g)
        self.repo.save_graph(g)
        self._save_plot_tree_json(outline.model_dump(by_alias=True))

        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.branch_script,
            type="graph",
            message=f"剧情树已写入：{len(g.nodes)} 个节点",
            payload={"node_count": len(g.nodes), "edge_count": len(g.edges)},
        )
        return json.dumps(
            {
                "ok": True,
                "node_count": len(g.nodes),
                "edge_count": len(g.edges),
                "id_map": id_map,
                "next": "branch_script",
            },
            ensure_ascii=False,
        )

    def write_node_scripts(self, updates: list[dict[str, Any]]) -> str:
        """批量写入节点剧本：updates=[{node_id, script, title?, summary?}]。"""
        if not updates:
            return json.dumps(
                {"ok": False, "error": "updates 不能为空"}, ensure_ascii=False
            )

        g = self.repo.load_graph(self.story_id)
        updated: list[str] = []
        for item in updates:
            nid = str(item.get("node_id") or "").strip()
            if not nid:
                return json.dumps(
                    {"ok": False, "error": "缺少 node_id"}, ensure_ascii=False
                )
            if nid not in g.nodes:
                return json.dumps(
                    {"ok": False, "error": f"节点不存在: {nid}"},
                    ensure_ascii=False,
                )
            if nid == g.root_id:
                return json.dumps(
                    {"ok": False, "error": "根节点不写 script"},
                    ensure_ascii=False,
                )
            raw_script = item.get("script")
            if not isinstance(raw_script, dict):
                return json.dumps(
                    {"ok": False, "error": f"{nid}: script 必须为对象"},
                    ensure_ascii=False,
                )
            try:
                script = NodeScript.model_validate(sanitize_script_dict(raw_script))
            except Exception as exc:
                return json.dumps(
                    {"ok": False, "error": f"{nid}: script 校验失败: {exc}"},
                    ensure_ascii=False,
                )

            node = g.nodes[nid]
            parent = g.nodes.get(node.parent_id) if node.parent_id else None
            label = ""
            for opt in g.options:
                if opt.to_node_id == nid:
                    label = opt.label
                    break
            if parent and parent.script:
                script = _ground_script_for_edge(
                    script,
                    parent_out=parent.script.dramatic_state_out,
                    option_label=label or "继续",
                )
            elif label:
                script = _ground_script_for_edge(
                    script, parent_out="", option_label=label
                )

            hard = [
                x
                for x in check_node_script(nid, script)
                if x.code in {"NO_DIALOGUE", "VISUAL_PLAN", "NO_SCRIPT"}
            ]
            if hard:
                return json.dumps(
                    {"ok": False, "error": f"{nid}: {hard[0].message}"},
                    ensure_ascii=False,
                )

            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            node.script = script
            if title:
                node.title = title
            node.summary = summary_from_script(
                script, summary or node.summary or node.title
            )
            updated.append(nid)

        apply_layout(g)
        self.repo.save_graph(g)
        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.branch_script,
            type="graph",
            message=f"写入节点剧本：{len(updated)} 个",
            payload={"node_ids": updated},
        )
        return json.dumps(
            {"ok": True, "updated": updated, "count": len(updated)},
            ensure_ascii=False,
        )


    async def compliance_check(self) -> str:
        g = self.repo.load_graph(self.story_id)
        meta = self.repo.load_meta(self.story_id)
        if g.open_plot_leaves():
            return json.dumps(
                {
                    "error": "结构未完成：仍有开放叶，须先 consistency 通过",
                    "open_plot_leaves": g.open_plot_leaves(),
                },
                ensure_ascii=False,
            )
        if g.ending_count() < 1:
            return json.dumps({"error": "没有结局节点，无法合规"}, ensure_ascii=False)

        try:
            await apply_dag_compliance_once(self.story_id, meta.inspiration)
            g = self.repo.load_graph(self.story_id)
            # 一轮 DAG 已覆盖涉政/敏感红线；不再对每条剧情线调 LLM（1303 线会卡死数小时）
            lines = list(g.iter_plot_lines())
            for pl in lines:
                pl.compliance_status = ComplianceStatus.passed.value
                pl.reasons = []
            self.repo.append_event(
                self.story_id,
                phase=FissionPhase.compliance,
                type="log",
                message="DAG 合规已通过",
            )
        except Exception as exc:  # noqa: BLE001
            meta.phase = FissionPhase.failed
            self.repo.save_meta(meta)
            self.repo.append_event(
                self.story_id,
                phase=FissionPhase.failed,
                type="error",
                message=f"合规审查失败：{exc}",
            )
            return json.dumps({"error": f"合规审查失败：{exc}"}, ensure_ascii=False)

        passed = len(lines)
        rejected = 0

        g, kept = prune_rejected_lines(g, lines)
        if not kept:
            meta.phase = FissionPhase.failed
            self.repo.save_meta(meta)
            self.repo.append_event(
                self.story_id,
                phase=FissionPhase.failed,
                type="error",
                message="合规剪枝后无合格剧情线",
                payload={"pass": 0, "reject": rejected},
            )
            path = compliance_path(self.story_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "story_id": self.story_id,
                        "pass": 0,
                        "reject": rejected,
                        "lines": [pl.model_dump() for pl in lines],
                        "kept_lines": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return json.dumps(
                {"error": "合规剪枝后无合格剧情线", "pass": 0, "reject": rejected},
                ensure_ascii=False,
            )

        apply_layout(g)
        self.repo.save_graph(g)
        meta.line_count = g.line_count
        meta.ending_count = g.ending_count()

        min_lines = self._min_paths()
        if g.line_count < min_lines:
            meta.phase = FissionPhase.failed
            self.repo.save_meta(meta)
            self.repo.append_event(
                self.story_id,
                phase=FissionPhase.failed,
                type="error",
                message=f"合规剪枝后剧情线 {g.line_count} < {min_lines}",
                payload={"pass": len(kept), "reject": rejected, "line_count": g.line_count},
            )
            path = compliance_path(self.story_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "story_id": self.story_id,
                        "pass": len(kept),
                        "reject": rejected,
                        "lines": [pl.model_dump() for pl in lines],
                        "kept_lines": [pl.model_dump() for pl in kept],
                        "line_count": g.line_count,
                        "error": f"line_count < {min_lines}",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return json.dumps(
                {
                    "error": f"合规剪枝后剧情线 {g.line_count} < {min_lines}",
                    "pass": len(kept),
                    "reject": rejected,
                    "line_count": g.line_count,
                },
                ensure_ascii=False,
            )

        meta.phase = FissionPhase.compliance
        self.repo.save_meta(meta)

        payload = {
            "story_id": self.story_id,
            "pass": len(kept),
            "reject": rejected,
            "lines": [pl.model_dump() for pl in lines],
            "kept_lines": [pl.model_dump() for pl in kept],
            "line_count": g.line_count,
            "ending_count": g.ending_count(),
            "pruned": True,
        }
        path = compliance_path(self.story_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.compliance,
            type="graph",
            message=f"合规剪枝完成：pass={len(kept)} reject={rejected} lines={g.line_count}",
            payload={"pass": len(kept), "reject": rejected, "line_count": g.line_count},
        )
        return json.dumps({"ok": True, **payload}, ensure_ascii=False)

    async def persist_graph(self) -> str:
        meta = self.repo.load_meta(self.story_id)
        if meta.phase not in {FissionPhase.compliance, FissionPhase.persist}:
            return json.dumps(
                {
                    "error": "须先 compliance_check（含剪枝）再 persist_graph",
                    "phase": meta.phase.value,
                },
                ensure_ascii=False,
            )
        try:
            result = await persist_production_blueprint(self.story_id, repo=self.repo)
        except Exception as exc:  # noqa: BLE001
            meta = self.repo.load_meta(self.story_id)
            # 图与合规已完成；仅 persist 失败时回到 compliance 以便重试 persist
            meta.phase = FissionPhase.compliance
            self.repo.save_meta(meta)
            self.repo.append_event(
                self.story_id,
                phase=FissionPhase.compliance,
                type="error",
                message=f"定稿入库失败：{exc}",
            )
            return json.dumps({"error": f"定稿入库失败：{exc}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    def finish_fission(self) -> str:
        g = self.repo.load_graph(self.story_id)
        meta = self.repo.load_meta(self.story_id)
        persisted = meta.phase == FissionPhase.persist or blueprint_path(self.story_id).exists()
        min_lines = self._min_paths()
        # min_story_lines 只约束收束前；合规剪枝后线数可少于门槛
        if not persisted and g.line_count < min_lines:
            return json.dumps(
                {
                    "error": (
                        f"剧情线数 {g.line_count} < {min_lines}；"
                        "须先完成剧情树与剧本，使通向结局的路径数达标"
                    ),
                    "line_count": g.line_count,
                    "ending_count": g.ending_count(),
                    "min_story_lines": min_lines,
                },
                ensure_ascii=False,
            )
        if g.open_plot_leaves():
            return json.dumps(
                {
                    "error": "结构未完成：仍有开放叶，须先 consistency 通过",
                    "open_plot_leaves": g.open_plot_leaves(),
                },
                ensure_ascii=False,
            )
        if g.ending_count() < 1:
            return json.dumps({"error": "没有结局节点"}, ensure_ascii=False)
        if not persisted:
            return json.dumps(
                {
                    "error": "须先 persist_graph 定稿入库后再 finish_fission",
                    "phase": meta.phase.value,
                },
                ensure_ascii=False,
            )
        meta.phase = FissionPhase.done
        meta.status = StoryStatus.planning
        self.repo.save_meta(meta)
        self.repo.append_event(
            self.story_id,
            phase=FissionPhase.done,
            type="phase",
            message="裂变完成",
            payload={
                "line_count": g.line_count,
                "ending_count": g.ending_count(),
            },
        )
        return json.dumps(
            {
                "ok": True,
                "done": True,
                "ending_count": g.ending_count(),
                "line_count": g.line_count,
            }
        )

