from __future__ import annotations

from typing import Any

from backend.app.models.story_graph import NodeScript, StoryGraph, validate_visual_plan
from backend.app.services.cast_extract import CharacterDraft
from backend.app.services.script_sanitize import sanitize_script_dict

# 剧本常见英文 slug → 中文角色名关键词（用于对齐 cast_extract 产出）
_SLUG_NAME_HINTS: dict[str, list[str]] = {
    "cat": ["猫", "会说话的猫"],
    "owner": ["主人", "铲屎官"],
    "family_member": ["家人", "亲属"],
    "family": ["家人"],
    "visitor": ["访客", "客人", "来访者"],
    "reporter": ["记者", "采访"],
    "protagonist": ["主角"],
    "主角": ["主角"],
}


def collect_script_character_tokens(graph: StoryGraph) -> set[str]:
    tokens: set[str] = set()
    for node in graph.nodes.values():
        if node.script is None:
            continue
        s = node.script
        vp = s.visual_plan
        for ref in vp.character_refs:
            if ref.character_id:
                tokens.add(ref.character_id)
        for cid in vp.first_frame.covers_character_ids:
            if cid:
                tokens.add(cid)
        for cid in vp.hidden_or_pov_only_ids:
            if cid:
                tokens.add(cid)
        for beat in s.beats:
            if beat.pov:
                tokens.add(beat.pov)
            for dlg in beat.dialogue:
                if dlg.speaker:
                    tokens.add(dlg.speaker)
    return tokens


def collect_character_ref_tokens(graph: StoryGraph) -> set[str]:
    refs: set[str] = set()
    for node in graph.nodes.values():
        if node.script is None:
            continue
        for ref in node.script.visual_plan.character_refs:
            if ref.character_id:
                refs.add(ref.character_id)
    return refs


def _humanize_slug(token: str) -> str:
    return token.replace("_", " ").strip()


def match_token_to_character_id(
    token: str,
    characters: list[CharacterDraft],
    *,
    protagonist_id: str | None = None,
) -> str | None:
    tid = (token or "").strip()
    if not tid:
        return None

    known = {c.character_id for c in characters}
    if tid in known:
        return tid

    lower = tid.lower()
    if lower in ("cat", "protagonist", "主角") and protagonist_id:
        return protagonist_id

    for c in characters:
        if c.name == tid or c.name.lower() == lower:
            return c.character_id

    hints = list(_SLUG_NAME_HINTS.get(lower, []))
    underscored = lower.replace(" ", "_")
    if underscored != lower:
        hints.extend(_SLUG_NAME_HINTS.get(underscored, []))

    for c in characters:
        for hint in hints:
            if hint in c.name or c.name in hint:
                return c.character_id

    human = _humanize_slug(lower)
    for c in characters:
        name_lower = c.name.lower()
        if human and (human in name_lower or name_lower in human):
            return c.character_id
        if tid in c.name or c.name in tid:
            return c.character_id

    return None


def build_character_slug_map(
    tokens: set[str],
    characters: list[CharacterDraft],
    *,
    protagonist_id: str | None = None,
) -> dict[str, str]:
    slug_map: dict[str, str] = {}
    known = {c.character_id for c in characters}
    for token in tokens:
        if not token:
            continue
        if token in known:
            slug_map[token] = token
            continue
        if token in slug_map:
            continue
        matched = match_token_to_character_id(
            token, characters, protagonist_id=protagonist_id
        )
        if matched:
            slug_map[token] = matched
    return slug_map


def supplement_characters_for_unmapped_refs(
    graph: StoryGraph,
    characters: list[CharacterDraft],
    slug_map: dict[str, str],
) -> tuple[list[CharacterDraft], dict[str, str]]:
    """为 character_refs 中仍无法映射的 slug 补角色卡，避免生产缺定妆图。"""
    chars = list(characters)
    known = {c.character_id for c in chars}
    slug_map = dict(slug_map)

    for token in sorted(collect_character_ref_tokens(graph)):
        if token in known:
            continue
        canonical = slug_map.get(token)
        if canonical and canonical in known:
            continue

        idx = len(chars)
        hints = _SLUG_NAME_HINTS.get(token.lower(), [])
        name = hints[0] if hints else _humanize_slug(token) or token
        cid = f"c_{idx:04d}"
        chars.append(
            CharacterDraft(
                character_id=cid,
                name=name,
                appearance_prompt=(
                    f"角色「{name}」：根据剧情出场的配角，面部清晰、"
                    "服装符合故事时代与生活场景，神态自然"
                ),
                traits=[],
            )
        )
        slug_map[token] = cid
        known.add(cid)

    return chars, slug_map


def remap_script_dict_ids(script: dict[str, Any], slug_map: dict[str, str]) -> dict[str, Any]:
    data = dict(script)

    def map_id(raw: Any) -> Any:
        if not isinstance(raw, str):
            return raw
        return slug_map.get(raw, raw)

    vp = dict(data.get("visual_plan") or {})
    first = dict(vp.get("first_frame") or {})
    first["covers_character_ids"] = [
        map_id(x) for x in first.get("covers_character_ids") or []
    ]
    vp["first_frame"] = first
    vp["character_refs"] = [
        {**ref, "character_id": map_id(ref.get("character_id"))}
        for ref in vp.get("character_refs") or []
        if isinstance(ref, dict)
    ]
    vp["hidden_or_pov_only_ids"] = [
        map_id(x) for x in vp.get("hidden_or_pov_only_ids") or []
    ]
    data["visual_plan"] = vp

    beats: list[Any] = []
    for beat in data.get("beats") or []:
        if not isinstance(beat, dict):
            beats.append(beat)
            continue
        row = dict(beat)
        if row.get("pov"):
            row["pov"] = map_id(row["pov"])
        beats.append(row)
    data["beats"] = beats
    return data


def normalize_graph_character_ids(
    graph: StoryGraph,
    slug_map: dict[str, str],
) -> None:
    if not slug_map:
        return
    for node in graph.nodes.values():
        if node.script is None:
            continue
        raw = remap_script_dict_ids(node.script.model_dump(), slug_map)
        node.script = NodeScript.model_validate(sanitize_script_dict(raw))
        validate_visual_plan(node.script)


def align_cast_with_scripts(
    graph: StoryGraph,
    characters: list[CharacterDraft],
    *,
    protagonist_id: str | None,
) -> tuple[list[CharacterDraft], dict[str, str]]:
    tokens = collect_script_character_tokens(graph)
    slug_map = build_character_slug_map(
        tokens, characters, protagonist_id=protagonist_id
    )
    characters, slug_map = supplement_characters_for_unmapped_refs(
        graph, characters, slug_map
    )
    # 二次映射：补角后可能还能对齐其余 token
    slug_map = {
        **slug_map,
        **build_character_slug_map(
            tokens, characters, protagonist_id=protagonist_id
        ),
    }
    normalize_graph_character_ids(graph, slug_map)
    return characters, slug_map
