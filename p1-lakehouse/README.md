# P1 · Retail Lakehouse

Raw Favorita files → bronze → silver → gold (dbt) on Databricks, a nightly job and serving
snapshot 1.0. Spec: tab "P1 · Lakehouse". Every Databricks task wraps a pure, unit-tested
function, so logic is tested locally first.

    uv run pytest
