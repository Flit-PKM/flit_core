from __future__ import annotations

import logging

from fastapi import FastAPI

from config import settings

logger = logging.getLogger(__name__)

_catalog_registered = False
_mcp_registered = False


def register_mcp_openapi(app: FastAPI) -> None:
    """Mount read-only MCP catalog for OpenAPI when configured."""
    global _catalog_registered
    if _catalog_registered:
        return
    if not (settings.MCP_OPENAPI_INCLUDE or settings.MCP_ENABLED):
        return

    from flit_mcp.catalog import router as catalog_router

    app.include_router(catalog_router)
    _catalog_registered = True
    logger.info("MCP catalog mounted at GET /mcp/catalog")


def register_mcp(app: FastAPI) -> None:
    global _mcp_registered
    register_mcp_openapi(app)
    if _mcp_registered:
        return
    if not settings.MCP_ENABLED:
        logger.info("MCP server disabled (MCP_ENABLED=false)")
        return
    from exceptions import ValidationError
    from service.mcp_oauth import mcp_issuer

    try:
        issuer = mcp_issuer()
    except ValidationError:
        logger.warning(
            "MCP_ENABLED but public base URL unset (set VERIFY_EMAIL_BASE_URL); skipping MCP mount"
        )
        return

    import flit_mcp.resources  # noqa: F401 — register resources
    import flit_mcp.tools  # noqa: F401 — register tools
    from flit_mcp.oauth.routes import router as mcp_oauth_router
    from flit_mcp.oauth.routes import well_known_oauth_router
    from flit_mcp.router_setup import flit_mcp_router
    from routes.mcp_api_keys import router as mcp_api_keys_router

    app.include_router(flit_mcp_router, prefix="/mcp")
    app.include_router(mcp_api_keys_router)
    app.include_router(well_known_oauth_router())
    app.include_router(mcp_oauth_router)
    _mcp_registered = True
    logger.info("MCP server mounted at /mcp (issuer=%s)", issuer)
