# Logo: copied from webapp_build/images/flit_app_logo.svg — see static/README.
from __future__ import annotations

import html
from urllib.parse import urlparse

from flit_mcp.scopes import (
    READ_SCOPE,
    READ_WRITE_SCOPE,
    normalize_requested_scope,
    scope_display_description,
    scope_display_label,
)

FLIT_LOGO_URL = "/mcp/oauth/static/flit_logo.svg"
GOOGLE_LOGO_URL = "/mcp/oauth/static/google_logo.svg"

_STYLES = """
.mcp-oauth-page {
  --mcp-oauth-bg: #f4f6f8;
  --mcp-oauth-card: #ffffff;
  --mcp-oauth-ink: #1a2332;
  --mcp-oauth-muted: #5c6b7a;
  --mcp-oauth-border: #d8dee6;
  --mcp-oauth-accent: #3d6fd9;
  --mcp-oauth-accent-hover: #2f5bb8;
  --mcp-oauth-warn-bg: #fef3c7;
  --mcp-oauth-warn-ink: #92400e;
  --mcp-oauth-error: #b91c1c;
  --mcp-oauth-shadow: 0 4px 24px rgba(26, 35, 50, 0.08);
  min-height: 100vh;
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
  font-family: system-ui, -apple-system, Segoe UI, sans-serif;
  font-size: 1rem;
  line-height: 1.5;
  color: var(--mcp-oauth-ink);
  background: var(--mcp-oauth-bg);
  box-sizing: border-box;
}
.mcp-oauth-page *, .mcp-oauth-page *::before, .mcp-oauth-page *::after {
  box-sizing: border-box;
}
@media (prefers-color-scheme: dark) {
  .mcp-oauth-page {
    --mcp-oauth-bg: #0f1419;
    --mcp-oauth-card: #1a222c;
    --mcp-oauth-ink: #e8edf2;
    --mcp-oauth-muted: #9aa8b5;
    --mcp-oauth-border: #2d3a47;
    --mcp-oauth-accent: #5b8def;
    --mcp-oauth-accent-hover: #7aa3f5;
    --mcp-oauth-warn-bg: #3d3420;
    --mcp-oauth-warn-ink: #f5d78e;
    --mcp-oauth-error: #f87171;
    --mcp-oauth-shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
  }
}
.mcp-oauth-card {
  width: 100%;
  max-width: 26rem;
  background: var(--mcp-oauth-card);
  border: 1px solid var(--mcp-oauth-border);
  border-radius: 0.75rem;
  padding: 1.75rem 1.5rem;
  box-shadow: var(--mcp-oauth-shadow);
}
.mcp-oauth-header {
  text-align: center;
  margin-bottom: 1.25rem;
}
.mcp-oauth-logo {
  display: block;
  margin: 0 auto 0.75rem;
  max-height: 3.25rem;
  width: auto;
}
.mcp-oauth-title {
  margin: 0;
  font-size: 1.375rem;
  font-weight: 700;
  line-height: 1.25;
}
.mcp-oauth-subtitle {
  margin: 0.5rem 0 0;
  font-size: 0.9375rem;
  color: var(--mcp-oauth-muted);
}
.mcp-oauth-client-logo {
  display: block;
  margin: 0.75rem auto 0;
  max-height: 2.5rem;
  width: auto;
}
.mcp-oauth-body p {
  margin: 0 0 0.75rem;
  font-size: 0.9375rem;
}
.mcp-oauth-body p:last-child {
  margin-bottom: 0;
}
.mcp-oauth-warn {
  margin: 0 0 1rem;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  color: var(--mcp-oauth-warn-ink);
  background: var(--mcp-oauth-warn-bg);
}
.mcp-oauth-error {
  margin: 0 0 1rem;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  color: var(--mcp-oauth-error);
  background: color-mix(in srgb, var(--mcp-oauth-error) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--mcp-oauth-error) 35%, transparent);
}
.mcp-oauth-form {
  margin-top: 1.25rem;
}
.mcp-oauth-field {
  margin-bottom: 1rem;
}
.mcp-oauth-field label {
  display: block;
  margin-bottom: 0.35rem;
  font-size: 0.875rem;
  font-weight: 500;
}
.mcp-oauth-field input[type="email"],
.mcp-oauth-field input[type="password"] {
  width: 100%;
  padding: 0.625rem 0.75rem;
  font-size: 1rem;
  color: var(--mcp-oauth-ink);
  background: var(--mcp-oauth-bg);
  border: 1px solid var(--mcp-oauth-border);
  border-radius: 0.5rem;
}
.mcp-oauth-field input:focus {
  outline: 2px solid var(--mcp-oauth-accent);
  outline-offset: 1px;
  border-color: var(--mcp-oauth-accent);
}
.mcp-oauth-btn {
  display: block;
  width: 100%;
  padding: 0.65rem 1rem;
  margin-top: 0.5rem;
  font-size: 0.9375rem;
  font-weight: 600;
  text-align: center;
  text-decoration: none;
  border-radius: 0.5rem;
  border: 1px solid transparent;
  cursor: pointer;
}
.mcp-oauth-btn-primary {
  color: #fff;
  background: var(--mcp-oauth-accent);
}
.mcp-oauth-btn-primary:hover {
  background: var(--mcp-oauth-accent-hover);
}
.mcp-oauth-btn-secondary {
  color: var(--mcp-oauth-ink);
  background: transparent;
  border-color: var(--mcp-oauth-border);
}
.mcp-oauth-btn-secondary:hover {
  background: var(--mcp-oauth-bg);
}
.mcp-oauth-btn-google {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.625rem;
  color: var(--mcp-oauth-ink);
  background: var(--mcp-oauth-card);
  border-color: var(--mcp-oauth-border);
}
.mcp-oauth-btn-google:hover {
  background: var(--mcp-oauth-bg);
  border-color: color-mix(in srgb, var(--mcp-oauth-muted) 40%, var(--mcp-oauth-border));
}
.mcp-oauth-google-icon {
  width: 1.25rem;
  height: 1.25rem;
  flex-shrink: 0;
}
.mcp-oauth-footer {
  margin-top: 1.25rem;
  text-align: center;
  font-size: 0.8125rem;
  color: var(--mcp-oauth-muted);
}
.mcp-oauth-footer a {
  color: var(--mcp-oauth-accent);
}
.mcp-oauth-scopes {
  margin: 1.25rem 0 0;
  padding: 0;
  border: none;
}
.mcp-oauth-scopes legend {
  font-size: 0.875rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  padding: 0;
}
.mcp-oauth-scope-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.mcp-oauth-scope-option {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border: 2px solid var(--mcp-oauth-border);
  border-radius: 0.625rem;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.mcp-oauth-scope-option:hover {
  border-color: color-mix(in srgb, var(--mcp-oauth-accent) 50%, var(--mcp-oauth-border));
}
.mcp-oauth-scope-option:has(input:checked) {
  border-color: var(--mcp-oauth-accent);
  background: color-mix(in srgb, var(--mcp-oauth-accent) 8%, transparent);
}
.mcp-oauth-scope-option input {
  margin-top: 0.2rem;
  flex-shrink: 0;
  accent-color: var(--mcp-oauth-accent);
}
.mcp-oauth-scope-text {
  flex: 1;
  min-width: 0;
}
.mcp-oauth-scope-label {
  display: block;
  font-weight: 600;
  font-size: 0.9375rem;
}
.mcp-oauth-scope-desc {
  display: block;
  margin-top: 0.15rem;
  font-size: 0.8125rem;
  color: var(--mcp-oauth-muted);
}
.mcp-oauth-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 1.25rem;
}
.mcp-oauth-actions .mcp-oauth-btn {
  margin-top: 0;
}
"""


