#!/usr/bin/env python3
"""
Analyze knowledge base to suggest queries with high match potential.

This script:
1. Extracts common topics from the knowledge base
2. Identifies well-covered aspect combinations
3. Generates example queries likely to produce good matches

Usage:
    python suggest_queries.py --top 20
"""

import argparse
import psycopg2
from collections import Counter, defaultdict
import re
from typing import List, Dict, Tuple

# Common NGS-related keywords by category
PATHOGEN_KEYWORDS = [
    'bacteria', 'bacterial', 'virus', 'viral', 'fungus', 'fungal', 'parasite',
    'meningitis', 'encephalitis', 'sepsis', 'pneumonia',
    'tuberculosis', 'tb', 'cryptococcus', 'candida', 'aspergillus',
    'hsv', 'cmv', 'ebv', 'vzv', 'enterovirus', 'arbovirus',
    'salmonella', 'listeria', 'streptococcus', 'staphylococcus',
    'e. coli', 'klebsiella', 'pseudomonas', 'acinetobacter'
]

METHOD_KEYWORDS = [
    'mngs', 'metagenomic', 'targeted sequencing', 'whole genome',
    'amplicon', 'nanopore', 'minion', 'pacbio', 'illumina', 'miseq',
    'long-read', 'short-read', 'single-molecule', 'smrt',
    'rna-seq', 'dna-seq', '16s', '18s'
]

SPECIMEN_KEYWORDS = [
    'csf', 'cerebrospinal fluid', 'blood', 'plasma', 'serum',
    'respiratory', 'bronchoalveolar', 'bal', 'sputum',
    'tissue', 'biopsy', 'stool', 'urine', 'abscess'
]

METRIC_KEYWORDS = [
    'sensitivity', 'specificity', 'accuracy', 'ppv', 'npv',
    'turnaround time', 'tat', 'cost', 'time to result',
    'detection limit', 'limit of detection', 'lod'
]


def extract_keyword_frequencies(cursor, keywords: List[str], limit: int = 1000) -> Counter:
    """
    Count how often keywords appear in high-quality chunks.

    Args:
        cursor: Database cursor
        keywords: List of keywords to search for
        limit: Number of top chunks to analyze

    Returns:
        Counter of keyword frequencies
    """
    # Get top chunks by centrality (chunks with many connections/citations)
    cursor.execute("""
        SELECT pc.full_text
        FROM paper_chunks pc
        WHERE pc.full_text IS NOT NULL
          AND LENGTH(pc.full_text) > 200
        LIMIT %s
    """, (limit,))

    texts = [row[0].lower() for row in cursor.fetchall()]
    combined_text = ' '.join(texts)

    counts = Counter()
    for keyword in keywords:
        # Use word boundaries for better matching
        pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
        matches = len(re.findall(pattern, combined_text))
        if matches > 0:
            counts[keyword] = matches

    return counts


def find_well_covered_combinations(cursor) -> List[Dict]:
    """
    Find combinations of aspects that appear together frequently.

    Returns:
        List of well-covered query patterns
    """
    # Sample sections that likely contain multiple aspects
    cursor.execute("""
        SELECT
            pc.heading,
            pc.full_text,
            p.title,
            1 AS count
        FROM paper_chunks pc
        JOIN papers p ON pc.paper_id = p.id
        WHERE pc.heading ILIKE '%result%'
           OR pc.heading ILIKE '%method%'
           OR pc.heading ILIKE '%discussion%'
        LIMIT 500
    """)

    sections = cursor.fetchall()

    # Analyze which combinations appear together
    combinations = []

    for heading, text, title, _ in sections:
        text_lower = text.lower()

        # Check for method + pathogen + specimen
        has_method = any(kw in text_lower for kw in ['mngs', 'metagenomic', 'sequencing', 'ngs'])
        has_pathogen = any(kw in text_lower for kw in ['bacteria', 'virus', 'fungal', 'pathogen'])
        has_specimen = any(kw in text_lower for kw in ['csf', 'blood', 'plasma', 'respiratory'])
        has_metric = any(kw in text_lower for kw in ['sensitivity', 'specificity', 'accuracy'])

        if has_method and has_pathogen:
            combo = {
                'pattern': [],
                'example_section': heading,
                'example_title': title[:60] + '...' if len(title) > 60 else title
            }

            combo['pattern'].append('method')
            combo['pattern'].append('pathogen')

            if has_specimen:
                combo['pattern'].append('specimen')
            if has_metric:
                combo['pattern'].append('metric')

            combinations.append(combo)

    # Count pattern frequencies
    pattern_counts = Counter(tuple(sorted(c['pattern'])) for c in combinations)

    results = []
    for pattern, count in pattern_counts.most_common(10):
        # Find example
        example = next((c for c in combinations if tuple(sorted(c['pattern'])) == pattern), None)
        results.append({
            'pattern': list(pattern),
            'count': count,
            'example': example['example_section'] if example else '',
            'example_title': example['example_title'] if example else ''
        })

    return results


