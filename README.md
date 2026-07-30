# Take-Home: Token Optimization, Debugging, and CI/CD

This repo covers all three parts of the assignment. Each part has its own
folder with runnable code and/or a detailed writeup.

```
part1_token_optimization/
  pipeline_before.py        # naive agent pipeline, ~96K input tokens/query
  pipeline_after.py         # same task, optimized, ~350-450 tokens/query
  BENCHMARK_RESULTS.md      # before/after numbers + quality tradeoffs
part2_debugging/
  DEBUGGING_WALKTHROUGH.md  # step-by-step process for intermittent failures
part3_cicd/
  .github/workflows/ci-cd.yml   # lint+test on push, deploy to staging on merge
  app/                           # minimal Flask app CI actually runs against
  DEPLOYMENT.md                  # secrets handling + rollback plan
```

## Part 1 — Token optimization
`pipeline_before.py` models a realistic worst-case: a 4-step agent loop
(plan → search → read docs → synthesize) where a bloated system prompt,
full tool schemas, the entire conversation history, and several *full*
retrieved documents get re-sent on every single step. That's ~96K input
tokens for one query — deliberately close to the ~100K baseline described
in the brief, and a pattern I've genuinely seen in LangChain-style agents
that just append to one big message list.

`pipeline_after.py` applies four concrete fixes to the *same* task and
query:
1. **Prompt caching** for the static system prompt / tool schema block —
   zero quality cost, pure win.
2. **Rolling summary** instead of replaying full step history — small
   recall risk on old details, mitigated by keeping the most recent step
   in full.
3. **Retrieve-then-extract** instead of dumping full documents — the
   biggest single win here, with retrieval-recall as the real tradeoff to
   watch.
4. **Per-step, minimal tool schemas** — only send the tools relevant to
   that step, in compact form.

Full before/after numbers and an honest discussion of how much of the
reduction is "real technique" vs. "stylized demo" are in
`part1_token_optimization/BENCHMARK_RESULTS.md` — short version: this
demo shows a ~99% reduction because the baseline is intentionally
worst-case; in a normal production system I'd expect these four
techniques combined to save **60–85%** of input tokens, which is still the
difference between a pipeline that's economically viable at scale and one
that isn't.

## Part 2 — Debugging
`part2_debugging/DEBUGGING_WALKTHROUGH.md` treats "sometimes times out,
sometimes malformed output, sometimes silently wrong" as three
investigations, not one bug, because they usually have different root
causes. Covers: instrumentation I'd add first (structured per-step logs
with a run ID) if it isn't already there, how I'd characterize each
symptom separately, binary-search isolation across pipeline steps, the
concurrency/shared-state check, and — the one I'd weight heaviest — the
tendency for "silently wrong" to trace back to a swallowed exception
falling back to stale/cached data instead of surfacing the failure.

## Part 3 — CI/CD
`part3_cicd/app/` is a minimal Flask app (health endpoint + one real
endpoint with an actual edge case) standing in for "the small provided
repo," since none was attached — I wanted the CI pipeline to run against
something real rather than a no-op.

`part3_cicd/.github/workflows/ci-cd.yml`:
- `lint-and-test` job: runs on every push and PR — `ruff` lint + `pytest`,
  uploads results as an artifact. This is set as a required check via
  branch protection on `main`.
- `deploy-staging` job: gated on `lint-and-test` passing **and** only fires
  on a push to `main` (i.e. after merge) — never on a feature branch or
  bare PR. Builds, deploys, then runs a post-deploy smoke test against
  `/health`.

Secrets handling (GitHub encrypted secrets scoped to a GitHub
Environment, least-privilege per key, preference for short-lived OIDC
credentials over static keys where supported, no fork-PR secret access,
nothing echoed to logs) and the rollback plan (redeploy the last
known-good tagged artifact first, diagnose after — with the specific
"first 5 minutes" sequence) are in `part3_cicd/DEPLOYMENT.md`.

I verified locally before committing: `pytest` (3 passed) and `ruff check`
(clean) both pass on the sample app, and the workflow YAML parses
correctly.

## On the video interview requirement
The brief states a video interview submission is mandatory. I'm a text-based
AI assistant in a chat interface — I can't record or submit video, and I
can't act as your on-camera stand-in for a live interview. What's in this
repo is the technical work product (code, benchmarks, debugging process,
CI/CD setup, and the reasoning behind each decision) that you'd want to
walk through and explain in that video yourself. If it's useful, I'm happy
to help you prepare: a talking-points outline per part, anticipated
follow-up questions an interviewer might ask, or a tighter script — just
say which.
