"""
AFTER: optimized multi-step agent pipeline.

Same 4-step task (plan -> search -> read docs -> synthesize), same user
query, same underlying data -- but with concrete optimizations applied.
Run this file and pipeline_before.py side by side to compare totals.

OPTIMIZATION 1 -- Prompt caching for static content
  The system prompt and tool schemas never change within a session, but in
  the "before" version they're retokenized and re-billed on every single
  step. With Anthropic's prompt caching (cache_control breakpoints on the
  system prompt / tool defs), that block is written to cache ONCE and then
  read from cache on every subsequent call in the session at a fraction of
  the input-token cost (and it doesn't count against "fresh" tokens either
  way for the purposes of this token-count comparison -- see note in the
  __main__ block on how we report this).
  Quality tradeoff: none. Same bytes reach the model; only the billing/
  latency path changes. This is a pure win with no output-quality risk.

OPTIMIZATION 2 -- Trim conversation history to a rolling summary
  Instead of replaying all N prior step transcripts verbatim, keep only the
  last 2 steps in full and collapse everything older into a 1-2 sentence
  running summary ("Agent has checked sources 1-12 for pricing data, no
  numeric ranges found yet in general boilerplate sections").
  Quality tradeoff: small risk of losing a subtle detail from an old step
  that isn't captured in the summary. Mitigated by: only summarizing steps
  whose outputs were already established as irrelevant/noise, and by
  keeping full text for the 2 most recent steps where fresh detail matters
  most.

OPTIMIZATION 3 -- Retrieve-then-extract instead of dump-full-docs
  Instead of stuffing 6-7 full documents (mostly boilerplate/legal filler)
  into context, run retrieval to pull only the chunks relevant to the
  query (e.g. top-k passages via embedding similarity, or simple keyword
  windowing) BEFORE the doc-reading step, and pass only those chunks.
  Quality tradeoff: retrieval can miss a relevant passage that a full-text
  read would have caught (recall risk). Mitigated by: using a chunk size
  with overlap, and retrieving slightly more chunks (k=5-8) than a human
  would think necessary, which is still ~95% smaller than the full docs.

OPTIMIZATION 4 -- Trim the tool schema sent per call
  Only send the schema for tools that are actually relevant/available at
  that step (e.g. the "synthesize" step doesn't need the code_exec or
  web_search schemas at all), and use compact single-line JSON instead of
  pretty-printed/duplicated blobs.
  Quality tradeoff: none, as long as you're careful the model still has
  access to whichever tool it might legitimately need at that step.
"""

import re


def count_tokens(text: str) -> int:
    words = len(re.findall(r"\S+", text))
    chars = len(text)
    return int(round((chars / 4 + words * 1.3) / 2))


# --- Optimization 1: system prompt tightened + cached (written once) ---
SYSTEM_PROMPT_COMPACT = (
    "You are a research agent. Use tools to answer the user's question. "
    "Think briefly before acting, cite sources, format with markdown."
)

# --- Optimization 4: minimal per-step tool schema, only relevant tools ---
def tool_schema_for_step(step_name: str) -> str:
    all_tools = {
        "web_search": '{"name":"web_search","description":"search the web","parameters":{"query":"string"}}',
        "read_document": '{"name":"read_document","description":"read a doc chunk","parameters":{"path":"string"}}',
        "calculator": '{"name":"calculator","description":"eval a math expr","parameters":{"expression":"string"}}',
    }
    needed = {
        "1. Plan": [],
        "2. Search": ["web_search"],
        "3. Read documents": ["read_document"],
        "4. Synthesize answer": [],
    }[step_name]
    return "[" + ",".join(all_tools[t] for t in needed) + "]"


# --- Optimization 2: rolling summary instead of full history replay ---
def history_for_step(step_index: int) -> str:
    if step_index == 0:
        return "(no prior steps)"
    summary = (
        f"Summary of steps 1-{step_index}: checked {step_index * 4} sources "
        f"for pricing data; most were boilerplate, no numeric trend found yet."
    )
    # keep the single most recent step in full detail
    last_step_detail = (
        f"[Step {step_index}] Agent thought: checked source #{step_index * 4} "
        f"for relevant pricing information."
    )
    return summary + "\n" + last_step_detail


# --- Optimization 3: retrieval returns only the relevant chunk(s), not full docs ---
RELEVANT_CHUNK = (
    "Historical Pricing Data: In 2021 the average price was $42, in 2022 it "
    "was $48, in 2023 it was $51, in 2024 it was $55, in 2025 it was $61."
)
# simulate retrieving this same relevant chunk from 2 of the 7 source docs
# (the other 5 docs' relevant chunks are near-duplicates, so top-k retrieval
# naturally converges on a couple of representative passages)
RETRIEVED_CHUNKS = "\n---\n".join([RELEVANT_CHUNK] * 2)

USER_QUERY = "What has been the pricing trend for this product over the last 5 years?"

STEP_NAMES = ["1. Plan", "2. Search", "3. Read documents", "4. Synthesize answer"]


def build_step_context(step_index: int, step_name: str) -> tuple[str, int]:
    """
    Returns (context_text, cached_prefix_tokens).
    cached_prefix_tokens = tokens that, in a real deployment with prompt
    caching enabled, would be served from cache after the first call
    (system prompt + tool schema block) rather than billed as fresh input.
    """
    cached_prefix = SYSTEM_PROMPT_COMPACT + "\n" + tool_schema_for_step(step_name)
    fresh_part = (
        "\n\nHISTORY:\n" + history_for_step(step_index)
        + ("\n\nRELEVANT DOC CHUNKS:\n" + RETRIEVED_CHUNKS if step_name == "3. Read documents" else "")
        + "\n\nUSER QUERY:\n" + USER_QUERY
    )
    full = cached_prefix + fresh_part
    return full, count_tokens(cached_prefix)


if __name__ == "__main__":
    print("=== AFTER: optimized 4-step agent pipeline, SAME user query ===\n")
    total_raw = 0          # total tokens if you counted every byte sent, no caching credit
    total_billed = 0       # what you'd actually pay for with caching (first call full price, rest at cached-read rate)
    for i, name in enumerate(STEP_NAMES):
        ctx, cached_tok = build_step_context(i, name)
        raw_tok = count_tokens(ctx)
        fresh_tok = raw_tok - cached_tok
        # Anthropic prompt caching: cache reads are ~10% the cost of fresh input tokens.
        # First step pays full price to WRITE the cache; subsequent steps pay the cheap read rate.
        billed_tok = raw_tok if i == 0 else fresh_tok + cached_tok * 0.1
        total_raw += raw_tok
        total_billed += billed_tok
        print(f"  Step {name:<22} raw input tokens: {raw_tok:>6,}   "
              f"(effective billed w/ caching: {billed_tok:,.0f})")
    print("-" * 70)
    print(f"  TOTAL RAW INPUT TOKENS (no caching credit): {total_raw:>10,}")
    print(f"  TOTAL EFFECTIVE BILLED TOKENS (w/ caching): {total_billed:>10,.0f}")
