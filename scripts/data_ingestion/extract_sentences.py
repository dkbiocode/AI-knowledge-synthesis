#!/usr/bin/env python3
"""
Extract sentences from existing paper_chunks and review_chunks.

This script:
1. Retrieves all chunks from the database
2. Splits each chunk into sentences using regex-based sentence boundary detection
3. Filters out very short sentences (< 20 chars)
4. Outputs JSON for embedding generation

Usage:
    python extract_sentences.py --output sentences.json
    python extract_sentences.py --source papers --output paper_sentences.json
    python extract_sentences.py --source reviews --output review_sentences.json
"""

import argparse
import json
import sys
import re
from typing import List, Dict, Any
import psycopg2


def extract_sentences(text: str, min_length: int = 20) -> List[str]:
    """
    Extract sentences from text using regex-based sentence boundary detection.

    This approach handles scientific text well, including:
    - Abbreviations (Dr., et al., Fig., etc.)
    - Decimal numbers
    - Citations with periods

    Args:
        text: Input text
        min_length: Minimum sentence length in characters

    Returns:
        List of sentence strings
    """
    # Common abbreviations in scientific text that should NOT trigger sentence breaks
    abbreviations = r'(?:Dr|Mr|Ms|Mrs|Prof|Sr|Jr|vs|etc|Fig|al|cf|e\.g|i\.e|viz|approx|ca|et|seq)'

    # Protect abbreviations by temporarily replacing them
    protected_text = re.sub(
        rf'\b({abbreviations})\.',
        r'\1<PERIOD>',
        text,
        flags=re.IGNORECASE
    )

    # Split on sentence boundaries:
    # - Period, exclamation, or question mark
    # - Followed by whitespace
    # - Followed by uppercase letter or digit (new sentence starts)
    # Also handle cases where sentence ends with quote or parenthesis
    sentence_pattern = r'(?<=[.!?])(?<![A-Z]\.)[\s]+(?=[A-Z"\'\(])'

    raw_sentences = re.split(sentence_pattern, protected_text)

    sentences = []
    for sent in raw_sentences:
        # Restore periods in abbreviations
        sent = sent.replace('<PERIOD>', '.')
        sent = sent.strip()

        # Filter very short sentences (likely fragments, citations, etc.)
        if len(sent) >= min_length:
            sentences.append(sent)

    return sentences


def extract_from_papers(cursor, min_length: int = 20) -> List[Dict[str, Any]]:
    """Extract sentences from paper_chunks."""
    print("Extracting sentences from paper_chunks...", file=sys.stderr)

    cursor.execute("""
        SELECT id, full_text
        FROM paper_chunks
        WHERE full_text IS NOT NULL AND full_text != ''
        ORDER BY id
    """)

    results = []
    total_chunks = 0
    total_sentences = 0

    for row in cursor:
        chunk_id, text = row
        sentences = extract_sentences(text, min_length)

        if sentences:
            results.append({
                "chunk_id": chunk_id,
                "chunk_type": "paper",
                "sentences": [
                    {"index": i, "text": sent}
                    for i, sent in enumerate(sentences)
                ]
            })

            total_chunks += 1
            total_sentences += len(sentences)

            if total_chunks % 100 == 0:
                print(f"  Processed {total_chunks} chunks, {total_sentences} sentences...",
                      file=sys.stderr)

    print(f"✓ Extracted {total_sentences} sentences from {total_chunks} paper chunks",
          file=sys.stderr)
    return results


def extract_from_reviews(cursor, min_length: int = 20) -> List[Dict[str, Any]]:
    """Extract sentences from review_chunks."""
    print("Extracting sentences from review_chunks...", file=sys.stderr)

    cursor.execute("""
        SELECT id, full_text
        FROM review_chunks
        WHERE full_text IS NOT NULL AND full_text != ''
        ORDER BY id
    """)

    results = []
    total_chunks = 0
    total_sentences = 0

    for row in cursor:
        chunk_id, text = row
        sentences = extract_sentences(text, min_length)

        if sentences:
            results.append({
                "chunk_id": chunk_id,
                "chunk_type": "review",
                "sentences": [
                    {"index": i, "text": sent}
                    for i, sent in enumerate(sentences)
                ]
            })

            total_chunks += 1
            total_sentences += len(sentences)

    print(f"✓ Extracted {total_sentences} sentences from {total_chunks} review chunks",
          file=sys.stderr)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract sentences from chunks using spaCy"
    )
    parser.add_argument(
        "--source",
        choices=["papers", "reviews", "both"],
        default="both",
        help="Which chunks to process (default: both)"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file"
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=20,
        help="Minimum sentence length in characters (default: 20)"
    )
    parser.add_argument(
        "--db",
        default="mngs_kb",
        help="Database name (default: mngs_kb)"
    )

    args = parser.parse_args()

    # Connect to database
    try:
        conn = psycopg2.connect(f"dbname={args.db}")
        cursor = conn.cursor()
    except psycopg2.Error as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract sentences
    results = []

    if args.source in ["papers", "both"]:
        results.extend(extract_from_papers(cursor, args.min_length))

    if args.source in ["reviews", "both"]:
        results.extend(extract_from_reviews(cursor, args.min_length))

    # Write output
    print(f"\nWriting to {args.output}...", file=sys.stderr)
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)

    # Summary
    total_sentences = sum(len(chunk["sentences"]) for chunk in results)
    print(f"\n✓ Complete!", file=sys.stderr)
    print(f"  Total chunks: {len(results)}", file=sys.stderr)
    print(f"  Total sentences: {total_sentences}", file=sys.stderr)
    print(f"  Output: {args.output}", file=sys.stderr)

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
