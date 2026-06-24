# PLAN — Push Dashboards to Power BI

Branch `hybrid-brain`. Goal: build a dashboard in CityAgent Analytics →
push it to Microsoft Power BI. New flag-gated subsystem `HYBRID_POWERBI_PUSH`,
default OFF. Reuse Azure OAuth; touch no core (HARD RULE 3/4). Captures 2026-06-19
design.

## The catch (set expectations)
Power BI dashboards are NOT a file you POST. PBI model = **datasets (data model)
+ reports (proprietary visuals) + pinned tiles**. Our dashboards = ECharts/React
artifacts (HTML/JS). You can't ship our ECharts and have it become a native PBI
visual 1:1. Possibilities split by **fidelity vs effort**: push the *data* (easy)
vs reconstruct the *visuals* (hard).

## Reuse (already in repo)
- **Azure AD OAuth** — have it for SharePoint/OneDrive (`graph_drive_client`, same
  Azure app pattern). Add Power BI scope `https://analysis.windows.net/powerbi/api/.default`.
- **`powerbi_client.py`** — read connector exists (EE-gated); push is a separate
  write path, auth/SDK patterns carry over.
- **Agent output** — the SQL + result set + chart spec per dashboard.
- **Knowledge Layer metrics** (`metric_definition`: name→sql_calc) → map to PBI **DAX measures**.

## Three tiers
**Tier 1 — push the DATA (easiest, highest ROI) — recommended MVP**
- 1a Power BI connects to our data: `analytics.*` views in managed Postgres → PBI
  Postgres DirectQuery/Import. We expose; user builds visuals in PBI. Lowest effort,
  native PBI charts.
- 1b Push-dataset REST API: `POST /datasets` + `POST /datasets/{id}/rows` → create a
  dataset from our query schema, push rows to a chosen workspace, optional scheduled
  refresh. "Push to Power BI" button per dashboard. **Pro-tier, no Premium needed.**

**Tier 2 — generate a real PBI REPORT (medium-high) — the "build here → push" dream**
- Use **PBIP / PBIR** format (2024, text-based: `.tmdl` model + `report.json` visuals —
  documented, unlike legacy binary `.pbix`).
- Map each artifact chart → PBIR visual JSON + TMDL measures (from Knowledge Layer
  metrics) → zip → `POST /imports` to publish. Native, editable PBI report mirroring ours.
- Effort = chart-type mapping (bar/line/pie/table/KPI) + DAX generation. Doable, not trivial.

**Tier 3 — XMLA / Fabric semantic-model push (enterprise only)**
- Deploy a tabular model to a Premium/Fabric workspace via XMLA write (TOM/Tabular Editor).
- Only if they have **Premium/Fabric capacity.**

## Constraints
| | requirement |
|---|---|
| Auth | Azure AD **service principal** + tenant setting "allow service principals to use Power BI APIs" (admin toggle) |
| Target | a Power BI **workspace** (group) to push into |
| License | push datasets / import = **Pro**; XMLA/large = **Premium/Fabric** |
| Fidelity | Tier 1 = data only (rebuild visuals in PBI); Tier 2 = visuals reconstructed; no pixel-match guarantee |

## Phases (MVP = Tier 1b)
- **P1** Azure app + Power BI scope; `powerbi_push_client.py` (service-principal token,
  list workspaces). Config in `integration_config` row (reuse pattern), secret in env.
- **P2** Push-dataset: from a dashboard's query result → create dataset + push rows to
  a chosen workspace; return PBI link. Flag `HYBRID_POWERBI_PUSH`. FE: "Push to Power BI"
  action (pick workspace).
- **P3** Optional scheduled refresh / re-push on data change (leader-gated daemon).
- **P4 (Tier 2)** PBIR report generation: chart→visual mapping + TMDL measures from
  metric definitions → `POST /imports`. Premium follow-up.
- **P5 (Tier 3, optional)** XMLA/Fabric semantic-model deploy (Premium only).

## Recommendation
Ship **Tier 1b** first (reuses auth + SQL, Pro-tier, fast). Then **Tier 2** (PBIR)
as the premium "real report" follow-up using our metrics as DAX. New flag-gated
subsystem, reuses Azure OAuth, no core touch.
