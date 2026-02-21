#!/usr/bin/env python3
"""
search_protocols.py

Search tool for NGS diagnostic protocols in the knowledge base.

Usage:
    # Search by modality
    python search_protocols.py --modality mNGS

    # Search by pathogen class
    python search_protocols.py --pathogen virus

    # Search by specimen type
    python search_protocols.py --specimen CSF

    # Search by platform
    python search_protocols.py --platform Illumina

    # Search by clinical context
    python search_protocols.py --context CNS

    # Search by veterinary transferability score
    python search_protocols.py --vet-score 3

    # General text search across all excerpt fields
    python search_protocols.py --search "metagenomic sequencing"

    # Combine filters
    python search_protocols.py --modality mNGS --pathogen virus --vet-score 2

    # Show sources (papers/chunks) for each protocol
    python search_protocols.py --modality mNGS --show-sources

    # Interactive mode
    python search_protocols.py
"""

import argparse
import os
import sys
import psycopg2
from psycopg2.extras import DictCursor


def get_conn(dbname: str = "mngs_kb"):
    """Connect to PostgreSQL database."""
    params = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", 5432)),
        "user": os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname": dbname,
    }
    return psycopg2.connect(**{k: v for k, v in params.items() if v != ""})


def search_protocols(
    cur,
    modality=None,
    pathogen=None,
    context=None,
    specimen=None,
    platform=None,
    vet_score=None,
    general_search=None,
):
    """
    Search for protocols in the database.
    Returns list of matching protocols with source counts.
    """
    conditions = []
    params = {}

    if general_search:
        # Search across all text excerpt fields
        conditions.append("""(
            excerpt_method ILIKE %(search)s OR
            excerpt_performance ILIKE %(search)s OR
            excerpt_limitations ILIKE %(search)s OR
            excerpt_biology ILIKE %(search)s OR
            excerpt_obstacles ILIKE %(search)s OR
            excerpt_transferability ILIKE %(search)s OR
            vet_obstacle_summary ILIKE %(search)s OR
            platform ILIKE %(search)s OR
            bioinformatics_pipeline ILIKE %(search)s
        )""")
        params['search'] = f"%{general_search}%"
    else:
        if modality:
            conditions.append("ngs_modality ILIKE %(modality)s")
            params['modality'] = f"%{modality}%"

        if pathogen:
            conditions.append("pathogen_class ILIKE %(pathogen)s")
            params['pathogen'] = f"%{pathogen}%"

        if context:
            conditions.append("clinical_context ILIKE %(context)s")
            params['context'] = f"%{context}%"

        if specimen:
            conditions.append("specimen_type ILIKE %(specimen)s")
            params['specimen'] = f"%{specimen}%"

        if platform:
            conditions.append("platform ILIKE %(platform)s")
            params['platform'] = f"%{platform}%"

        if vet_score is not None:
            conditions.append("vet_transferability_score = %(vet_score)s")
            params['vet_score'] = vet_score

    if not conditions:
        where_clause = ""
    else:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            p.*,
            COUNT(ps.id) as source_count
        FROM protocols p
        LEFT JOIN protocol_sources ps ON ps.protocol_id = p.id
        {where_clause}
        GROUP BY p.id
        ORDER BY p.id
    """

    cur.execute(query, params)
    return cur.fetchall()


def get_protocol_sources(cur, protocol_id):
    """Get all sources (papers/chunks) for a specific protocol."""
    query = """
        SELECT
            ps.mention_type,
            ps.excerpt_type,
            ps.verbatim_excerpt,
            COALESCE(papers.title, 'Review') as source_title,
            COALESCE(papers.pmc_id, rs.title) as source_id,
            papers.domain,
            COALESCE(pc.heading, rc.heading) as chunk_heading
        FROM protocol_sources ps
        LEFT JOIN paper_chunks pc ON ps.paper_chunk_id = pc.id
        LEFT JOIN review_chunks rc ON ps.review_chunk_id = rc.id
        LEFT JOIN papers ON ps.paper_id = papers.id
        LEFT JOIN review_sources rs ON rc.source_id = rs.id
        WHERE ps.protocol_id = %(protocol_id)s
        ORDER BY ps.id
    """
    cur.execute(query, {"protocol_id": protocol_id})
    return cur.fetchall()


def format_protocol(row, show_sources=False, cur=None):
    """Format a protocol for display."""
    lines = []
    lines.append("=" * 80)
    lines.append(f"PROTOCOL ID: {row['id']}")
    lines.append("")

    # Identity section
    lines.append("IDENTITY:")
    if row['ngs_modality']:
        lines.append(f"  Modality:         {row['ngs_modality']}")
    if row['pathogen_class']:
        lines.append(f"  Pathogen:         {row['pathogen_class']}")
    if row['clinical_context']:
        lines.append(f"  Clinical Context: {row['clinical_context']}")
    if row['specimen_type']:
        lines.append(f"  Specimen:         {row['specimen_type']}")
    if row['platform']:
        lines.append(f"  Platform:         {row['platform']}")
    if row['bioinformatics_pipeline']:
        lines.append(f"  Pipeline:         {row['bioinformatics_pipeline']}")

    # Performance metrics
    if row['sensitivity'] or row['specificity'] or row['turnaround_hours']:
        lines.append("")
        lines.append("PERFORMANCE:")
        if row['sensitivity']:
            lines.append(f"  Sensitivity: {row['sensitivity']}%")
        if row['specificity']:
            lines.append(f"  Specificity: {row['specificity']}%")
        if row['turnaround_hours']:
            lines.append(f"  Turnaround:  {row['turnaround_hours']} hours")

    # Veterinary transferability
    if row['vet_transferability_score'] is not None:
        lines.append("")
        lines.append("VETERINARY TRANSFERABILITY:")
        score_labels = {
            0: "0 - Blocked (fundamental constraints)",
            1: "1 - Needs modification (significant changes required)",
            2: "2 - Likely feasible (minor changes needed)",
            3: "3 - Directly applicable"
        }
        lines.append(f"  Score: {score_labels.get(row['vet_transferability_score'], row['vet_transferability_score'])}")
        if row['vet_obstacle_summary']:
            lines.append(f"  Obstacles: {row['vet_obstacle_summary']}")

    # Excerpts (show first 200 chars of each)
    excerpt_fields = [
        ('excerpt_method', 'METHOD'),
        ('excerpt_performance', 'PERFORMANCE'),
        ('excerpt_limitations', 'LIMITATIONS'),
        ('excerpt_biology', 'BIOLOGY'),
        ('excerpt_obstacles', 'OBSTACLES'),
        ('excerpt_transferability', 'TRANSFERABILITY'),
    ]

    for field, label in excerpt_fields:
        if row[field]:
            lines.append("")
            lines.append(f"{label}:")
            text = row[field][:200] + "..." if len(row[field]) > 200 else row[field]
            lines.append(f"  {text}")

    # Source count
    lines.append("")
    lines.append(f"SOURCES: {row['source_count']} chunk(s)")

    # Optional: show sources
    if show_sources and cur and row['source_count'] > 0:
        sources = get_protocol_sources(cur, row['id'])
        lines.append("")
        lines.append("SOURCE DETAILS:")
        for i, src in enumerate(sources, 1):
            domain = f" [{src['domain']}]" if src['domain'] else ""
            lines.append(f"  {i}. {src['source_title']}{domain}")
            lines.append(f"     {src['source_id']} | {src['chunk_heading']}")
            lines.append(f"     Mention: {src['mention_type']}")
            if src['excerpt_type']:
                lines.append(f"     Type: {src['excerpt_type']}")

    return "\n".join(lines)


def interactive_search(cur):
    """Interactive search mode."""
    print("\n" + "=" * 80)
    print("PROTOCOL SEARCH - Interactive Mode")
    print("=" * 80)
    print("\nSearch by:")
    print("  1. NGS modality (mNGS, WGS, targeted_NGS, etc.)")
    print("  2. Pathogen class (virus, bacteria, fungus, etc.)")
    print("  3. Clinical context (CNS, sepsis, respiratory, etc.)")
    print("  4. Specimen type (CSF, blood, BALF, etc.)")
    print("  5. Platform (Illumina, Nanopore, etc.)")
    print("  6. Veterinary transferability score (0-3)")
    print("  7. General search (all excerpt fields)")
    print("  8. Show all protocols")
    print("  q. Quit")
    print()

    while True:
        choice = input("Enter choice (1-8, q): ").strip().lower()

        if choice == 'q':
            print("Goodbye!")
            return

        results = []
        show_sources = False

        if choice == '1':
            term = input("Enter NGS modality: ").strip()
            if term:
                results = search_protocols(cur, modality=term)

        elif choice == '2':
            term = input("Enter pathogen class: ").strip()
            if term:
                results = search_protocols(cur, pathogen=term)

        elif choice == '3':
            term = input("Enter clinical context: ").strip()
            if term:
                results = search_protocols(cur, context=term)

        elif choice == '4':
            term = input("Enter specimen type: ").strip()
            if term:
                results = search_protocols(cur, specimen=term)

        elif choice == '5':
            term = input("Enter platform: ").strip()
            if term:
                results = search_protocols(cur, platform=term)

        elif choice == '6':
            term = input("Enter vet score (0-3): ").strip()
            try:
                score = int(term)
                results = search_protocols(cur, vet_score=score)
            except ValueError:
                print("Invalid score. Must be 0-3.\n")
                continue

        elif choice == '7':
            term = input("Enter search term: ").strip()
            if term:
                results = search_protocols(cur, general_search=term)

        elif choice == '8':
            results = search_protocols(cur)

        else:
            print("Invalid choice. Try again.\n")
            continue

        if results:
            print(f"\nFound {len(results)} protocol(s):\n")

            # Ask if user wants to see sources
            if len(results) > 0:
                show = input("Show source details? (y/n): ").strip().lower()
                show_sources = (show == 'y')

            for row in results:
                print(format_protocol(row, show_sources=show_sources, cur=cur))
            print()
        else:
            print("\nNo protocols found.\n")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--modality", help="Search by NGS modality")
    parser.add_argument("--pathogen", help="Search by pathogen class")
    parser.add_argument("--context", help="Search by clinical context")
    parser.add_argument("--specimen", help="Search by specimen type")
    parser.add_argument("--platform", help="Search by sequencing platform")
    parser.add_argument("--vet-score", type=int, choices=[0, 1, 2, 3],
                        help="Search by veterinary transferability score (0-3)")
    parser.add_argument("--search", help="General search across all excerpt fields")
    parser.add_argument("--show-sources", action="store_true",
                        help="Show source details (papers/chunks) for each protocol")
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")

    args = parser.parse_args()

    # Connect to database
    conn = get_conn(args.dbname)
    cur = conn.cursor(cursor_factory=DictCursor)

    try:
        # Check if any search parameters provided
        if not any([args.modality, args.pathogen, args.context, args.specimen,
                   args.platform, args.vet_score is not None, args.search]):
            # Interactive mode
            interactive_search(cur)
        else:
            # Command-line search
            results = search_protocols(
                cur,
                modality=args.modality,
                pathogen=args.pathogen,
                context=args.context,
                specimen=args.specimen,
                platform=args.platform,
                vet_score=args.vet_score,
                general_search=args.search
            )

            if results:
                print(f"\nFound {len(results)} protocol(s):\n")
                for row in results:
                    print(format_protocol(row, show_sources=args.show_sources, cur=cur))
                print()
            else:
                print("\nNo protocols found.\n")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
