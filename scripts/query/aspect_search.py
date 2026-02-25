#!/usr/bin/env python3
"""
Aspect-based hierarchical search with query decomposition.

This script:
1. Decomposes complex queries into aspects
2. Searches sections with full query (broad context)
3. Searches sentences with aspect-specific embeddings (precise matching)
4. Reports coverage (how many aspects were answered)

Usage:
    python aspect_search.py "What NGS methods detect arboviruses in CSF and what are their sensitivity and turnaround times?"
"""

import sys
import os
import argparse
import psycopg2
from openai import OpenAI
import numpy as np
from typing import List, Dict, Any, Tuple

# Import decomposition function and database config
import json
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from decompose_query import decompose_query, DECOMPOSITION_MODEL
from config.db_config import get_connection

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
EMBEDDING_MODEL = "text-embedding-3-small"


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts in one API call."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts
    )
    return [item.embedding for item in response.data]


def search_sections(cursor, query_embedding, limit=5, domain=None):
    """Search at section level with optional domain filter."""
    domain_filter = ""
    params = [query_embedding, query_embedding, limit]

    if domain:
        domain_filter = "AND p.domain = %s"
        params.insert(2, domain)

    query_sql = f"""
        SELECT
            pc.id,
            pc.paper_id,
            p.title,
            p.domain,
            pc.heading,
            pc.full_text,
            1 - (pc.embedding <=> %s::vector) as similarity
        FROM paper_chunks pc
        JOIN papers p ON pc.paper_id = p.id
        WHERE pc.embedding IS NOT NULL
          {domain_filter}
        ORDER BY pc.embedding <=> %s::vector
        LIMIT %s
    """

    cursor.execute(query_sql, params)
    return cursor.fetchall()


