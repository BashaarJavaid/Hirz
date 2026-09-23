# Item 17 retained inputs and outputs

This is a **partial experiment**, not a completed year-long performance claim.
`results.json` records requested 2025-09-01–2026-09-01 Chicago coverage, all six
rate/household combinations and three wear settings, eligible days, failures,
and final state. No strategy is restarted after it cannot continue within hard
constraints. `readme-table.md` is generated from those results and includes the
EV-only result despite incomplete coverage. Annualized values extrapolate eligible
days and are subject to missing-data and stopped-run bias.

- `raw/`: gzip-compressed original public responses and a URL, retrieval-time,
  uncompressed SHA-256 manifest. Day-ahead responses are evidence, not forecasts.
- `workload.json`: expanded physical parameters and approved workload configuration.
- `results.json`, `daily.csv`, `readme-table.md`: generated historical study outputs.
- `run.log`, `reproduction.log`: study status and independent offline reproduction.
- `demo-evening*.json`, `parents-scam-check.json`: separate read-only scenario reports.
- `smoke-planner.json`: measured latency gates; `live-weather-smoke.json`: live
  adapter evidence explicitly excluded from historical figures.

Procedures: [development documentation](../../docs/development.md#item-17-planner-and-backtest).
Full evidence and failed gates: [verification log](../../docs/verification-log.md#item-17--partial-2026-09-21).
