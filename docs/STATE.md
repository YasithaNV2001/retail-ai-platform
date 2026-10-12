# STATE — Retail AI Platform
Updated: 2026-10-12 · Current project: P1 · Next step: P1 step 1.1

## Done
- Part A: WSL2 Ubuntu 24.04 (10 GB cap, 8 GB swap), Docker Desktop + WSL integration, GPU in containers (GTX 1650 4 GB, driver 610.88, CUDA 13.3)
- Part B: tools installed (see Versions)
- Part C: accounts and keys; 13 GitHub secrets, 5 repo variables; RAP_SCHEMA_PREFIX left undefined
- Part D: monorepo skeleton

## Environment facts (names and IDs only, never secrets)
GitHub: YasithaNV2001 · repos retail-ai-platform (public), rap-data (private)
Hugging Face user: YasithaNV
Databricks Free Edition: dbc-19319377-e58c.cloud.databricks.com · login nvypriyashan@gmail.com
Neon: rap-features, rap-copilot (made through Vercel's Neon integration) · aws ap-southeast-1 (Singapore)
Qdrant cluster: rap-docs · Langfuse: EU cloud, project retail-ai-platform
Render region to use: Singapore
Catalogs: rap_dev, rap_prod (confirmed by P-01) · RAP_SCHEMA_PREFIX: ""
SQL warehouse ID: a137d5ad9ffc26be (HTTP path /sql/1.0/warehouses/a137d5ad9ffc26be) · Serverless environment version: (set in P1 step 5.1)
URLs: none deployed yet

## LLM models seen 2026-10-12 (re-check free availability in P3)
Groq: openai/gpt-oss-20b, openai/gpt-oss-120b, qwen/qwen3.8-27b, meta-llama/llama-prompt-guard-2-22m / -86m
Gemini: Flash family 2.5 to 3.8 (flash and flash-lite); pin a version, never *-latest

## Probe results (2026-10-12)
Pass: P-01 catalogs rap_dev/rap_prod · P-02 volume upload (parent folder must exist: fs mkdir) · P-03 bundle deploy + serverless run (bundles now "Declarative Automation Bundles") · P-04 wheel task · P-05 condition task + run_if NONE_FAILED · P-06 dbt-databricks vs warehouse (dbt task inside a job: test in P1 5.1) · P-07 Auto Loader · P-08 UC model + alias · P-09 serverless reaches Open-Meteo (HTTP 200; keep Actions-side fetch) · P-10 Actions to Databricks · P-11 rap-data write + read tokens · P-13 512 MB budget (peak 182 MB) · P-14 Neon from PC + Actions · P-19 Streamlit from subfolder + secrets
Deferred: P-12 Render needs card verification (decide before P2 11.2) · P-15/P-16/P-17/P-18 at P3 start · P-20/P-21 before P4 training
Fallbacks taken: none

## Data facts
train 125,497,040 · items 4,100 · stores 54 · transactions 83,488 · oil 1,218 · holidays_events 350 · train dates 2013-01-01 to 2017-08-15

## Contract versions
none yet

## Decisions since the spec
- 2026-10-12: Neon projects created via Vercel integration (personal Neon org not available)
- 2026-10-12: Public demos show store/family aggregates only; copilot gated by RAP_DEMO_ACCESS_CODE (Kaggle rule 7B)

## Known issues
- rap-data tokens and Neon passwords were exposed in chat: regenerate before P1 day 5 and before P2
- PC shows F1 at boot and may reset BIOS (suspect CMOS battery): re-check VT-x after power loss

## Token renewal dates
RAP_DATA_WRITE_TOKEN 2027-01-10 · RAP_DATA_READ_TOKEN 2027-01-10 · DATABRICKS_TOKEN 2027-01-10

## Versions (recorded 2026-10-12)
```
git version 2.43.0
openjdk version "17.0.20.1" 2026-08-18
uv 0.13.0 (x86_64-unknown-linux-gnu)
Python 3.12.15
v24.21.0
Docker version 29.8.2, build 7fc2dff
Databricks CLI v1.20.0
gh version 2.45.0 (2025-07-18 Ubuntu 2.45.0-1ubuntu0.3)
pre-commit 4.6.2
NVIDIA GeForce GTX 1650, 610.88
```