def search_sentences_by_aspect(cursor, chunk_id, aspect_embedding, limit=3):
    """Search sentences within a chunk using aspect-specific embedding."""
    cursor.execute("""
        SELECT
            id,
            sentence_index,
            text,
            1 - (embedding <=> %s::vector) as similarity
        FROM paper_sentences
        WHERE paper_chunk_id = %s
          AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (aspect_embedding, chunk_id, aspect_embedding, limit))

    return cursor.fetchall()


def calculate_coverage(aspect_results: Dict[str, List], threshold: float = 0.70) -> Tuple[int, int]:
    """
    Calculate how many aspects were answered.

    Args:
        aspect_results: Dict mapping aspect names to list of sentence matches
        threshold: Minimum score to count as "answered"

    Returns:
        (answered_count, total_count)
    """
    answered = 0
    for aspect_name, sentences in aspect_results.items():
        if sentences and sentences[0][3] >= threshold:  # sentences[0][3] is similarity score
            answered += 1

    return answered, len(aspect_results)


def classify_result(section_score, best_aspect_score, coverage_pct):
    """Classify result quality based on scores and coverage."""
    if coverage_pct >= 0.80 and best_aspect_score > 0.75:
        return "🎯 COMPLETE ANSWER"
    elif coverage_pct >= 0.60 and section_score > 0.75:
        return "✅ MOSTLY ANSWERED"
    elif coverage_pct >= 0.40:
        return "📌 PARTIAL ANSWER"
    elif section_score > 0.75:
        return "📖 TOPIC DISCUSSED (incomplete)"
    else:
        return "❓ WEAK MATCH"


def main():
    parser = argparse.ArgumentParser(
        description="Aspect-based hierarchical search"
    )
    parser.add_argument(
        "query",
        nargs="+",
        help="Query to search"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Number of sections to retrieve (default: 3)"
    )
    parser.add_argument(
        "--domain",
        choices=["medical", "veterinary"],
        help="Filter by domain"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="Minimum score to count aspect as answered (default: 0.70)"
    )
    parser.add_argument(
        "--decomposition-model",
        default=DECOMPOSITION_MODEL,
        help=f"Model for query decomposition (default: {DECOMPOSITION_MODEL})"
    )
    parser.add_argument(
        "--db-config",
        default="local",
        help="Database configuration to use: 'local' or 'supabase' (default: local)"
    )

    args = parser.parse_args()
    query = " ".join(args.query)

    print(f"\n{'='*80}")
    print(f"ASPECT-BASED SEARCH")
    print(f"{'='*80}")
    print(f"Query: {query}")
    if args.domain:
        print(f"Domain: {args.domain}")
    print(f"{'='*80}\n")

    # Step 1: Decompose query
    print("Step 1: Decomposing query...", file=sys.stderr)
    decomposition = decompose_query(query, args.decomposition_model)

    print(f"Complexity: {'COMPLEX' if decomposition['is_complex'] else 'SIMPLE'}")
    print(f"Aspects identified: {len(decomposition['aspects'])}\n")

    for i, aspect in enumerate(decomposition['aspects'], 1):
        print(f"  {i}. [{aspect['category']}] {aspect['question']}")

    print(f"\n{'-'*80}\n")

    # Step 2: Generate embeddings
    print("Step 2: Generating embeddings...", file=sys.stderr)

    # Full query embedding for section-level search
    # Aspect embeddings for sentence-level search
    texts_to_embed = [query] + [aspect['question'] for aspect in decomposition['aspects']]
    embeddings = get_embeddings_batch(texts_to_embed)

    query_embedding = embeddings[0]
    aspect_embeddings = {
        aspect['name']: embeddings[i+1]
        for i, aspect in enumerate(decomposition['aspects'])
    }

    # Step 3: Connect to database
    conn = get_connection(args.db_config)
    cursor = conn.cursor()

    # Step 4: Section-level search
    print("Step 3: Searching sections...", file=sys.stderr)
    sections = search_sections(cursor, query_embedding, limit=args.limit, domain=args.domain)

    # Step 5: For each section, search sentences by aspect
    print("Step 4: Searching sentences by aspect...\n", file=sys.stderr)

    for result_num, section in enumerate(sections, 1):
        chunk_id, paper_id, title, domain, heading, full_text, section_score = section

        print(f"{'─'*80}")
        print(f"RESULT {result_num}: {title[:70]}...")
        print(f"{'─'*80}")
        print(f"Domain: {domain.upper()}")
        print(f"Section: {heading}")
        print(f"Section Relevance: {section_score:.3f}")

        # Search for each aspect
        aspect_results = {}
        for aspect in decomposition['aspects']:
            aspect_name = aspect['name']
            aspect_emb = aspect_embeddings[aspect_name]

            sentences = search_sentences_by_aspect(cursor, chunk_id, aspect_emb, limit=1)
            aspect_results[aspect_name] = sentences

        # Calculate coverage
        answered, total = calculate_coverage(aspect_results, args.threshold)
        coverage_pct = answered / total if total > 0 else 0

        # Get best aspect score for classification
        best_aspect_score = 0
        if aspect_results:
            scores = [s[0][3] for s in aspect_results.values() if s]
            best_aspect_score = max(scores) if scores else 0

        # Classify result
        quality = classify_result(section_score, best_aspect_score, coverage_pct)

        print(f"\nResult Quality: {quality}")
        print(f"Coverage: {answered}/{total} aspects ({coverage_pct*100:.0f}%)")

        # Show aspect breakdown
        print(f"\n┌─ Aspect Coverage {'─'*57}┐")
        for aspect in decomposition['aspects']:
            aspect_name = aspect['name']
            sentences = aspect_results[aspect_name]

            if sentences:
                sent_id, sent_idx, sent_text, sent_score = sentences[0]

                if sent_score >= args.threshold:
                    indicator = "✓"
                    status = "ANSWERED"
                elif sent_score >= 0.55:
                    indicator = "~"
                    status = "PARTIAL"
                else:
                    indicator = "✗"
                    status = "NOT FOUND"

                print(f"│ {indicator} [{aspect['category']:12s}] {status:10s} (score: {sent_score:.3f})")
                print(f"│   Q: {aspect['question'][:70]}")
                if sent_score >= 0.55:
                    print(f"│   A: {sent_text[:70]}...")
            else:
                print(f"│ ✗ [{aspect['category']:12s}] NOT FOUND")
                print(f"│   Q: {aspect['question'][:70]}")

            print(f"│")

        print(f"└{'─'*78}┘")

        # Show high-quality matches in context
        high_quality_aspects = [
            (aspect, aspect_results[aspect['name']][0])
            for aspect in decomposition['aspects']
            if aspect_results[aspect['name']] and aspect_results[aspect['name']][0][3] >= 0.70
        ]

        if high_quality_aspects:
            print(f"\n📄 High-Confidence Answers:")
            for aspect, (_, _, sent_text, score) in high_quality_aspects:
                print(f"   [{aspect['category']}] {sent_text}")

        print()

    cursor.close()
    conn.close()

    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
