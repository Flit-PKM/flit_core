"""BFS graph traversal over note relationships for MCP query_graph."""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ValidationError
from flit_mcp.note_response import ReturnMode, shape_note_dict
from flit_mcp.serialize import dump_model
from models.note import Note
from models.relationship import RelationshipType
from schemas.note import NoteRead
from service.relationship import list_relationships_for_note

MAX_GRAPH_DEPTH = 3
MAX_GRAPH_NODES = 50

ReturnFormat = Literal["flat", "tree"]


def normalize_return_format(value: str) -> ReturnFormat:
    if value not in ("flat", "tree"):
        raise ValidationError('return_format must be "flat" or "tree"')
    return value  # type: ignore[return-value]


def _parse_relation_type(value: str | None) -> RelationshipType | None:
    if value is None:
        return None
    if value in RelationshipType.__members__:
        return RelationshipType(value)
    return None


def _relationship_type_value(rel_type: RelationshipType | str) -> str:
    if isinstance(rel_type, RelationshipType):
        return rel_type.value
    return str(rel_type)


def _build_tree_node(
    node_id: int,
    nodes: dict[int, dict[str, Any]],
    node_depths: dict[int, int],
    tree_children: dict[int, list[tuple[int, str]]],
) -> dict[str, Any]:
    """Build nested tree from BFS discovery edges (first path only per node)."""
    result = dict(nodes[node_id])
    result["depth"] = node_depths[node_id]
    result["children"] = []
    for child_id, via_type in tree_children.get(node_id, []):
        if child_id not in nodes:
            continue
        child = _build_tree_node(
            child_id, nodes, node_depths, tree_children
        )
        child["via_type"] = via_type
        result["children"].append(child)
    return result


async def query_note_graph(
    db: AsyncSession,
    user_id: int,
    starting_id: int,
    *,
    relation_type: str | None = None,
    max_depth: int = 2,
    limit: int = 50,
    return_mode: ReturnMode = "snippet",
    return_format: ReturnFormat = "flat",
    max_content_chars: int | None = None,
    snippet_chars: int = 200,
) -> dict[str, Any]:
    """Breadth-first traversal from starting_id over owned notes."""
    max_depth = min(max(max_depth, 1), MAX_GRAPH_DEPTH)
    limit = min(max(limit, 1), MAX_GRAPH_NODES)
    rel_filter = _parse_relation_type(relation_type)

    nodes: dict[int, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[int, int, str]] = set()
    node_depths: dict[int, int] = {starting_id: 0}
    tree_children: dict[int, list[tuple[int, str]]] = {}
    depth_reached = 0

    queue: deque[tuple[int, int]] = deque([(starting_id, 0)])
    visited: set[int] = {starting_id}

    while queue and len(nodes) < limit:
        current_id, depth = queue.popleft()
        depth_reached = max(depth_reached, depth)

        result = await db.execute(
            select(Note).where(
                Note.id == current_id,
                Note.user_id == user_id,
                Note.is_deleted == False,
            )
        )
        note = result.scalar_one_or_none()
        if note is None:
            continue

        if current_id not in nodes and len(nodes) < limit:
            note_dict = dump_model(NoteRead.model_validate(note))
            nodes[current_id] = shape_note_dict(
                note_dict,
                return_mode=return_mode,
                max_content_chars=max_content_chars,
                snippet_chars=snippet_chars,
            )

        if depth >= max_depth or len(nodes) >= limit:
            continue

        rels = await list_relationships_for_note(
            db, current_id, skip=0, limit=1000
        )
        peer_ids: set[int] = set()
        peer_rel_types: dict[int, str] = {}
        for rel in rels:
            if rel_filter is not None and _relationship_type_value(rel.type) != rel_filter.value:
                continue
            peer_id = rel.note_b_id if rel.note_a_id == current_id else rel.note_a_id
            peer_ids.add(peer_id)
            rel_type_str = _relationship_type_value(rel.type)
            peer_rel_types[peer_id] = rel_type_str
            edge_key = (current_id, peer_id, rel_type_str)
            rev_key = (peer_id, current_id, rel_type_str)
            if edge_key not in seen_edges and rev_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append(
                    {
                        "from": current_id,
                        "to": peer_id,
                        "type": rel_type_str,
                    }
                )

        if peer_ids:
            owned = await db.execute(
                select(Note.id).where(
                    Note.id.in_(peer_ids),
                    Note.user_id == user_id,
                    Note.is_deleted == False,
                )
            )
            owned_ids = {row[0] for row in owned.all()}
            for peer_id in owned_ids:
                if peer_id not in visited and len(nodes) < limit:
                    visited.add(peer_id)
                    node_depths[peer_id] = depth + 1
                    tree_children.setdefault(current_id, []).append(
                        (peer_id, peer_rel_types[peer_id])
                    )
                    queue.append((peer_id, depth + 1))

    base = {
        "starting_id": starting_id,
        "return_format": return_format,
        "depth_reached": depth_reached,
    }

    if return_format == "tree":
        if starting_id not in nodes:
            return {**base, "root": None}
        return {
            **base,
            "root": _build_tree_node(
                starting_id, nodes, node_depths, tree_children
            ),
        }

    flat_nodes = []
    for node_id, node_data in nodes.items():
        entry = dict(node_data)
        entry["depth"] = node_depths.get(node_id, 0)
        flat_nodes.append(entry)

    return {
        **base,
        "nodes": flat_nodes,
        "edges": edges,
    }
