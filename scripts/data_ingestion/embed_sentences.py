#!/usr/bin/env python3
"""
Generate OpenAI embeddings for extracted sentences.

This script reads the output from extract_sentences.py and generates
embeddings using the text-embedding-3-small model.

Usage:
    python embed_sentences.py --input all_sentences.json --output all_sentence_embeddings.json

Cost estimation:
    ~32,000 sentences × ~20 tokens/sentence = 640,000 tokens
    Cost: ~$0.013 (at $0.00002 per 1k tokens)
"""

import argparse
import json
import sys
import os
from typing import List, Dict, Any
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Embedding model
EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 100  # Process in batches to avoid rate limits


def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a batch of texts.

    Args:
        texts: List of text strings

    Returns:
        List of embedding vectors
    """
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts
    )

    return [item.embedding for item in response.data]


def main():
    parser = argparse.ArgumentParser(
        description="Generate embeddings for extracted sentences"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input JSON file from extract_sentences.py"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file with embeddings"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Batch size for API calls (default: {BATCH_SIZE})"
    )

    args = parser.parse_args()

    # Load sentences
    print(f"Loading sentences from {args.input}...", file=sys.stderr)
    with open(args.input, 'r') as f:
        chunks = json.load(f)

    # Count total sentences
    total_sentences = sum(len(chunk["sentences"]) for chunk in chunks)
    print(f"Found {total_sentences} sentences across {len(chunks)} chunks",
          file=sys.stderr)

    # Estimate cost
    avg_tokens_per_sentence = 20
    estimated_tokens = total_sentences * avg_tokens_per_sentence
    estimated_cost = (estimated_tokens / 1000) * 0.00002
    print(f"\nEstimated cost: ${estimated_cost:.4f} "
          f"({estimated_tokens:,} tokens at ~{avg_tokens_per_sentence} tokens/sentence)",
          file=sys.stderr)

    # Ask for confirmation
    response = input("\nProceed with embedding generation? [y/N]: ")
    if response.lower() != 'y':
        print("Aborted.", file=sys.stderr)
        sys.exit(0)

    # Process chunks
    print("\nGenerating embeddings...", file=sys.stderr)
    processed_count = 0
    result_chunks = []

    for chunk in chunks:
        # Collect all sentence texts for this chunk
        sentence_texts = [sent["text"] for sent in chunk["sentences"]]

        # Generate embeddings in batches
        embeddings = []
        for i in range(0, len(sentence_texts), args.batch_size):
            batch = sentence_texts[i:i + args.batch_size]
            batch_embeddings = generate_embeddings_batch(batch)
            embeddings.extend(batch_embeddings)

            processed_count += len(batch)
            if processed_count % 500 == 0:
                print(f"  Processed {processed_count}/{total_sentences} sentences...",
                      file=sys.stderr)

        # Build result structure
        result_sentences = [
            {
                "index": sent["index"],
                "text": sent["text"],
                "embedding": embeddings[i]
            }
            for i, sent in enumerate(chunk["sentences"])
        ]

        result_chunks.append({
            "chunk_id": chunk["chunk_id"],
            "chunk_type": chunk["chunk_type"],
            "sentences": result_sentences
        })

    # Write output
    print(f"\nWriting embeddings to {args.output}...", file=sys.stderr)
    with open(args.output, 'w') as f:
        json.dump(result_chunks, f, indent=2)

    print(f"\n✓ Complete! Generated embeddings for {total_sentences} sentences",
          file=sys.stderr)


if __name__ == "__main__":
    main()
