"""
Seed an OpenRouter LLM provider (Phase 1).
==========================================

Creates a single `custom` (OpenAI-compatible) provider pointed at OpenRouter
plus two models: a strong analysis model and a cheap router model.

OpenRouter is the single LLM gateway for CityAgent Analytics. The `custom`
provider routes through Dash's OpenAi client (Chat Completions + native
tool_use) — verified compatible with PlannerV3.

Run against a RUNNING, ONBOARDED instance (an org + admin must already exist):

    export DASH_BASE_URL=http://localhost:3000        # or :8000 for backend direct
    export DASH_ADMIN_EMAIL=admin@example.com
    export DASH_ADMIN_PASSWORD=...
    export OPENROUTER_API_KEY=sk-or-...
    # optional overrides:
    export OR_ANALYSIS_MODEL=anthropic/claude-sonnet-4
    export OR_ROUTER_MODEL=openai/gpt-4o-mini
    python scripts/seed_openrouter.py

Idempotent-ish: a duplicate provider name returns 409 and is reported, not fatal.
"""

import os
import sys

import httpx

BASE = os.environ.get("DASH_BASE_URL", "http://localhost:3000").rstrip("/")
EMAIL = os.environ.get("DASH_ADMIN_EMAIL")
PASSWORD = os.environ.get("DASH_ADMIN_PASSWORD")
KEY = os.environ.get("OPENROUTER_API_KEY")
ANALYSIS = os.environ.get("OR_ANALYSIS_MODEL", "anthropic/claude-sonnet-4")
ROUTER = os.environ.get("OR_ROUTER_MODEL", "openai/gpt-4o-mini")
OR_BASE_URL = "https://openrouter.ai/api/v1"


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if not (EMAIL and PASSWORD):
        die("set DASH_ADMIN_EMAIL and DASH_ADMIN_PASSWORD")
    if not KEY:
        die("set OPENROUTER_API_KEY")

    with httpx.Client(base_url=BASE, timeout=30) as c:
        # 1. login (fastapi-users JWT)
        r = c.post(
            "/api/auth/jwt/login",
            data={"username": EMAIL, "password": PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            die(f"login failed {r.status_code}: {r.text}")
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # 2. resolve org id (first membership)
        r = c.get("/api/users/whoami", headers=auth)
        if r.status_code != 200:
            die(f"whoami failed {r.status_code}: {r.text}")
        me = r.json()
        org_id = None
        for k in ("organization_id", "organizations", "memberships"):
            v = me.get(k)
            if isinstance(v, str):
                org_id = v
                break
            if isinstance(v, list) and v:
                first = v[0]
                org_id = first.get("organization_id") or first.get("id") if isinstance(first, dict) else first
                break
        if not org_id:
            die(f"could not resolve org id from whoami: {me}")
        org_headers = {**auth, "X-Organization-Id": str(org_id)}

        # 3. create the OpenRouter custom provider + models
        payload = {
            "name": "OpenRouter",
            "provider_type": "custom",
            "credentials": {"base_url": OR_BASE_URL, "api_key": KEY, "verify_ssl": True},
            "config": {"max_tokens": 4096, "temperature": 0.2},
            "models": [
                {"name": "Analysis", "model_id": ANALYSIS},
                {"name": "Router", "model_id": ROUTER},
            ],
        }
        r = c.post("/api/llm/providers", json=payload, headers=org_headers)
        if r.status_code == 409:
            print("Provider 'OpenRouter' already exists (409) — skipping create.")
        elif r.status_code not in (200, 201):
            die(f"create provider failed {r.status_code}: {r.text}")
        else:
            print(f"Created OpenRouter provider with models: {ANALYSIS}, {ROUTER}")
        print(f"Done. org={org_id} base_url={OR_BASE_URL}")
        print("Next: set the Analysis model as default in Settings -> Models, then run smoke test 1.4.")


if __name__ == "__main__":
    main()