def generate_query_suggestions(
    pathogen_counts: Counter,
    method_counts: Counter,
    specimen_counts: Counter,
    metric_counts: Counter,
    patterns: List[Dict]
) -> List[str]:
    """
    Generate example queries based on actual KB content.

    Returns:
        List of suggested queries
    """
    queries = []

    # Get top items from each category
    top_pathogens = [k for k, v in pathogen_counts.most_common(5)]
    top_methods = [k for k, v in method_counts.most_common(5)]
    top_specimens = [k for k, v in specimen_counts.most_common(5)]
    top_metrics = [k for k, v in metric_counts.most_common(3)]

    # Pattern 1: Method + Pathogen + Specimen
    if top_methods and top_pathogens and top_specimens:
        queries.append(
            f"What {top_methods[0]} methods detect {top_pathogens[0]} in {top_specimens[0]}?"
        )

    # Pattern 2: Method + Pathogen + Metric
    if top_methods and top_pathogens and top_metrics:
        queries.append(
            f"What is the {top_metrics[0]} of {top_methods[0]} for {top_pathogens[0]} detection?"
        )

    # Pattern 3: Method + Specimen + Metric
    if top_methods and top_specimens and top_metrics:
        queries.append(
            f"What is the {top_metrics[0]} of {top_methods[0]} in {top_specimens[0]} samples?"
        )

    # Pattern 4: Pathogen + Specimen (general)
    if top_pathogens and top_specimens:
        queries.append(
            f"How are {top_pathogens[1] if len(top_pathogens) > 1 else top_pathogens[0]} "
            f"diagnosed in {top_specimens[0]}?"
        )

    # Pattern 5: Method comparison
    if len(top_methods) >= 2:
        queries.append(
            f"How does {top_methods[0]} compare to {top_methods[1]} for pathogen detection?"
        )

    # Pattern 6: Specific pathogen + method
    if len(top_pathogens) >= 2 and top_methods:
        queries.append(
            f"Can {top_methods[0]} detect {top_pathogens[1]}?"
        )

    # Pattern 7: Specimen-specific method
    if len(top_specimens) >= 2 and top_methods:
        queries.append(
            f"What {top_methods[0]} workflow is used for {top_specimens[1]} samples?"
        )

    # Pattern 8: Multiple metrics
    if len(top_metrics) >= 2 and top_methods and top_pathogens:
        queries.append(
            f"What are the {top_metrics[0]} and {top_metrics[1]} of {top_methods[0]} "
            f"for {top_pathogens[0]}?"
        )

    return queries


def main():
    parser = argparse.ArgumentParser(
        description="Analyze KB and suggest high-quality queries"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top keywords to show (default: 20)"
    )
    parser.add_argument(
        "--db",
        default="mngs_kb",
        help="Database name"
    )

    args = parser.parse_args()

    print("\n" + "="*80)
    print("KNOWLEDGE BASE ANALYSIS - Query Suggestions")
    print("="*80 + "\n")

    # Connect
    conn = psycopg2.connect(f"dbname={args.db}")
    cursor = conn.cursor()

    # Get chunk count
    cursor.execute("SELECT COUNT(*) FROM paper_chunks WHERE full_text IS NOT NULL")
    total_chunks = cursor.fetchone()[0]
    print(f"Analyzing {total_chunks} chunks...\n")

    # Extract keyword frequencies
    print("Step 1: Extracting keyword frequencies...")
    pathogen_counts = extract_keyword_frequencies(cursor, PATHOGEN_KEYWORDS)
    method_counts = extract_keyword_frequencies(cursor, METHOD_KEYWORDS)
    specimen_counts = extract_keyword_frequencies(cursor, SPECIMEN_KEYWORDS)
    metric_counts = extract_keyword_frequencies(cursor, METRIC_KEYWORDS)

    # Display top keywords
    print(f"\n{'─'*80}")
    print("TOP KEYWORDS BY CATEGORY")
    print(f"{'─'*80}\n")

    print("🦠 PATHOGENS/INFECTIONS (Top {}):".format(args.top))
    for keyword, count in pathogen_counts.most_common(args.top):
        print(f"   {keyword:25s} {count:4d} mentions")

    print(f"\n🔬 METHODS (Top {args.top}):")
    for keyword, count in method_counts.most_common(args.top):
        print(f"   {keyword:25s} {count:4d} mentions")

    print(f"\n💉 SPECIMENS (Top {args.top}):")
    for keyword, count in specimen_counts.most_common(args.top):
        print(f"   {keyword:25s} {count:4d} mentions")

    print(f"\n📊 METRICS (Top {args.top}):")
    for keyword, count in metric_counts.most_common(args.top):
        print(f"   {keyword:25s} {count:4d} mentions")

    # Find well-covered patterns
    print(f"\n{'─'*80}")
    print("Step 2: Finding well-covered aspect combinations...")
    patterns = find_well_covered_combinations(cursor)

    print(f"\n{'─'*80}")
    print("WELL-COVERED QUERY PATTERNS")
    print(f"{'─'*80}\n")

    for i, pattern in enumerate(patterns, 1):
        aspects = ' + '.join(pattern['pattern'])
        print(f"{i}. {aspects:40s} ({pattern['count']:3d} sections)")
        print(f"   Example: {pattern['example']}")
        print(f"   From: {pattern['example_title']}\n")

    # Generate query suggestions
    print(f"{'─'*80}")
    print("Step 3: Generating query suggestions...")

    queries = generate_query_suggestions(
        pathogen_counts,
        method_counts,
        specimen_counts,
        metric_counts,
        patterns
    )

    print(f"\n{'─'*80}")
    print("SUGGESTED QUERIES (High Match Probability)")
    print(f"{'─'*80}\n")

    for i, query in enumerate(queries, 1):
        print(f"{i}. {query}")

    print(f"\n{'─'*80}")
    print("\nThese queries are generated from actual KB content and should produce")
    print("better matches than queries about topics not well-represented in the KB.")
    print(f"\n{'='*80}\n")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
