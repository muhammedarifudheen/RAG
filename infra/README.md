# Deploying Atlas to Google Cloud

Staging runs entirely on Google Cloud:

| Piece | Where | Name |
| ----- | ----- | ---- |
| Postgres 16 with pgvector | Cloud SQL | `atlas-staging-pg` |
| API (`apps/api`) | Cloud Run service, always one instance | `atlas-staging-api` |
| Web (`apps/web`) | Cloud Run service, scales to zero | `atlas-staging-web` |
| Ingestion (`apps/worker`) | Cloud Run job, run on demand | `atlas-staging-ingest` |
| Database migrations | Cloud Run job, run on every deploy | `atlas-staging-migrate` |
| Secrets | Secret Manager | `atlas-staging-database-url`, `atlas-staging-anthropic-api-key` |
| Images | Artifact Registry | `atlas-staging` |

The work is split in two. **Terraform** (`infra/terraform`) creates what lives
for a long time: the database, registry, secrets, service accounts and the
keyless link to GitHub. You run it by hand, once. **GitHub Actions** builds the
images and deploys the Cloud Run services and jobs on every merge to `main`.

> **Status.** Both images build, and the stack runs end to end under
> `docker compose` (verified on Linux, 2026-10-09). The Terraform passes
> `terraform validate` and the workflows pass `actionlint`, but neither has been
> applied or run: expect to fix something on the first real deploy.

## Before you deploy: this app has no login

