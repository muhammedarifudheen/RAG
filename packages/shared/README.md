# @atlas/shared / atlas-shared

One directory, two packages:

| Language   | Package name    | Source                  | Contents |
| ---------- | --------------- | ----------------------- | -------- |
| TypeScript | `@atlas/shared` | `src/`                  | The API's request and response types, used by `apps/web` |
| Python     | `atlas-shared`  | `python/atlas_shared/`  | Empty for now |

## TypeScript

`src/index.ts` describes every shape the API sends or accepts: search results,
answers and citations, the call graph, the file graph, the health report, and
the events of the ingest stream. `apps/web` imports all of its API types from
here and defines none of its own.

The types mirror the Pydantic models in `apps/api/app/schemas.py` and are kept
in sync **by hand**: when a field changes there, change it here in the same
commit. Nothing checks this automatically. Generating the types from the API's
OpenAPI schema would close that gap and is the obvious next step if the two
drift.

There is no build step. The package exports its `.ts` source directly and
`apps/web` compiles it through `transpilePackages` in its `next.config.mjs`.

```ts
import type { AskResponse, HealthReport } from "@atlas/shared";
```

```sh
pnpm --filter @atlas/shared typecheck
```

## Python

Installed in editable mode into each Python app's venv:

```sh
pip install -e ../../packages/shared    # from apps/api or apps/worker
```

The API's models currently live in `apps/api/app/schemas.py`, not here, because
only the API uses them.
