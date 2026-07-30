# Part 1 — Token Optimization: Before/After

Run both scripts yourself:

```bash
python3 pipeline_before.py
python3 pipeline_after.py
```

(Token counts use a documented char/word approximation, not a real tokenizer —
this sandbox has no network access to tiktoken's remote vocab file. It's
accurate enough for a *relative* comparison, which is the point.)

## Results for the sample query
Query: *"What has been the pricing trend for this product over the last 5 years?"*
Pipeline: 4-step agent loop (plan → search → read docs → synthesize).

| Step | Before (raw tokens) | After (raw tokens) | After (billed w/ caching) |
|---|---:|---:|---:|
| 1. Plan | 23,636 | 58 | 58 |
| 2. Search | 23,878 | 108 | 69 |
| 3. Read documents | 24,121 | 189 | 149 |
| 4. Synthesize | 24,243 | 96 | 68 |
| **Total** | **~95,878** | **~451** | **~345** |

**Honest caveat:** this demo is deliberately stylized to make each technique's
effect visible in isolation — the "before" script intentionally dumps 7 full
documents (mostly filler/legal boilerplate) and replays the entire history
every step, which is a realistic but worst-case pattern I've seen in
LangChain-style agents that just `.append()` to one big message list. In a
real system with moderately-sized docs and history to begin with, expect
these four techniques combined to cut input tokens by roughly **60–85%**,
not 99%+. The demo exaggerates the starting bloat to make the mechanism
clear; the mechanism itself (cache static content, summarize old history,
retrieve instead of dump, trim tool schemas) is what transfers to production.

## The four optimizations, and their quality tradeoffs

### 1. Prompt caching for static content (system prompt, tool schemas)
- **What:** Anthropic's prompt caching lets you mark a prefix (system prompt,
  tool definitions) with a cache breakpoint. It's written to cache once, then
  read back on every later call in the session at ~10% of normal input-token
  cost, with lower latency too.
- **Quality tradeoff:** **none.** The model sees identical content either
  way — only the billing/latency path changes. This is a pure win and should
  usually be the *first* thing you turn on, before touching anything else.

### 2. Rolling summary instead of full history replay
- **What:** Keep the most recent 1–2 steps verbatim (fresh detail matters
  most there), collapse everything older into a short running summary.
- **Quality tradeoff:** small risk of losing a subtle detail buried in an
  old step's full transcript. Mitigate by only summarizing steps whose
  output was already established as irrelevant, and by re-expanding a
  summarized step back to full text on demand if the model later asks a
  question that the summary can't answer (cheap fallback, rarely triggered).

### 3. Retrieve-then-extract instead of dumping full documents
- **What:** Run retrieval (embedding similarity or keyword windowing) to
  pull only the relevant chunks before the "read docs" step, instead of
  stuffing entire documents into context and hoping the model finds the
  needle.
- **Quality tradeoff:** the real one to watch — retrieval can miss a
  relevant passage a full-text read would have caught (recall risk),
  especially for questions requiring synthesis across scattered facts.
  Mitigate with slightly generous top-k (5–8 chunks, not 1–2), chunk
  overlap so a fact split across a boundary isn't lost, and a fallback path
  where the agent can request the full document if the chunks it got don't
  actually answer the question.

### 4. Minimal, per-step tool schemas
- **What:** Only send schemas for tools actually usable/relevant at that
  step (the "synthesize" step doesn't need `web_search` or `code_exec`
  schemas at all), in compact JSON, not pretty-printed or duplicated.
- **Quality tradeoff:** essentially none, *provided* you're careful not to
  withhold a tool the model will legitimately need at that step — the
  failure mode here isn't lower quality, it's the model wanting to call a
  tool it doesn't currently have. Test each step's tool subset against a
  handful of edge-case queries before shipping.

## What I'd do next in a real system
- Turn on prompt caching first (zero risk, immediate win).
- Instrument actual token usage per step in production (not estimates) so
  the retrieval/summary tuning is based on real distributions, not a
  synthetic example.
- A/B the retrieval top-k against a "full doc" fallback on a sample of
  queries to quantify the recall risk before fully committing.
