# Part 3 — Secrets Handling & Rollback Plan

## CI/CD pipeline
See `.github/workflows/ci-cd.yml`:
- **On every push (any branch) and every PR into `main`:** install deps,
  `ruff check` (lint), `pytest` (tests). This is the required gate — PRs
  can't merge if this fails (enforced via GitHub branch protection rules on
  `main`, requiring the `lint-and-test` check to pass).
- **On push to `main` (i.e. after a PR merge):** a second job,
  `deploy-staging`, runs *only if* `lint-and-test` passed and only on
  `main`. It builds and deploys to staging, then runs a smoke test against
  the deployed `/health` endpoint.

## 1. Secrets / API key handling
- **Never in code or the workflow file itself.** All credentials live in
  **GitHub Actions encrypted secrets**, scoped to a GitHub **Environment**
  (`staging`, and separately `production` if this pipeline grew a prod
  deploy job). Environment-scoped secrets mean a workflow run only gets
  access to the secrets for the environment it's actually targeting — a PR
  from a feature branch can't read production credentials even if the
  workflow file is edited, because environment protection rules control
  which refs/branches are allowed to deploy to which environment.
- **Least privilege per secret.** The staging deploy key only has
  permission to deploy to staging, not to touch production infra or read
  other services' data. If the deploy target is cloud infra (AWS/GCP), I'd
  use short-lived OIDC-based credentials (GitHub's OIDC provider →
  cloud IAM role) instead of a long-lived static access key stored as a
  secret at all, where the platform supports it — that removes an entire
  class of "leaked static credential" risk.
- **Nothing sensitive echoed to logs.** GitHub Actions automatically masks
  registered secret values in log output, but I still avoid `echo
  $SECRET`-style debugging entirely and never pass secrets as CLI args
  (which can leak via process listing) — env vars only.
- **Rotation.** Secrets get rotated on a schedule and immediately on any
  suspected leak (e.g. a fork PR workflow run, a dependency compromise).
  `pull_request` triggers from forks don't get secret access in this setup
  by default, which avoids a common leak vector (a malicious fork PR
  trying to exfiltrate secrets via a modified workflow file).
- **Local dev** uses a `.env` file (git-ignored) with dummy/sandbox
  credentials, never real staging/prod keys on a developer laptop.

## 2. Rollback plan — first 5 minutes if a deploy breaks production

**Minute 0 — stop the bleeding, don't diagnose yet.**
The first move is always to get production back to a known-good state,
*not* to start debugging the new code live. Diagnosis happens after
rollback, not instead of it.

1. **Immediate rollback to the last known-good deployment.** If deploys are
   containerized/versioned (which they should be — tag every deploy with
   the git SHA), this is a single command: redeploy the previous image tag
   (`docker service update --image myapp:<last-good-sha>` or the
   equivalent for whatever platform — Fly, ECS, Render, k8s `kubectl
   rollout undo` all support this natively). This should take under 2
   minutes if the pipeline is set up right — which is exactly why I always
   keep the previous artifact readily deployable rather than relying on
   "just redeploy from source," which is slower and where the source might
   itself be the problem.
2. **If rollback itself isn't immediately safe** (e.g. the new deploy
   already migrated the database schema in a way the old code can't read),
   the first move instead is to put the service into a maintenance/
   degraded mode or route traffic away from it (feature flag off, load
   balancer pulls the bad instances) rather than serving broken responses
   to users while sorting out the DB state. This is why schema migrations
   should be backward-compatible / additive and deployed as a separate
   step from the code that uses them, specifically so this scenario is
   avoidable.
3. **Confirm the rollback worked** via the health check / smoke test
   endpoint and a quick check of error rates in whatever monitoring is in
   place (this is why the pipeline runs a smoke test post-deploy — the
   same check verifies a rollback too).
4. **Communicate**, in parallel with 1–3, not after: post in the incident
   channel that a rollback is in progress, roughly what triggered it, and
   an ETA — even a one-line "rolling back the 2:14pm deploy, investigating"
   before the rollback finishes.
5. **Only then, diagnose.** Once production is stable again, pull logs and
   the diff between the last-good and broken deploy to find the actual
   cause, write a regression test for it, and fix forward on a branch —
   without the pressure of live user impact.

**Preconditions that make step 1 actually possible in under 2 minutes** (things
I'd set up ahead of time, not scramble for during an incident): every deploy
tagged with its git SHA and kept available as a redeployable artifact for
at least the last N releases; a single-command or single-click rollback
path (not "rebuild from source and redeploy"); a fast, reliable health
check the rollback can be verified against; and either backward-compatible
migrations or migrations decoupled from code deploys so "rollback the
code" doesn't get blocked on "but the DB already changed."