def _redirect_is_localhost(redirect_uri: str) -> bool:
    host = (urlparse(redirect_uri).hostname or "").lower()
    return host in ("127.0.0.1", "localhost")


def _localhost_warning(redirect_uri: str) -> str:
    if not _redirect_is_localhost(redirect_uri):
        return ""
    return (
        '<p class="mcp-oauth-warn"><strong>Note:</strong> This app uses a localhost '
        "redirect. Only continue if you trust the application on your device.</p>"
    )


def _safe_logo_uri(logo_uri: str) -> str | None:
    """Allow https logos and same-origin static paths only (no javascript: etc.)."""
    uri = logo_uri.strip()
    if not uri:
        return None
    lower = uri.lower()
    if lower.startswith("https://"):
        return uri
    if uri.startswith("/") and not uri.startswith("//"):
        return uri
    return None


def _client_logo_block(logo_uri: str | None) -> str:
    if not logo_uri:
        return ""
    allowed = _safe_logo_uri(logo_uri)
    if not allowed:
        return ""
    safe_uri = html.escape(allowed, quote=True)
    return f'<img class="mcp-oauth-client-logo" src="{safe_uri}" alt="" />'


def _flit_header(*, title: str, subtitle: str | None = None) -> str:
    sub = (
        f'<p class="mcp-oauth-subtitle">{html.escape(subtitle)}</p>'
        if subtitle
        else ""
    )
    return f"""<header class="mcp-oauth-header">
  <img class="mcp-oauth-logo" src="{FLIT_LOGO_URL}" alt="Flit" />
  <h1 class="mcp-oauth-title">{html.escape(title)}</h1>
  {sub}
</header>"""


