"""
MCP OAuth helper — file-backed token storage with PKCE support.
Port of 4th-devs/01_05_agent mcp/mcp-auth.ts.

Provides an OAuthTokenStore that persists access/refresh tokens to disk
so MCP servers that require OAuth can reuse tokens across restarts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from infra.logger import logger


@dataclass
class OAuthToken:
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_at: float = 0.0
    scope: str = ""


@dataclass
class PKCEChallenge:
    code_verifier: str = ""
    code_challenge: str = ""
    code_challenge_method: str = "S256"


def generate_pkce() -> PKCEChallenge:
    """Generate a PKCE code verifier/challenge pair (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PKCEChallenge(
        code_verifier=verifier,
        code_challenge=challenge,
        code_challenge_method="S256",
    )


class OAuthTokenStore:
    """Persist OAuth tokens to a JSON file keyed by server name."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path(__file__).resolve().parent / ".data"
        self._dir = Path(storage_dir)
        self._file = self._dir / "mcp_oauth_tokens.json"
        self._cache: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                self._cache = json.loads(self._file.read_text("utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load OAuth tokens: {e}")
                self._cache = {}

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")

    def get(self, server_name: str) -> OAuthToken | None:
        data = self._cache.get(server_name)
        if not data:
            return None
        token = OAuthToken(
            **{k: v for k, v in data.items() if k in OAuthToken.__dataclass_fields__}
        )
        if token.expires_at and token.expires_at < time.time():
            return token  # expired but caller may use refresh_token
        return token

    def is_valid(self, server_name: str) -> bool:
        token = self.get(server_name)
        if not token or not token.access_token:
            return False
        if token.expires_at and token.expires_at < time.time():
            return False
        return True

    def store(self, server_name: str, token: OAuthToken) -> None:
        self._cache[server_name] = asdict(token)
        self._save()
        logger.info(f"OAuth token stored for MCP server '{server_name}'")

    def remove(self, server_name: str) -> None:
        if server_name in self._cache:
            del self._cache[server_name]
            self._save()

    def list_servers(self) -> list[str]:
        return list(self._cache.keys())


def build_authorization_url(
    authorize_endpoint: str,
    client_id: str,
    redirect_uri: str,
    scope: str = "",
    pkce: PKCEChallenge | None = None,
    state: str | None = None,
) -> tuple[str, PKCEChallenge]:
    """Build an OAuth2 authorization URL with optional PKCE."""
    if pkce is None:
        pkce = generate_pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": pkce.code_challenge_method,
    }
    if scope:
        params["scope"] = scope
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{authorize_endpoint}?{qs}", pkce


def exchange_code_for_token(
    token_endpoint: str,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    client_secret: str = "",
) -> OAuthToken:
    """Exchange an authorization code for an access token (sync HTTP)."""
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
            **({"client_secret": client_secret} if client_secret else {}),
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    expires_in = body.get("expires_in", 3600)
    return OAuthToken(
        access_token=body.get("access_token", ""),
        refresh_token=body.get("refresh_token", ""),
        token_type=body.get("token_type", "Bearer"),
        expires_at=time.time() + expires_in,
        scope=body.get("scope", ""),
    )


def refresh_access_token(
    token_endpoint: str,
    refresh_token: str,
    client_id: str,
    client_secret: str = "",
) -> OAuthToken:
    """Use a refresh token to obtain a new access token."""
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            **({"client_secret": client_secret} if client_secret else {}),
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    expires_in = body.get("expires_in", 3600)
    return OAuthToken(
        access_token=body.get("access_token", ""),
        refresh_token=body.get("refresh_token", refresh_token),
        token_type=body.get("token_type", "Bearer"),
        expires_at=time.time() + expires_in,
        scope=body.get("scope", ""),
    )
