from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agents.fission_tools import FissionTools
from backend.app.config import get_settings
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path, compliance_path
from backend.app.models.enums import (
    ComplianceStatus,
    FissionPhase,
    NodeKind,
)
from backend.app.models.story_graph import (
    PlotLine,
    StoryEdge,
    StoryGraph,
    StoryNode,
    StoryOption,
)
from backend.app.services.cast_extract import CharacterDraft, NodeBinding, SceneDraft
from backend.app.services.persist import persist_production_blueprint
from backend.app.services.prune import prune_rejected_lines
from backend.app.services.story_repository import StoryRepository


@pytest.fixture()
def story_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MIN_STORY_LINES", "2")
    get_settings.cache_clear()
    reset_engine_for_tests()
    yield tmp_path
    get_settings.cache_clear()
    reset_engine_for_tests()


def _tiny_converged_graph(story_id: str) -> StoryGraph:
    return StoryGraph(
        story_id=story_id,
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "a": StoryNode(id="a", kind=NodeKind.main, title="共享", parent_id="n_root"),
            "b": StoryNode(id="b", kind=NodeKind.branch, title="好支", parent_id="a"),
            "c": StoryNode(id="c", kind=NodeKind.branch, title="坏支", parent_id="a"),
            "e_ok": StoryNode(
                id="e_ok",
                kind=NodeKind.ending,
                title="成",
                parent_id="b",
                share_key="ok",
                outcome="completed",
            ),
            "e_bad": StoryNode(
                id="e_bad",
                kind=NodeKind.ending,
                title="败",
                parent_id="c",
                share_key="bad",
                outcome="failed",
            ),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="a", target="b"),
            StoryEdge(id="e3", source="a", target="c"),
            StoryEdge(id="e4", source="b", target="e_ok"),
            StoryEdge(id="e5", source="c", target="e_bad"),
        ],
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="a", label="起"),
            StoryOption(id="o2", from_node_id="a", to_node_id="b", label="好"),
            StoryOption(id="o3", from_node_id="a", to_node_id="c", label="坏"),
            StoryOption(id="o4", from_node_id="b", to_node_id="e_ok", label="收好"),
            StoryOption(id="o5", from_node_id="c", to_node_id="e_bad", label="收坏"),
        ],
    )


@pytest.mark.asyncio
async def test_prune_persist_finish_flow(story_env: Path):
    await init_db()
    repo = StoryRepository()
    sid = await repo.create_story_indexed("桃园测试")
    g = _tiny_converged_graph(sid)
    lines = [
        PlotLine(
            line_id="pl_0001",
            node_path=["n_root", "a", "b", "e_ok"],
            ending_id="e_ok",
            outcome="completed",
            share_key="ok",
            compliance_status=ComplianceStatus.passed.value,
        ),
        PlotLine(
            line_id="pl_0002",
            node_path=["n_root", "a", "c", "e_bad"],
            ending_id="e_bad",
            outcome="failed",
            share_key="bad",
            compliance_status=ComplianceStatus.rejected.value,
            reasons=["剧情拉垮: 空洞"],
        ),
    ]
    g, kept = prune_rejected_lines(g, lines)
    assert len(kept) == 1
    assert "c" not in g.nodes
    repo.save_graph(g)
    meta = repo.load_meta(sid)
    meta.phase = FissionPhase.compliance
    repo.save_meta(meta)
    compliance_path(sid).write_text(
        __import__("json").dumps(
            {
                "story_id": sid,
                "pass": 1,
                "reject": 1,
                "lines": [pl.model_dump() for pl in lines],
                "kept_lines": [pl.model_dump() for pl in kept],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    fake_cast = (
        [CharacterDraft("c_liu", "刘备", "白袍青年", ["仁"])],
        [SceneDraft("s_tao", "桃园", "桃花盛开")],
        [NodeBinding("a", ["c_liu"], "s_tao"), NodeBinding("b", ["c_liu"], "s_tao"), NodeBinding("e_ok", ["c_liu"], "s_tao")],
        "c_liu",
    )
    with patch(
        "backend.app.services.persist.extract_cast_and_bindings",
        new=AsyncMock(return_value=fake_cast),
    ):
        result = await persist_production_blueprint(sid, repo=repo)
    assert result["ok"] is True
    assert blueprint_path(sid).exists()
    bp = __import__("json").loads(blueprint_path(sid).read_text(encoding="utf-8"))
    assert bp["characters"][0]["character_id"] == "c_liu"
    assert bp["plot_lines"][0]["line_id"] == "pl_0001"
    g2 = repo.load_graph(sid)
    assert g2.nodes["a"].character_ids == ["c_liu"]
    assert g2.nodes["a"].scene_id == "s_tao"
    assert repo.load_meta(sid).phase == FissionPhase.persist

    tools = FissionTools(sid, repo=repo)
    fin = tools.finish_fission()
    assert "done" in fin
    assert repo.load_meta(sid).phase == FissionPhase.done
