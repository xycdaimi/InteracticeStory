from __future__ import annotations

from backend.app.models.story_graph import StoryGraph


def story_graph_to_comfy_workflow(graph: StoryGraph) -> dict:
    """派生视图：把故事图映射为 Comfy-like workflow JSON（权威数据仍是 graph.json）。"""
    id_map = {nid: i + 1 for i, nid in enumerate(graph.nodes.keys())}
    nodes = []
    for nid, n in graph.nodes.items():
        nodes.append(
            {
                "id": id_map[nid],
                "type": f"StoryDisplay/{n.kind.value}",
                "pos": [n.canvas_x, n.canvas_y],
                "widgets_values": [n.title, n.summary],
            }
        )
    links = []
    for i, e in enumerate(graph.edges):
        links.append(
            [
                i + 1,
                id_map[e.source],
                0,
                id_map[e.target],
                0,
                "STORY",
            ]
        )
    return {
        "last_node_id": len(nodes),
        "last_link_id": len(links),
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {"story_id": graph.story_id},
    }
