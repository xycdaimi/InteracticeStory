from __future__ import annotations

import pytest

from backend.app.agents.mainline_orchestrator import _extract_json_object


def test_extract_json_object_plain() -> None:
    data = _extract_json_object('{"nodes": [{"title": "a"}]}')
    assert "nodes" in data


def test_extract_json_object_fence() -> None:
    data = _extract_json_object('```json\n{"ok": true}\n```')
    assert data["ok"] is True


def test_extract_json_object_raises_on_empty() -> None:
    with pytest.raises(ValueError):
        _extract_json_object("")
