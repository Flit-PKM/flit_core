"""Unit tests for MCP graph query formatting."""

from flit_mcp.graph import _build_tree_node


def test_build_tree_node_nested_children():
    nodes = {
        1: {"id": 1, "title": "Root"},
        2: {"id": 2, "title": "Child"},
        3: {"id": 3, "title": "Grandchild"},
    }
    node_depths = {1: 0, 2: 1, 3: 2}
    tree_children = {
        1: [(2, "REFERENCES")],
        2: [(3, "RELATED_TO")],
    }
    root = _build_tree_node(1, nodes, node_depths, tree_children)
    assert root["title"] == "Root"
    assert root["depth"] == 0
    assert len(root["children"]) == 1
    child = root["children"][0]
    assert child["via_type"] == "REFERENCES"
    assert child["title"] == "Child"
    assert child["children"][0]["title"] == "Grandchild"
