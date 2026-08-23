from __future__ import annotations

import pytest

from backend.app.models.story_graph import PlotLine
from backend.app.services.compliance import (
    apply_batch_results,
    extract_json_object,
    normalize_status,
)


def test_extract_json_object_plain() -> None:
    data = extract_json_object('{"results":[]}')
    assert data["results"] == []


def test_extract_json_object_fenced() -> None:
    text = """好的，如下：
```json
{"results":[{"line_index":0,"status":"pass","reasons":[]}]}
```
"""
    data = extract_json_object(text)
    assert data["results"][0]["line_index"] == 0


def test_normalize_status() -> None:
    assert normalize_status("PASS") == "pass"
    assert normalize_status("reject") == "reject"
    with pytest.raises(ValueError):
        normalize_status("maybe")


def test_apply_batch_results_ok() -> None:
    lines = [
        PlotLine(line_id="pl_0001", node_path=["n_root", "e"], ending_id="e"),
        PlotLine(line_id="pl_0002", node_path=["n_root", "e2"], ending_id="e2"),
    ]
    apply_batch_results(
        lines,
        {
            "results": [
                {"line_index": 0, "status": "pass", "reasons": []},
                {
                    "line_index": 1,
                    "status": "reject",
                    "reasons": ["剧情拉垮: 空洞"],
                },
            ]
        },
    )
    assert lines[0].compliance_status == "pass"
    assert lines[1].compliance_status == "reject"
    assert lines[1].reasons == ["剧情拉垮: 空洞"]


def test_apply_batch_results_reject_without_reasons() -> None:
    lines = [PlotLine(line_id="pl_0001", node_path=["n_root"], ending_id="n_root")]
    with pytest.raises(ValueError, match="reasons"):
        apply_batch_results(
            lines,
            {"results": [{"line_index": 0, "status": "reject", "reasons": []}]},
        )


def test_apply_batch_results_reindex_by_order() -> None:
    lines = [PlotLine(line_id="pl_0001", node_path=["n_root"], ending_id="n_root")]
    apply_batch_results(
        lines,
        {"results": [{"line_index": 9, "status": "pass", "reasons": []}]},
    )
    assert lines[0].compliance_status == "pass"


def test_apply_batch_results_unknown_index() -> None:
    lines = [
        PlotLine(line_id="pl_0001", node_path=["n_root"], ending_id="n_root"),
        PlotLine(line_id="pl_0002", node_path=["n_root", "e2"], ending_id="e2"),
    ]
    with pytest.raises(ValueError, match="missing line_indices"):
        apply_batch_results(
            lines,
            {"results": [{"line_index": 1, "status": "pass", "reasons": []}]},
        )