def _scope_options_html(selected_scope: str) -> str:
    selected = normalize_requested_scope(selected_scope)
    options = [
        (READ_SCOPE, scope_display_label(READ_SCOPE), scope_display_description(READ_SCOPE)),
        (
            READ_WRITE_SCOPE,
            scope_display_label(READ_WRITE_SCOPE),
            scope_display_description(READ_WRITE_SCOPE),
        ),
    ]
    items = []
    for value, label, desc in options:
        checked = " checked" if value == selected else ""
        safe_value = html.escape(value, quote=True)
        items.append(
            f"""<label class="mcp-oauth-scope-option">
  <input type="radio" name="scope" value="{safe_value}" required{checked} />
  <span class="mcp-oauth-scope-text">
    <span class="mcp-oauth-scope-label">{html.escape(label)}</span>
    <span class="mcp-oauth-scope-desc">{html.escape(desc)}</span>
  </span>
</label>"""
        )
    return (
        '<fieldset class="mcp-oauth-scopes">'
        "<legend>Access level</legend>"
        '<div class="mcp-oauth-scope-list">'
        + "".join(items)
        + "</div></fieldset>"
    )


def _page_shell(*, title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <link rel="icon" href="/favicon-32x32.png" type="image/png" />
  <style>{_STYLES}</style>
</head>
<body class="mcp-oauth-page">
  <main class="mcp-oauth-card">
    {body}
  </main>
</body>
</html>"""


def login_html(
    *,
    state: str,
    client_name: str,
    redirect_uri: str,
    logo_uri: str | None = None,
    error: str | None = None,
    google_enabled: bool,
    register_url: str,
) -> str:
    err = (
        f'<p class="mcp-oauth-error">{html.escape(error)}</p>' if error else ""
    )
    google_block = ""
    if google_enabled:
        google_url = f"/mcp/oauth/google/start?state={html.escape(state, quote=True)}"
        google_block = (
            f'<a class="mcp-oauth-btn mcp-oauth-btn-google" href="{google_url}">'
            f'<img class="mcp-oauth-google-icon" src="{GOOGLE_LOGO_URL}" alt="" />'
            "<span>Sign in with Google</span></a>"
        )
    safe_state = html.escape(state, quote=True)
    body = f"""{_flit_header(title="Connect to Flit", subtitle="Sign in to continue")}
<div class="mcp-oauth-body">
  <p><strong>{html.escape(client_name)}</strong> wants to connect to your Flit account.</p>
  <p class="mcp-oauth-subtitle" style="margin-top:0">You will choose read-only or read-write access on the next step.</p>
  {_client_logo_block(logo_uri)}
  {_localhost_warning(redirect_uri)}
  {err}
</div>
<form class="mcp-oauth-form" method="post" action="/mcp/oauth/login">
  <input type="hidden" name="state" value="{safe_state}" />
  <div class="mcp-oauth-field">
    <label>Email <input type="email" name="email" required autocomplete="email" /></label>
  </div>
  <div class="mcp-oauth-field">
    <label>Password <input type="password" name="password" required autocomplete="current-password" /></label>
  </div>
  <button class="mcp-oauth-btn mcp-oauth-btn-primary" type="submit">Sign in with email</button>
  {google_block}
</form>
<p class="mcp-oauth-footer">No account? <a href="{html.escape(register_url, quote=True)}">Register on Flit</a></p>"""
    return _page_shell(title="Flit — Sign in", body=body)


def consent_html(
    *,
    state: str,
    client_name: str,
    selected_scope: str,
    redirect_uri: str,
    logo_uri: str | None = None,
) -> str:
    safe_state = html.escape(state, quote=True)
    body = f"""{_flit_header(title="Authorize access", subtitle="Choose what this app can do")}
<div class="mcp-oauth-body">
  <p><strong>{html.escape(client_name)}</strong> is requesting access to your Flit PKM data.</p>
  {_client_logo_block(logo_uri)}
  {_localhost_warning(redirect_uri)}
</div>
<form class="mcp-oauth-form" method="post" action="/mcp/oauth/consent">
  <input type="hidden" name="state" value="{safe_state}" />
  {_scope_options_html(selected_scope)}
  <div class="mcp-oauth-actions">
    <button class="mcp-oauth-btn mcp-oauth-btn-primary" name="action" value="allow" type="submit">Allow</button>
    <button class="mcp-oauth-btn mcp-oauth-btn-secondary" name="action" value="deny" type="submit">Deny</button>
  </div>
</form>"""
    return _page_shell(title="Flit — Authorize", body=body)
