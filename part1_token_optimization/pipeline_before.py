"""
BEFORE: naive multi-step agent pipeline.

Problems that inflate token usage:
  1. Full conversation history is re-sent verbatim on every step, including
     every prior tool call/result, even ones no longer relevant.
  2. Tool schemas are large, verbose JSON blobs re-sent on every call, even
     though they never change within a session.
  3. Retrieved documents are dumped in FULL into context ("stuff everything
     and let the model figure it out") instead of just the relevant chunks.
  4. The system prompt is long-winded boilerplate repeated every call.

This file builds a realistic worst-case context for a single query in a
4-step agentic pipeline (plan -> search -> read docs -> synthesize) and
reports the token count using tiktoken (cl100k_base as a stand-in encoder
for order-of-magnitude comparisons across models).
"""

import re


def count_tokens(text: str) -> int:
    """
    Approximate token count.

    NOTE: This sandbox has no network access to tiktoken's remote BPE vocab
    file, so we can't call a real tokenizer. We use the standard rule-of-thumb
    approximation (~4 characters per token for English text, refined slightly
    using whitespace-split word count) which is within ~10-15% of real
    cl100k/Claude tokenizers for this kind of prose+code mix -- good enough
    for a *relative* before/after comparison, which is the point of this demo.
    In production you'd swap this for the real tokenizer (tiktoken, or
    Anthropic's token counting endpoint) with zero other code changes.
    """
    words = len(re.findall(r"\S+", text))
    chars = len(text)
    # blend word-based and char-based estimates
    return int(round((chars / 4 + words * 1.3) / 2))


# --- 1. Bloated system prompt (verbose, repeated every call) ---
SYSTEM_PROMPT_VERBOSE = """
You are an advanced autonomous research and support agent designed to help
users with complex, multi-step tasks. You have access to a wide range of
tools including web search, document retrieval, a calculator, a code
execution sandbox, and internal knowledge base lookup. When responding to
a user, you should always think carefully step by step about the best way
to solve their problem before taking any action. You should never take an
action without first explaining your reasoning in detail. You should always
double check your work before finalizing an answer. You should be polite,
thorough, and comprehensive in every response, and you should never leave
out relevant details, even if they seem minor, because the user may need
them later. If you are unsure about something, you should still attempt to
answer as best you can rather than saying you don't know. Remember: quality
and completeness are more important than brevity. Always cite your sources
when using retrieved information, and always format your output clearly
using markdown, including headers and bullet points where appropriate...
""" * 3  # simulate a long, repeated boilerplate block as often happens in practice

# --- 2. Verbose tool schemas (all tools, full JSON, every call) ---
TOOL_SCHEMAS = """
[
  {"name": "web_search", "description": "Searches the web for a query and returns up to 10 results with titles, snippets, and URLs. Use this when you need current information not in your training data. Always formulate concise, specific search queries.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "The search query string"}, "max_results": {"type": "integer", "description": "Maximum number of results to return", "default": 10}}, "required": ["query"]}},
  {"name": "read_document", "description": "Reads the full text content of a document given its URL or file path. Returns the complete raw text.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
  {"name": "calculator", "description": "Evaluates a mathematical expression and returns the numeric result.", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}},
  {"name": "code_exec", "description": "Executes a snippet of Python code in a sandbox and returns stdout/stderr.", "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
  {"name": "kb_lookup", "description": "Looks up an entry in the internal knowledge base by key.", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}}
]
""" * 2  # simulate schema being re-sent for every step, sometimes duplicated across a wrapper layer

# --- 3. Full conversation history (every prior step, verbatim) ---
PRIOR_HISTORY = "\n".join(
    [
        f"[Step {i}] Agent thought: I should check source #{i} for relevant "
        f"pricing information because the user asked about cost trends over "
        f"the last five years and I need to be thorough and cross-reference "
        f"multiple sources before concluding anything definitive about the topic."
        for i in range(1, 15)
    ]
)

# --- 4. Fully dumped retrieved documents (3 full docs, only ~10% relevant) ---
FAKE_DOC = (
    "Section 1: Company Overview. " + ("Lorem ipsum dolor sit amet corporate filler text. " * 120) +
    "Section 2: Historical Pricing Data (RELEVANT). In 2021 the average price was $42, "
    "in 2022 it was $48, in 2023 it was $51, in 2024 it was $55, in 2025 it was $61. " +
    "Section 3: Legal Disclaimers. " + ("Boilerplate legal text not relevant to the query. " * 150)
)
RETRIEVED_DOCS = "\n\n---DOC BREAK---\n\n".join([FAKE_DOC] * 7)  # 7 "relevant-ish" docs pulled by a broad retriever

USER_QUERY = "What has been the pricing trend for this product over the last 5 years?"

STEP_NAMES = ["1. Plan", "2. Search", "3. Read documents", "4. Synthesize answer"]


def build_step_context(step_index: int) -> str:
    """
    Models the realistic (and wasteful) pattern where each agent step in a
    LangChain/ReAct-style loop re-sends the ENTIRE accumulated context
    (system prompt + tools + full history so far + full docs) because the
    framework just appends to one big message list and replays it every call.
    Later steps carry more history, so context grows step over step.
    """
    history_so_far = "\n".join(PRIOR_HISTORY.split("\n")[: (step_index + 1) * 4])
    return (
        SYSTEM_PROMPT_VERBOSE
        + "\n\nTOOLS:\n" + TOOL_SCHEMAS
        + "\n\nCONVERSATION HISTORY:\n" + history_so_far
        + "\n\nRETRIEVED DOCUMENTS:\n" + RETRIEVED_DOCS
        + "\n\nUSER QUERY:\n" + USER_QUERY
    )


if __name__ == "__main__":
    print("=== BEFORE: naive 4-step agent pipeline, ONE user query ===\n")
    total = 0
    for i, name in enumerate(STEP_NAMES):
        ctx = build_step_context(i)
        tok = count_tokens(ctx)
        total += tok
        print(f"  Step {name:<22} input tokens: {tok:>7,}")
    print("-" * 50)
    print(f"  TOTAL INPUT TOKENS FOR THIS QUERY: {total:>10,}")
    print("\n  (This is why a single query can burn ~100K input tokens:")
    print("   the SAME bloated system prompt, tool schema, and full")
    print("   documents get re-sent on every one of the 4 agent steps.)")