Both Cloud Run services are public. Anyone who finds the web URL can ask
questions (each one is billed to your model provider's key), add sources, make
the server fetch web pages of their choosing, and **remove any source**. Rate
limits slow this down and nothing else stops it. For anything beyond a private staging URL, put the web service
behind Identity-Aware Proxy or add authentication first.

## One-time setup

You need a Google Cloud project with billing enabled, the `gcloud` CLI,
Terraform 1.5+, and the repository on GitHub.

### 1. Create the infrastructure

```sh
gcloud auth application-default login

cd infra/terraform
cp terraform.tfvars.example terraform.tfvars     # set project_id, region, github_repository
terraform init
terraform apply
```

Creating the Cloud SQL instance takes about ten minutes. Commit the
`.terraform.lock.hcl` that `init` writes.

Terraform state is stored locally and **contains the database password**. It is
git-ignored; keep it safe, or move it to a bucket (see the comment in
`versions.tf`) before anyone else needs to apply.

### 2. Add the Anthropic API key

Terraform creates this secret empty so that the key never passes through
Terraform state or CI. The API deploy fails until it has a value:

```sh
printf '%s' "sk-ant-..." | gcloud secrets versions add atlas-staging-anthropic-api-key --data-file=-
```

### 3. Tell GitHub where to deploy

In the GitHub repository, create an environment named `staging`
(Settings → Environments) and add one **variable** per line of:

```sh
terraform output
```

The names match: `GCP_PROJECT_ID`, `GCP_REGION`,
`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SERVICE_ACCOUNT`,
`GCP_RUNTIME_SERVICE_ACCOUNT`, `GCP_WEB_SERVICE_ACCOUNT`,
`GCP_ARTIFACT_REPOSITORY` and `CLOUD_SQL_CONNECTION_NAME`. None is secret, and no
Google credential is stored in GitHub: workflows on `main` of your repository
exchange a short-lived GitHub token for Google credentials (Workload Identity
Federation). Tokens from any other repository or branch are refused.

### 4. Deploy

Deploys are off by default so that pushes only run the tests. Turn them on by
adding a **repository** variable (Settings → Secrets and variables → Actions →
Variables) named `DEPLOY_STAGING` with the value `true`.

Then merge to `main`. The first run takes longest because nothing is cached.

## What CI does

**On every pull request** (`.github/workflows/ci.yml`), three jobs in parallel:

- **Worker**: lint and tests.
- **API**: lint and tests against a `pgvector/pgvector:pg16` service container.
  The job fails if any test is skipped, because the suite skips its database
  tests when Postgres is unreachable and that must not pass silently in CI.
- **Web**: lint, type-check, and the Playwright tests against a production build.

**On merge to `main`** (`.github/workflows/deploy-staging.yml`), the same three
jobs run again, then:

1. Build and push the backend image.
2. Run database migrations as a job and wait. If they fail, the deploy stops and
   the running services are untouched.
3. Deploy the API.
4. Update the ingest job's image.
5. Build the web image against the API's URL and deploy it.
6. Request `/api/healthz` through the web app, which checks both services and
   the proxy between them.

Deploys never overlap or cancel each other.

Migrations run before the new API is live, so the *old* API briefly runs
against the *new* schema. Keep migrations backward compatible with the previous
release (add columns before using them; drop them one release later).

## Ingesting a repository

From the web UI, the same as locally: paste a URL on the home page. This runs
inside the API service.

For large repositories, use the job instead. It has its own CPU and memory and
does not slow the API down:

```sh
gcloud run jobs execute atlas-staging-ingest --region <region> --wait \
  --args=-m,worker.ingest,https://github.com/pallets/itsdangerous
```

Either way, an ingest replaces whatever was loaded before. Do not run both at
once: the "one at a time" lock is inside the API process and does not know about
the job.

## Why the API is configured the way it is

| Setting | Reason |
| ------- | ------ |
| `--min-instances 1` | No cold start: loading PyTorch and the embedding model takes several seconds |
| `--no-cpu-throttling` | An ingest runs in a background thread. Without this, Cloud Run takes the CPU away as soon as the browser that started it disconnects, and the ingest stalls |
| `--max-instances 1` | The ingest lock and the rate-limit counters are in process memory, so a second instance would not share them. Move them to a shared store before raising this |
| `--timeout 60m` (API and web) | The ingest progress stream stays open for the whole run, and it passes through the web app's proxy |
| `--memory 4Gi`, `--cpu 2` | PyTorch plus two copies of the embedding model (one for queries, one for ingestion). Clones go to `/tmp`, which on Cloud Run is memory too, so a large repository needs more or should use the job |

Min-instances 1 with CPU always allocated means the API is billed around the
clock; together with Cloud SQL that is the fixed cost of this environment.

## Images

| Image | Dockerfile | Used by |
| ----- | ---------- | ------- |
| `backend` | `apps/api/Dockerfile` | API service, migrate job, ingest job |
| `web` | `apps/web/Dockerfile` | Web service |

The API and worker import each other, so they ship as one image and the jobs
override its command. Both builds use the repo root as context:

```sh
docker build -f apps/api/Dockerfile -t atlas-backend .
docker build -f apps/web/Dockerfile --build-arg API_URL=http://host.docker.internal:8000 -t atlas-web .
```

The web image is specific to one API URL: Next.js fixes the `/api` proxy target
at build time. The backend image contains the embedding model and runs with
Hugging Face offline, so changing `EMBEDDING_MODEL` means changing the
Dockerfile as well.

## Operating

```sh
# Logs
gcloud run services logs read atlas-staging-api --region <region> --limit 100

# Roll back the API to the previous revision
gcloud run revisions list --service atlas-staging-api --region <region>
gcloud run services update-traffic atlas-staging-api --region <region> --to-revisions <revision>=100

# Rotate the Anthropic key, then redeploy (or merge anything) to pick it up
printf '%s' "sk-ant-..." | gcloud secrets versions add atlas-staging-anthropic-api-key --data-file=-
```

A rollback does not undo migrations. Private repositories need a `GITHUB_TOKEN`
secret wired into the API and the ingest job; that is not set up here.

## Tearing down

```sh
gcloud run services delete atlas-staging-api atlas-staging-web --region <region>
gcloud run jobs delete atlas-staging-migrate atlas-staging-ingest --region <region>

cd infra/terraform
terraform apply -var db_deletion_protection=false     # allow the database to be destroyed
terraform destroy
```

The services and jobs are created by the deploy workflow, not Terraform, so
`terraform destroy` alone leaves them running.
