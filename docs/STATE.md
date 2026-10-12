# STATE — Retail AI Platform
Updated: 2026-10-12 · Current project: Day 0 · Next step: Part E (probes)

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
Catalogs: rap_dev, rap_prod (pending probe P-01) · RAP_SCHEMA_PREFIX: ""
SQL warehouse ID: (Part E) · Serverless environment version: (Part E)
URLs: none deployed yet

## LLM models seen 2026-10-12 (re-check free availability in P3)
Groq: openai/gpt-oss-20b, openai/gpt-oss-120b, qwen/qwen3.8-27b, meta-llama/llama-prompt-guard-2-22m / -86m
Gemini: Flash family 2.5 to 3.8 (flash and flash-lite); pin a version, never *-latest

## Probe results
(Part E)

## Data facts
(Part F)

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

The command 'docker' could not be found in this WSL 2 distro.
We recommend to activate the WSL integration in Docker Desktop settings.

For details about using Docker Desktop with WSL 2, visit:

https://docs.docker.com/go/wsl2/

Databricks CLI v1.20.0
gh version 2.45.0 (2025-07-18 Ubuntu 2.45.0-1ubuntu0.3)
pre-commit 4.6.2
NVIDIA GeForce GTX 1650, 610.88
```
