# reference/ — read-only blueprints

Source projects we port *patterns* from. **Not run, not imported** by CityAgent Analytics.

- `dash/` — agno-agi/dash. Blueprint for: dual-schema (public RO / agent-owned),
  Engineer↔Analyst split, DB-level read-only enforcement, learning loop.
  We reimplement these natively in `backend/app` (no Agno dependency).

Safe to delete once all patterns are ported (see docs/ARCHITECTURE.html phase 10).
