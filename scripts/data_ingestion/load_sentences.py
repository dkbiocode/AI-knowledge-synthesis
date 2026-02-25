#!/usr/bin/env python3
"""
Load sentence embeddings into the database.

This script reads the output from embed_sentences.py and loads sentences
with their embeddings into paper_sentences and review_sentences tables.

Usage:
    python load_sentences.py --input all_sentence_embeddings.json
    python load_sentences.py --input all_sentence_embeddings.json --force  # Overwrite existing
"""

import argparse
import json
import sys
from typing import List, Dict, Any
import psycopg2
from psycopg2.extras import execute_values


def load_sentences(cursor, chunks: List[Dict[str, Any]], force: bool = False) -> tuple:
    """
    Load sentences into database tables.

    Args:
        cursor: Database cursor
        chunks: List of chunks with sentences and embeddings
        force: If True, delete existing sentences first

    Returns:
        Tuple of (paper_count, review_count)
    """
    paper_count = 0
    review_count = 0

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        chunk_type = chunk["chunk_type"]

        if chunk_type == "paper":
            table = "paper_sentences"
            fk_column = "paper_chunk_id"
        elif chunk_type == "review":
            table = "review_sentences"
            fk_column = "review_chunk_id"
        else:
            print(f"WARNING: Unknown chunk type '{chunk_type}', skipping",
                  file=sys.stderr)
            continue

        # Optionally delete existing sentences for this chunk
        if force:
            cursor.execute(f"DELETE FROM {table} WHERE {fk_column} = %s", (chunk_id,))

        # Prepare sentence data for batch insert
        sentence_data = [
            (
                chunk_id,
                sent["index"],
                sent["text"],
                sent["embedding"]
            )
            for sent in chunk["sentences"]
        ]

        # Insert sentences
        if sentence_data:
            execute_values(
                cursor,
                f"""
                INSERT INTO {table} ({fk_column}, sentence_index, text, embedding)
                VALUES %s
                ON CONFLICT ({fk_column}, sentence_index) DO NOTHING
                """,
                sentence_data
            )

            if chunk_type == "paper":
                paper_count += len(sentence_data)
            else:
                review_count += len(sentence_data)

    return paper_count, review_count


def main():
    parser = argparse.ArgumentParser(
        description="Load sentence embeddings into database"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input JSON file from embed_sentences.py"
    )
    parser.add_argument(
        "--db",
        default="mngs_kb",
        help="Database name (default: mngs_kb)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing sentences and reload"
    )

    args = parser.parse_args()

    # Load embeddings
    print(f"Loading embeddings from {args.input}...", file=sys.stderr)
    with open(args.input, 'r') as f:
        chunks = json.load(f)

    total_sentences = sum(len(chunk["sentences"]) for chunk in chunks)
    print(f"Found {total_sentences} sentences across {len(chunks)} chunks",
          file=sys.stderr)

    # Connect to database
    try:
        conn = psycopg2.connect(f"dbname={args.db}")
        cursor = conn.cursor()
    except psycopg2.Error as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        sys.exit(1)

    # Load sentences
    print("\nLoading sentences into database...", file=sys.stderr)
    try:
        paper_count, review_count = load_sentences(cursor, chunks, args.force)
        conn.commit()

        print(f"\n✓ Complete!", file=sys.stderr)
        print(f"  Paper sentences: {paper_count}", file=sys.stderr)
        print(f"  Review sentences: {review_count}", file=sys.stderr)
        print(f"  Total: {paper_count + review_count}", file=sys.stderr)

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: Failed to load sentences: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        cursor.close()
        conn.close()

    # Verify counts
    print("\nVerifying database counts...", file=sys.stderr)
    conn = psycopg2.connect(f"dbname={args.db}")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM paper_sentences")
    db_paper_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM review_sentences")
    db_review_count = cursor.fetchone()[0]

    print(f"  Database paper_sentences: {db_paper_count}", file=sys.stderr)
    print(f"  Database review_sentences: {db_review_count}", file=sys.stderr)

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
