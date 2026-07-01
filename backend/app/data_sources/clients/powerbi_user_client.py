"""Power BI Semantic Model — user-login (delegated) variant.

Same engine as :class:`PowerBIClient` (REST executeQueries / DAX, semantic-model
discovery, measures-as-schema), but authenticates as a USER via the OAuth2
Resource-Owner-Password (ROPC) grant — Entra email + password — instead of a
service principal (client_credentials).

This mirrors how ``ms_fabric_user`` subclasses ``ms_fabric``: override ONLY the
token acquisition (``connect``); inherit discovery, DAX execution, schema and
prompt formatting untouched.

Auth precedence inside ``connect``:
  1. a pre-supplied delegated ``access_token`` (device-code / external flow) — just
     open the session (this path already exists in the base client);
  2. ROPC: POST grant_type=password with username + password + a public client_id.

ROPC constraints (surfaced as a clear error, never a silent failure):
  - the account must NOT have MFA enabled, and the tenant must permit ROPC /
    legacy auth. If blocked, Azure returns AADSTS50076/50079 (MFA) or
    AADSTS7000218 — ``connect`` raises with the raw AADSTS code so the UI can tell
    the user to switch to device-code or a service principal.

Read-only: the client only ever issues DAX EVALUATE / discovery calls.
"""
from __future__ import annotations

from typing import Optional

import requests

from app.data_sources.clients.powerbi_client import PowerBIClient

# Microsoft Azure PowerShell — a well-known Microsoft FOCI public client that
# permits the ROPC (password) grant. Used only to mint a delegated user token;
# no secret required. Overridable per-connection via ``oauth_client_id``.
_DEFAULT_PUBLIC_CLIENT = "1950a258-227b-4e31-a9cf-717495945fc2"


class PowerBIUserClient(PowerBIClient):
    """Power BI semantic models queried as a signed-in user (ROPC / delegated)."""

    def __init__(
        self,
        tenant_id: str = None,
        username: str = None,
        password: str = None,
        client_id: str = None,
        access_token: str = None,
        refresh_token: str = None,
        **kwargs,
    ):
        # Base client stores tenant_id/client_id/client_secret/access_token. We
        # reuse tenant_id + access_token; carry user creds for the ROPC override.
        super().__init__(
            tenant_id=tenant_id,
            client_id=client_id or _DEFAULT_PUBLIC_CLIENT,
            client_secret=None,
            access_token=access_token,
        )
        self.username = username
        self.password = password
        # device-code sign-in stores a refresh_token instead of a password; used
        # to mint a fresh access token (rotating the refresh token) on connect.
        self.refresh_token = refresh_token
        # public client used for the password grant (separate from base client_id
        # semantics, which for SP is the app registration id)
        self._public_client_id = client_id or _DEFAULT_PUBLIC_CLIENT

    @property
    def description(self) -> str:
        base = "Power BI Semantic Model (user sign-in / DAX executeQueries)."
        try:
            return base + self.system_prompt()
        except Exception:  # noqa: BLE001 — description must never raise
            return base

    def connect(self):
        """Authenticate as the user via ROPC and open the HTTP session.

        Reuses a cached token / delegated access_token if present (base-client
        behaviour). Otherwise performs the password grant.
        """
        # already connected, or a delegated token was provided -> base handles it
        if (self._http and self._access_token) or self._access_token:
            return super().connect()

        # device-code path: exchange a stored refresh_token for a fresh access
        # token (and rotate the refresh token). Preferred over ROPC — MFA-safe.
        if self.refresh_token and self.tenant_id:
            auth_url = self.AUTH_URL.format(tenant_id=self.tenant_id)
            resp = requests.post(
                auth_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._public_client_id,
                    "refresh_token": self.refresh_token,
                    "scope": self.SCOPE + " offline_access",
                },
                timeout=30,
            )
            if resp.status_code >= 300:
                detail = ""
                try:
                    j = resp.json()
                    detail = f"{j.get('error')}: {j.get('error_description', '')[:300]}"
                except Exception:  # noqa: BLE001
                    detail = resp.text[:300]
                raise RuntimeError(
                    f"Power BI refresh-token sign-in failed: {detail} "
                    "(re-run device-code sign-in to get a fresh token.)"
                )
            body = resp.json()
            token = body.get("access_token")
            if not token:
                raise RuntimeError("Power BI refresh-token grant did not return an access token.")
            self._access_token = token
            # rotate the refresh token if Entra issued a new one
            if body.get("refresh_token"):
                self.refresh_token = body["refresh_token"]
            self._http = requests.Session()
            return

        if not (self.username and self.password and self.tenant_id):
            raise RuntimeError(
                "Power BI user login requires tenant_id, username and password "
                "(or a delegated access_token)."
            )

        auth_url = self.AUTH_URL.format(tenant_id=self.tenant_id)
        payload = {
            "grant_type": "password",
            "client_id": self._public_client_id,
            "username": self.username,
            "password": self.password,
            "scope": self.SCOPE,
        }
        resp = requests.post(auth_url, data=payload, timeout=30)
        if resp.status_code >= 300:
            # surface the raw AADSTS code so the caller can branch (MFA -> device
            # code, ROPC blocked -> service principal)
            detail = ""
            try:
                j = resp.json()
                detail = f"{j.get('error')}: {j.get('error_description', '')[:300]}"
            except Exception:  # noqa: BLE001
                detail = resp.text[:300]
            hint = ""
            if "AADSTS50076" in detail or "AADSTS50079" in detail:
                hint = " (MFA is required on this account — use device-code or a service principal.)"
            elif "AADSTS7000218" in detail or "AADSTS65001" in detail:
                hint = " (Tenant blocks ROPC / consent missing — use a service principal.)"
            raise RuntimeError(f"Power BI user authentication failed: {detail}{hint}")

        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError("Power BI user authentication did not return an access token.")

        self._access_token = token
        self._http = requests.Session()
