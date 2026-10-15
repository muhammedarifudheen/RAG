---
title: Atlas API
emoji: 🗺️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Atlas API

The server behind the public Atlas website: Postgres with pgvector, the FastAPI
service and the embedding model in one container. The website is a separate
static site on GitHub Pages that calls this API.

Source: the `apps/api`, `apps/worker` and `packages/shared` folders of the Atlas
repository; this Space is assembled from them by
`scripts/deploy-huggingface.ps1`.

## Settings (Space secrets and variables)

| Name | Purpose |
| ---- | ------- |
| `ADMIN_TOKEN` | Password for adding and removing sources. Visitors can only search and ask. |
| `LLM_PROVIDER` | `gemini` or `anthropic` |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | Key for the chosen provider |
| `CORS_ORIGINS` | JSON list of sites allowed to call the API, e.g. `["https://owner.github.io"]` |
| `SEED_SOURCES` | Links added automatically at every start, separated by spaces |

A free Space keeps nothing across restarts and sleeps after two days without
visitors. `SEED_SOURCES` rebuilds the starter content each time it starts;
anything else an admin adds has to be added again after a restart.
