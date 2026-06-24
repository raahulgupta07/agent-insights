# PLAN — Enterprise Connector Gating (un-badge / un-gate)

Branch `hybrid-brain`. Why some connectors (SharePoint, OneDrive, Tableau, …)
show an "enterprise" badge, and how to change it. Captures 2026-06-19 findings.

## Why they show "enterprise"
Upstream bagofwords **open-core monetization** (inherited by the fork): free
*community* tier + paid *team/enterprise* tier unlocked by `DASH_LICENSE_KEY`
(RS256 JWT verified in `app/ee/license.py`). MS Graph + BI connectors positioned
as paid-tier.

## TWO independent mechanisms (the key insight)
1. **Display badge** — `requires_license="enterprise"` on the registry entry
   (`app/schemas/data_source_registry.py`). FE reads the field:
   `isLocked = ds.requires_license==='enterprise' && !isLicensed`
   (`DataSourceGrid.vue:108`, `AddConnectionModal.vue:245`). **API-driven** — change
   the backend field, FE re-renders, no FE rebuild.
   Badge on 13 types: tableau, powerbi, powerbi_report_server, qvd, qlik_sense,
   sharepoint, onedrive, google_drive, sybase, timbr, timbr_a2a, sisense, oracle_bi.
2. **Actual enforcement** — `ENTERPRISE_DATASOURCES` in `app/ee/license.py:36`:
   ```python
   ENTERPRISE_DATASOURCES = ["powerbi", "qvd", "sybase", "tableau"]
   ```
   `is_datasource_allowed(ds_type)` blocks ONLY these 4 without a license; anything
   else returns True (allowed).

## Mismatch → SharePoint/OneDrive are badge-only
| connector | badge | actually blocked? |
|---|---|---|
| sharepoint, onedrive, google_drive | yes | **no** — usable without license |
| powerbi_report_server, qlik_sense, timbr(+a2a), sisense, oracle_bi | yes | **no** |
| **powerbi, qvd, sybase, tableau** | yes | **yes — license required** |

All connector client code is already in the image (`graph_drive_client`,
`powerbi_client`, `qvd_client`, `sybase_client`, `tableau_client`). Nothing to
build to *get* them.

## Options (all backend-only → hot-cp + restart, NO full rebuild)
- **Connect SharePoint/OneDrive now** — already allowed; just add the connection. No change.
- **Drop the badge** — set `requires_license=None` on chosen registry entries
  (`data_source_registry.py`) → `docker cp` + `py_compile` + `docker restart ca-app`.
  FE renders no badge (field is null). No FE rebuild.
- **Unlock the paid 4 — proper way** — set `DASH_LICENSE_KEY` (runtime config) → restart only.
- **Unlock the paid 4 — code way** — remove from `ENTERPRISE_DATASOURCES` (`license.py`)
  → hot-cp + restart.

## Hot-cp recipe
```
docker cp backend/app/schemas/data_source_registry.py ca-app:/app/backend/app/schemas/data_source_registry.py
docker exec ca-app /opt/venv/bin/python -m py_compile app/schemas/data_source_registry.py
docker restart ca-app
```

## ⚠️ Legal
`app/ee/` is Dash's **enterprise edition** code, typically a commercial/non-OSS
license separate from the MIT/Apache core. Bypassing `is_datasource_allowed` or
stripping EE gating for the **paid 4** may violate bagofwords' license terms.
Cosmetic badge removal on connectors you legitimately operate = lower risk.
**User decides; this plan documents, does not decide.**

## Suggested action (low-risk default)
Drop the `requires_license` badge from the file connectors you operate
(sharepoint, onedrive, google_drive) — backend hot-cp, no rebuild, no enforcement
change. Leave the paid-4 enforcement as-is unless a license is obtained.
