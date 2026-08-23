from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.ai.geekai_client import GeekAIClient
from backend.app.config import get_settings
from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryGraph
from backend.app.services.compliance import extract_json_object

SYSTEM = """你是互动故事制片助理。只输出 JSON，不要 markdown。
根据灵感与节点摘要，抽出全局去重的人物卡、场景卡，并为每个叙事节点绑定出场人物与场景。

## 主角（玩家扮演）
- 必须指定一名 `protagonist_index`（characters 数组下标），即玩家代入的主角。
- 主角应出现在绝大多数叙事节点中；bindings 优先包含主角。

人物可空（纯景）；场景尽量给到每个叙事节点。

## appearance_prompt（人物定妆照，只写「这个人长什么样」）
只写图像模型画单人立像/半身像所需信息：
- 年龄体感、性别、体型、脸型五官、发型须发、肤色
- 服装款式、颜色、材质、配饰（盔甲等）
- 神态气质：用静态表情/目光/站姿概括精神状态（如沉稳、凌厉、朴实），不要写剧情

禁止写入 appearance_prompt：
- 正在发生的事、剧情动作（扶老携幼、逃难、交战等）
- 背景故事、遭遇、社会群体意象（流离失所、家破人亡等）
- 场景环境、天气、他人互动（这些属于 scene 的 visual_prompt 或分镜）
性格与剧情差异放进 traits，不要塞进外观描述。

## visual_prompt（场景空镜/环境，只写「这个地方长什么样」）
写环境、建筑、光线、色调、氛围道具；可含时代质感，但不要写成剧情梗概。

重要：不要输出任何 node_id / character_id / scene_id。编号由系统根据数组下标生成。
用户消息里的节点以 [0]、[1]… 编号，bindings 用 node_index 引用。

## 输出 JSON 结构（字段名必须一致；值由当前灵感与节点生成，勿照抄占位符）

{
  "protagonist_index": <characters 数组下标，整数>,
  "characters": [
    {
      "name": "<人物名>",
      "appearance_prompt": "<定妆外貌：年龄体感、五官发型、服装配饰、静态神态；不写剧情动作>",
      "traits": ["<性格标签>"]
    }
  ],
  "scenes": [
    {
      "name": "<场景名>",
      "visual_prompt": "<环境空镜：建筑、光线、色调、氛围道具；不写剧情事件>"
    }
  ],
  "bindings": [
    {
      "node_index": <节点下标，整数>,
      "character_indices": [<characters 下标>],
      "scene_index": <scenes 下标或 null>
    }
  ]
}
"""


@dataclass
class CharacterDraft:
    character_id: str
    name: str
    appearance_prompt: str
    traits: list[str] = field(default_factory=list)


@dataclass
class SceneDraft:
    scene_id: str
    name: str
    visual_prompt: str


@dataclass
class NodeBinding:
    node_id: str
    character_ids: list[str]
    scene_id: str | None


def _truncate(text: str, limit: int = 180) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def narrative_node_ids(graph: StoryGraph) -> list[str]:
    """非 root 节点，稳定排序；下标即 LLM 可见的 node_index。"""
    return sorted(
        nid
        for nid, node in graph.nodes.items()
        if node.kind != NodeKind.root
    )


def build_cast_user(inspiration: str, graph: StoryGraph) -> str:
    lines = [
        f"灵感：{inspiration}",
        "叙事节点（bindings 使用 node_index，即方括号内数字）：",
    ]
    for i, nid in enumerate(narrative_node_ids(graph)):
        node = graph.nodes[nid]
        lines.append(
            f"[{i}] [{node.kind.value}] {node.title}: {_truncate(node.summary)}"
        )
    lines.append(
        "请输出人物、场景与 bindings JSON（勿输出任何 id 字段）。"
        "人物 appearance_prompt 仅写外貌穿着与静态神态，勿写剧情动作或苦难意象。"
    )
    return "\n".join(lines)


def parse_cast_payload(
    payload: dict[str, Any],
    graph: StoryGraph,
) -> tuple[list[CharacterDraft], list[SceneDraft], list[NodeBinding], str | None]:
    chars_raw = payload.get("characters") or []
    scenes_raw = payload.get("scenes") or []
    binds_raw = payload.get("bindings") or []
    if not isinstance(chars_raw, list) or not isinstance(scenes_raw, list):
        raise ValueError("characters/scenes must be lists")
    if not isinstance(binds_raw, list):
        raise ValueError("bindings must be a list")

    characters: list[CharacterDraft] = []
    for i, item in enumerate(chars_raw):
        if not isinstance(item, dict):
            raise ValueError("character item must be object")
        name = str(item.get("name") or "").strip()
        appearance = str(item.get("appearance_prompt") or "").strip()
        if not name or not appearance:
            raise ValueError("character requires name/appearance_prompt")
        traits = item.get("traits") or []
        if not isinstance(traits, list):
            raise ValueError("traits must be list")
        characters.append(
            CharacterDraft(
                character_id=f"c_{i:04d}",
                name=name,
                appearance_prompt=appearance,
                traits=[str(t) for t in traits],
            )
        )

    scenes: list[SceneDraft] = []
    for i, item in enumerate(scenes_raw):
        if not isinstance(item, dict):
            raise ValueError("scene item must be object")
        name = str(item.get("name") or "").strip()
        visual = str(item.get("visual_prompt") or "").strip()
        if not name or not visual:
            raise ValueError("scene requires name/visual_prompt")
        scenes.append(
            SceneDraft(scene_id=f"s_{i:04d}", name=name, visual_prompt=visual)
        )

    node_ids = narrative_node_ids(graph)
    bindings: list[NodeBinding] = []
    seen_nodes: set[str] = set()

    for item in binds_raw:
        if not isinstance(item, dict):
            continue
        raw_idx = item.get("node_index")
        if not isinstance(raw_idx, int) or raw_idx < 0 or raw_idx >= len(node_ids):
            continue
        nid = node_ids[raw_idx]
        if nid in seen_nodes:
            continue

        char_indices = item.get("character_indices") or []
        if not isinstance(char_indices, list):
            char_indices = []
        cid_list = [
            f"c_{int(j):04d}"
            for j in char_indices
            if isinstance(j, int) and 0 <= j < len(characters)
        ]

        scene_id: str | None = None
        raw_scene = item.get("scene_index")
        if isinstance(raw_scene, int) and 0 <= raw_scene < len(scenes):
            scene_id = f"s_{raw_scene:04d}"

        bindings.append(
            NodeBinding(node_id=nid, character_ids=cid_list, scene_id=scene_id)
        )
        seen_nodes.add(nid)

    for nid in node_ids:
        if nid not in seen_nodes:
            bindings.append(NodeBinding(node_id=nid, character_ids=[], scene_id=None))

    protagonist_id: str | None = None
    raw_protagonist = payload.get("protagonist_index")
    if isinstance(raw_protagonist, int) and 0 <= raw_protagonist < len(characters):
        protagonist_id = characters[raw_protagonist].character_id
    elif characters:
        protagonist_id = characters[0].character_id

    return characters, scenes, bindings, protagonist_id


async def extract_cast_and_bindings(
    inspiration: str,
    graph: StoryGraph,
    geekai: GeekAIClient,
) -> tuple[list[CharacterDraft], list[SceneDraft], list[NodeBinding], str | None]:
    settings = get_settings()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_cast_user(inspiration, graph)},
    ]
    last_err: Exception | None = None
    for _ in range(2):
        try:
            data = await geekai.chat(
                messages,
                model=settings.chat_model,
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
            return parse_cast_payload(payload, graph)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"cast extract failed: {last_err}") from last_err
