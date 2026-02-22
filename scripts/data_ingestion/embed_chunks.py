"""
embed_chunks.py

Read chunks.json produced by chunk_article.py, embed each chunk using the
OpenAI API, and save to embeddings.json.

Requires the 'openai' conda environment:
  conda activate openai
  python embed_chunks.py

Options:
  --input   chunks.json file to read (default: chunks.json)
  --output  output file (default: embeddings.json)
  --model   embedding model (default: text-embedding-3-small)
  --dry-run print token estimates and cost without calling the API
"""

import argparse
import json
import os
import sys
import time

# ---------------------------------------------------------------------------
# Pricing (USD per 1M tokens, as of early 2025)
# ---------------------------------------------------------------------------
MODEL_PRICES = {
    "text-embedding-3-large": 0.13,
    "text-embedding-3-small": 0.02,
    "text-embedding-ada-002": 0.10,
}

TOKEN_LIMIT = 8191   # context window for text-embedding-3-*


def estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 chars for English text."""
    return max(1, len(text) // 4)


def print_cost_estimate(chunks: list[dict], model: str) -> int:
    """Print per-chunk token counts and total cost estimate. Returns total tokens."""
    price_per_1m = MODEL_PRICES.get(model, None)

    print(f"\n{'#':<4} {'~Tokens':<9} {'Heading'}")
    print("-" * 70)
    total = 0
    for i, c in enumerate(chunks):
        # Support both "text" (from PDF parser) and "full_text" (from PMC extractor)
        text_content = c.get("full_text") or c.get("text", "")
        t = c.get("token_estimate") or estimate_tokens(text_content)
        total += t
        truncated = " [WILL TRUNCATE]" if t > TOKEN_LIMIT else ""
        print(f"{i+1:<4} {t:<9} {c['heading'][:50]}{truncated}")

    print(f"\nChunks       : {len(chunks)}")
    print(f"Total ~tokens: {total:,}")
    if price_per_1m:
        cost = (total / 1_000_000) * price_per_1m
        print(f"Model        : {model}  (${price_per_1m}/1M tokens)")
        print(f"Est. cost    : ${cost:.6f}")
    else:
        print(f"Model        : {model}  (price unknown)")
    return total


def embed_chunks(chunks: list[dict], model: str) -> list[dict]:
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package not found. Activate the correct conda environment.")

    client = OpenAI()  # reads OPENAI_API_KEY from environment

    embedded = []
    for i, chunk in enumerate(chunks):
        # Support both "text" (from PDF parser) and "full_text" (from PMC extractor)
        text = chunk.get("full_text") or chunk.get("text", "")

        # For empty parent sections (level 1 headings with no text), use heading as text
        if not text or not text.strip():
            heading = chunk.get("heading", "")
            if heading:
                text = heading  # Embed just the heading for structural sections
                if len(text) > 0:
                    print(f"  [info] chunk '{heading[:50]}' has no body text, using heading only")
            else:
                print(f"  [warn] chunk has no text or heading, skipping")
                continue

        tokens = estimate_tokens(text)

        # Truncate if over limit
        if tokens > TOKEN_LIMIT:
            text = text[: TOKEN_LIMIT * 4]
            print(f"  [warn] chunk '{chunk['heading'][:50]}' truncated to ~{TOKEN_LIMIT} tokens")

        print(f"  [{i+1}/{len(chunks)}] ~{tokens} tokens  {chunk['heading'][:55]}")

        response = client.embeddings.create(input=text, model=model, dimensions=1536)

        chunk_copy = dict(chunk)
        chunk_copy["embedding"] = response.data[0].embedding
        chunk_copy["embedding_model"] = model
        chunk_copy["tokens_used"] = response.usage.total_tokens
        embedded.append(chunk_copy)

        # Brief pause to stay within rate limits
        if i < len(chunks) - 1:
            time.sleep(0.05)

    return embedded


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="chunks.json",
                        help="Input chunks JSON file (default: chunks.json)")
    parser.add_argument("--output", default="embeddings.json",
                        help="Output embeddings JSON file (default: embeddings.json)")
    parser.add_argument("--model", default="text-embedding-3-small",
                        choices=list(MODEL_PRICES.keys()),
                        help="OpenAI embedding model (default: text-embedding-3-small)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show token/cost estimates only, do not call API")
    parser.add_argument("--yes", action="store_true",
                        help="Create embedding without asking")
    args = parser.parse_args()

    # Resolve paths relative to current working directory (not script directory)
    in_path = args.input if os.path.isabs(args.input) else os.path.abspath(args.input)

    if not os.path.exists(in_path):
        sys.exit(f"Input file not found: {in_path}\n"
                 "Run chunk_article.py or parse_pdf_article.py first to generate chunks.json")

    with open(in_path, encoding="utf-8") as fh:
        data = json.load(fh)

    # Handle both formats:
    # - List of chunks (from PMC extractor): [{"heading": ..., "full_text": ...}, ...]
    # - Dict with sections (from PDF parser): {"sections": [...], "metadata": {...}}
    if isinstance(data, list):
        chunks = data
    elif isinstance(data, dict) and "sections" in data:
        chunks = data["sections"]
    else:
        sys.exit(f"Unexpected JSON format in {in_path}\n"
                 "Expected either a list of chunks or dict with 'sections' key")

    print(f"Loaded {len(chunks)} chunks from {in_path}")
    total_tokens = print_cost_estimate(chunks, args.model)

    if args.dry_run:
        print("\n--dry-run: no API calls made.")
        return

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("\nOPENAI_API_KEY environment variable not set.")

    if not args.yes:
        confirm = input(f"\nProceed with embedding {len(chunks)} chunks? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    print(f"\nEmbedding with {args.model} ...")
    embedded = embed_chunks(chunks, args.model)

    actual_tokens = sum(c.get("tokens_used", 0) for c in embedded)
    print(f"\nActual tokens used: {actual_tokens:,}")

    # Resolve output path relative to current working directory
    out_path = args.output if os.path.isabs(args.output) else os.path.abspath(args.output)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(embedded, fh, indent=2, ensure_ascii=False)
    print(f"Embeddings saved to {out_path}")


if __name__ == "__main__":
    main()
