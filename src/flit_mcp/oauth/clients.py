from __future__ import annotations

import json
from dataclasses import dataclass

from config import settings


@dataclass(frozen=True)
class McpOAuthClient:
    client_id: str
    name: str
    redirect_uris: list[str]


def load_static_oauth_clients() -> dict[str, McpOAuthClient]:
    raw = settings.MCP_OAUTH_STATIC_CLIENTS_JSON
    clients: dict[str, McpOAuthClient] = {}
    if raw and str(raw).strip():
        data = json.loads(raw)
        for cid, meta in data.items():
            clients[cid] = McpOAuthClient(
                client_id=cid,
                name=str(meta.get("name", cid)),
                redirect_uris=list(meta.get("redirect_uris", [])),
            )
    # Dev default: allow localhost MCP clients
    if not clients:
        clients["mcp-dev"] = McpOAuthClient(
            client_id="mcp-dev",
            name="MCP Development Client",
            redirect_uris=[
                "http://127.0.0.1:8080/oauth/callback",
                "http://localhost:8080/oauth/callback",
            ],
        )
    return clients


def get_oauth_client(client_id: str) -> McpOAuthClient | None:
    return load_static_oauth_clients().get(client_id)
