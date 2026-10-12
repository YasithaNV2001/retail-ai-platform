# retail-contracts

Shared contracts for the Retail AI Platform: the replay clock, `RAP_*` settings,
table and snapshot schemas, shared config files and synthetic test fixtures.
Every project depends on it by path (`[tool.uv.sources]`, editable).

Change rules: System design §11. Every change bumps the version, adds a line to
`CHANGELOG.md` and is tagged `contracts-vX.Y.Z`.

    uv run pytest
