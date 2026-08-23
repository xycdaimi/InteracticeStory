from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.story_graph import NodeScript


@dataclass
class RefBinding:
    path: str
    role: str  # first_frame | character
    depicts: str
    character_id: str | None = None


def resolve_ref_bindings(
    script: NodeScript,
    *,
    first_frame_path: str | None,
    character_images: dict[str, str],
    character_names: dict[str, str] | None = None,
    continues_from_prev_shot: bool = False,
) -> list[RefBinding]:
    """按 visual_plan 选最少参考图。"""
    vp = script.visual_plan
    names = character_names or {}
    out: list[RefBinding] = []
    if vp.first_frame.required:
        if first_frame_path:
            out.append(
                RefBinding(
                    path=first_frame_path,
                    role="first_frame",
                    depicts=vp.first_frame.depicts,
                )
            )
        elif not continues_from_prev_shot:
            raise RuntimeError("visual_plan 要求首帧但路径缺失")
    for ref in vp.character_refs:
        path = character_images.get(ref.character_id)
        if not path:
            raise RuntimeError(f"缺定妆图: {ref.character_id}")
        label = names.get(ref.character_id) or ref.character_id
        out.append(
            RefBinding(
                path=path,
                role="character",
                depicts=label,
                character_id=ref.character_id,
            )
        )
    return out


def assemble_prompt_from_script(
    script: NodeScript,
    bindings: list[RefBinding],
    *,
    continues_from_prev_shot: bool = False,
    pov_names: dict[str, str] | None = None,
) -> str:
    """【参考图】绑定段 + 时码正文。"""
    pov_names = pov_names or {}
    lines: list[str] = ["【参考图】"]
    for b in bindings:
        if b.role == "first_frame":
            lines.append(f"- 首帧：{b.depicts}")
        else:
            lines.append(f"- 定妆：{b.depicts}")
    if len(lines) == 1:
        lines.append("- （无额外定妆）")
    lines.append("")

    for idx, beat in enumerate(script.beats):
        head = f"第{beat.t_start:g}~{beat.t_end:g}s："
        if continues_from_prev_shot and idx == 0:
            head += "承接上段末帧，"
        if beat.pov:
            pov_label = pov_names.get(beat.pov) or "视角角色"
            head += f"转到{pov_label}的主观视角，"
        body = f"{beat.shot} {beat.action}".strip()
        for d in beat.dialogue:
            body += f"{d.speaker}：「{d.line}」。"
        lines.append(head + body)
    return "\n".join(lines)
