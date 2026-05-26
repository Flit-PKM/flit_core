from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def dump_model(model: BaseModel) -> dict[str, Any]:
    """Serialize a Pydantic model for MCP JSON-RPC (ISO datetimes, enum values)."""
    return model.model_dump(mode="json")


def dump_models(models: list[BaseModel]) -> list[dict[str, Any]]:
    return [dump_model(m) for m in models]
