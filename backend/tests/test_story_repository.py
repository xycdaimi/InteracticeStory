from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import get_settings
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.models.enums import FissionPhase, NodeKind
from backend.app.models.story_graph import StoryEdge, StoryNode
from backend.app.services.story_repository import StoryRepository


@pytest.fixture()
def tmp_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_engine_for_tests()
    yield tmp_path
    get_settings.cache_clear()
    reset_engine_for_tests()


@pytest.mark.asyncio
async def test_create_story_persists_graph_and_events(tmp_data: Path):
    await init_db()
    repo = StoryRepository()
    sid = await repo.create_story_indexed("讲一个桃园三结义的故事")
    assert (tmp_data / "stories" / sid / "graph.json").exists()
    meta = repo.load_meta(sid)
    assert meta.inspiration.startswith("讲一个")
    assert meta.line_count == 1
    graph = repo.load_graph(sid)
    assert graph.root_id == "n_root"
    assert graph.nodes["n_root"].kind == NodeKind.root

    graph.nodes["n1"] = StoryNode(id="n1", kind=NodeKind.main, title="结义", parent_id="n_root")
    graph.nodes["n2a"] = StoryNode(id="n2a", kind=NodeKind.branch, title="A", parent_id="n1")
    graph.nodes["n2b"] = StoryNode(id="n2b", kind=NodeKind.branch, title="B", parent_id="n1")
    graph.edges = [
        StoryEdge(id="e1", source="n_root", target="n1"),
        StoryEdge(id="e2", source="n1", target="n2a"),
        StoryEdge(id="e3", source="n1", target="n2b"),
    ]
    repo.save_graph(graph)
    assert repo.load_graph(sid).line_count == 2
    assert repo.load_meta(sid).line_count == 2

    ev = repo.append_event(
        sid, phase=FissionPhase.expand, type="log", message="裂变中", payload={"line_count": 2}
    )
    assert ev.seq == 1
    events = repo.list_events(sid, since=0)
    assert len(events) == 1
    assert events[0].message == "裂变中"
