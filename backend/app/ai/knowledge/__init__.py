"""CityAgent knowledge-mining helpers (Phase-6 join graph, etc.).

Additive, flag-gated, fail-soft miners that derive structured knowledge
(e.g. table join paths) from observed agent traffic. Nothing here is on the
request hot-path; everything lands in an approval-gated pending state.
"""
