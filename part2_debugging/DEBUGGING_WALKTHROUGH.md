# Part 2 — Debugging an Intermittent Multi-Step Agent Pipeline

Symptoms given: **sometimes times out, sometimes returns malformed output,
sometimes silently succeeds with wrong data.** Three different symptoms
usually means three different (or interacting) root causes, not one bug —
so the first job is to stop treating this as "the pipeline is broken" and
start treating it as three separate investigations that happen to share
infrastructure.

## Step 0 — Before touching code: get visibility
If the pipeline doesn't already have structured, step-level logging with
request IDs, I add that *first*, before trying to reproduce anything.
Guessing at an intermittent bug from user reports alone is close to
impossible. Minimum I want per run:
- A unique `run_id` threaded through every step and every log line
- Per-step: input (or a hash/summary of it), output, latency, token counts,
  the exact prompt sent, retry count, and any tool calls with their raw
  results
- Timestamps at step boundaries, not just at the start/end of the whole run

If this is going into an already-live system, I'd wrap it with something
like OpenTelemetry spans (or even just structured JSON logs to start) so I
can filter by `run_id` in whatever log aggregator is in use, rather than
grep-ing raw stdout.

## Step 1 — Reproduce, or at least characterize, each symptom separately

**Timeouts:**
- Pull the logs for every timed-out run and check: is latency creeping up
  gradually (context growing too large over steps — ties back to Part 1) or
  is it a step failing to return at all (hung tool call, dead retry loop,
  waiting on a rate-limited API with no timeout set)?
- Check per-step latency distribution, not just total run time — this tells
  me *which* step is timing out, not just that the run did.
- Grep for retry logic: a naive `while True: retry` around a flaky external
  call is the single most common cause of "sometimes times out" I've seen —
  it isn't the model or the pipeline logic being slow, it's an unbounded
  retry loop around a tool call that's failing silently.

**Malformed output:**
- Pull the raw model output for a handful of failing runs, not the parsed/
  post-processed version. Almost always the "malformed output" is actually
  a parsing assumption that's too strict (e.g. expecting perfect JSON with
  no markdown code fences, or a regex that breaks on an edge case the model
  legitimately returned).
- Check whether the failures correlate with specific inputs (long context,
  unusual characters, a particular tool's output shape) — if malformed
  output only happens after a specific tool call, the issue is probably
  that tool's output getting fed back into the next prompt in a way that
  confuses the model, not the model being "randomly" unreliable.
- Check if a JSON schema / structured output mode is actually being
  enforced at the API level, or if the pipeline is asking the model to
  "please return JSON" in a plain prompt and hoping — the latter is
  inherently flaky and the fix is often just switching to actual
  tool-use / structured-output enforcement rather than any deeper
  debugging.

**Silent success with wrong data — the dangerous one:**
- This is the one that doesn't throw errors, so logs alone won't catch it.
  I want a small labeled set of "known correct" runs (golden test cases with
  expected outputs) that I can diff actual output against, ideally as part
  of CI (see Part 3).
- Walk backward from a known-wrong output through each step's logged
  intermediate output. Usually the wrong data enters at one specific step
  (a retrieval step returning the wrong document, a tool call silently
  returning stale/cached data, a step's output being misassigned to the
  wrong variable/field in the pipeline's internal state).
- Specifically check: is any step swallowing an exception and falling back
  to a default/cached value instead of surfacing the failure? This is the
  single most common cause of "silently wrong" — a `try/except: return
  cached_result` somewhere that was meant to be a safety net but instead
  masks real failures.

## Step 2 — Isolate with binary search across the pipeline
Once I have logs for a handful of failing runs, I don't try to reason about
the whole pipeline at once. I replay the run step-by-step in isolation:
- Take the exact logged input to step 2, run *only* step 2 against it
  directly, check if it reproduces
- If step 2 is fine in isolation but fails in the full pipeline, the bug is
  in how state is passed between steps (serialization, truncation, a race
  condition if anything is async/parallel), not in step 2's own logic
- This narrows "somewhere in a 4-step pipeline" down to "this one step, or
  the handoff between these two specific steps" quickly

## Step 3 — Check for concurrency / shared-state bugs
If the pipeline runs steps in parallel or reuses any client/session object
across requests, intermittent + hard-to-reproduce is the classic signature
of a race condition: a shared HTTP client with connection reuse issues, a
global variable getting mutated by concurrent runs, or an async task not
being properly awaited. I check for this explicitly, especially if the
failure rate correlates with load rather than with specific inputs.

## Step 4 — Check the boring stuff before the exotic stuff
In rough order of "how often this turns out to be the actual cause":
1. An unhandled/under-handled API error (rate limit, transient 5xx) with no
   or bad retry/backoff logic
2. A timeout value that's just too low for the p95 case, not a real bug
3. Non-deterministic model output combined with a downstream step that
   assumes deterministic structure
4. Context window creeping over a limit on longer runs, causing silent
   truncation
5. An actual logic bug in step-handoff code
6. A genuine race condition

I check these roughly in order of likelihood × cheapness-to-check before
assuming it's something exotic.

## Step 5 — Fix, then prove the fix with a regression test
Once isolated, I don't just patch and move on — I add the failing case as
a permanent test (see Part 3's CI setup) so it can't silently regress, and
I add an alert/metric for whatever the fix addresses (e.g. "retry count on
tool X" as a monitored metric if that was the timeout culprit) so I'd catch
a recurrence in production before a user reports it again.
