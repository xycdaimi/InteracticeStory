"""兼容旧 import；逻辑已迁至 mainline_graph.py（LangGraph）。"""

from backend.app.graphs.mainline_graph import (  # noqa: F401
    MainlineOutlineNode,
    MainlinePlan,
    _extract_json_object,
    run_mainline_graph as orchestrate_mainline,
)
