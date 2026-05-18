from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from flit_mcp.scopes import parse_scopes, scopes_allow_write


McpAuthMethod = Literal["mcp_oauth", "mcp_api_key", "connected_app_oauth"]


@dataclass(frozen=True)
class McpAuthContext:
    user_id: int
    scopes_raw: str
    auth_method: McpAuthMethod

    @property
    def scopes(self) -> set[str]:
        return parse_scopes(self.scopes_raw)

    def allows_write(self) -> bool:
        return scopes_allow_write(self.scopes)

    def to_claims_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "scopes": self.scopes_raw,
            "auth_method": self.auth_method,
        }
