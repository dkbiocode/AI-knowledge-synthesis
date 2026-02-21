#!/usr/bin/env python3
"""
search_references.py

Simple tool to search for papers and citations in the knowledge base.

Usage:
    python search_references.py --title "thrombocytopenia"
    python search_references.py --author "Momoi"
    python search_references.py --pmc PMC7953082
    python search_references.py --ref-id B83
    python search_references.py --search "fever cats"  # searches all fields

    # Interactive mode (no arguments)
    python search_references.py
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


def search_references(cur, title=None, author=None, pmc_id=None, ref_id=None, general_search=None):
    """
    Search for papers/citations in the database.
    Returns list of matching records with paper and citation info.
    """

    # Build query based on search parameters
    conditions = []
    params = {}

    if general_search:
        # Search across all text fields
        conditions.append("""(
            p.title ILIKE %(search)s OR
            p.pmc_id ILIKE %(search)s OR
            c.ref_id ILIKE %(search)s OR
            c.authors ILIKE %(search)s OR
            c.title ILIKE %(search)s
        )""")
        params['search'] = f"%{general_search}%"
    else:
        if title:
            conditions.append("(p.title ILIKE %(title)s OR c.title ILIKE %(title)s)")
            params['title'] = f"%{title}%"

        if author:
            conditions.append("c.authors ILIKE %(author)s")
            params['author'] = f"%{author}%"

        if pmc_id:
            conditions.append("p.pmc_id = %(pmc_id)s")
            params['pmc_id'] = pmc_id

        if ref_id:
            conditions.append("c.ref_id ILIKE %(ref_id)s")
            params['ref_id'] = f"%{ref_id}%"

    if not conditions:
        return []

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            p.id as paper_id,
            p.pmc_id,
            p.title as paper_title,
            p.domain,
            c.ref_id,
            c.authors,
            c.year,
            c.journal,
            c.title as citation_title,
            (SELECT COUNT(*) FROM paper_chunks pc WHERE pc.paper_id = p.id) as chunk_count
        FROM papers p
        LEFT JOIN citations c ON c.paper_id = p.id
        WHERE {where_clause}
        ORDER BY c.year DESC NULLS LAST, c.ref_id
    """

    cur.execute(query, params)
    return cur.fetchall()


def format_result(row):
    """Format a search result for display."""
    lines = []
    lines.append("=" * 80)

    if row['ref_id']:
        lines.append(f"REF ID:   {row['ref_id']}")

    lines.append(f"PMC ID:   {row['pmc_id'] or 'N/A'}")
    lines.append(f"Paper ID: {row['paper_id']}")
    lines.append(f"Domain:   {row['domain'] or 'N/A'}")

    if row['authors']:
        lines.append(f"Authors:  {row['authors']}")

    if row['year']:
        lines.append(f"Year:     {row['year']}")

    if row['journal']:
        lines.append(f"Journal:  {row['journal']}")

    title = row['paper_title'] or row['citation_title']
    if title:
        lines.append(f"Title:    {title}")

    if row['chunk_count']:
        lines.append(f"Chunks:   {row['chunk_count']}")

    return "\n".join(lines)


def interactive_search(cur):
    """Interactive search mode."""
    print("\n" + "=" * 80)
    print("REFERENCE SEARCH - Interactive Mode")
    print("=" * 80)
    print("\nSearch by:")
    print("  1. Title (partial match)")
    print("  2. Author name (partial match)")
    print("  3. PMC ID (exact match)")
    print("  4. Reference ID (partial match, e.g., B83)")
    print("  5. General search (all fields)")
    print("  q. Quit")
    print()

    while True:
        choice = input("Enter choice (1-5, q): ").strip().lower()

        if choice == 'q':
            print("Goodbye!")
            return

        results = []

        if choice == '1':
            term = input("Enter title search term: ").strip()
            if term:
                results = search_references(cur, title=term)

        elif choice == '2':
            term = input("Enter author name: ").strip()
            if term:
                results = search_references(cur, author=term)

        elif choice == '3':
            term = input("Enter PMC ID (e.g., PMC7953082): ").strip()
            if term:
                results = search_references(cur, pmc_id=term)

        elif choice == '4':
            term = input("Enter reference ID (e.g., B83): ").strip()
            if term:
                results = search_references(cur, ref_id=term)

        elif choice == '5':
            term = input("Enter search term: ").strip()
            if term:
                results = search_references(cur, general_search=term)

        else:
            print("Invalid choice. Try again.\n")
            continue

        if results:
            print(f"\nFound {len(results)} result(s):\n")
            for row in results:
                print(format_result(row))
            print()
        else:
            print("\nNo results found.\n")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--title", help="Search by title (partial match)")
    parser.add_argument("--author", help="Search by author name (partial match)")
    parser.add_argument("--pmc", "--pmc-id", dest="pmc_id", help="Search by PMC ID (exact match)")
    parser.add_argument("--ref-id", help="Search by reference ID (partial match, e.g., B83)")
    parser.add_argument("--search", help="General search across all fields")
    parser.add_argument("--dbname", default="mngs_kb", help="Database name (default: mngs_kb)")

    args = parser.parse_args()

    # Connect to database
    conn = get_conn(args.dbname)
    cur = conn.cursor(cursor_factory=DictCursor)

    try:
        # Check if any search parameters provided
        if not any([args.title, args.author, args.pmc_id, args.ref_id, args.search]):
            # Interactive mode
            interactive_search(cur)
        else:
            # Command-line search
            results = search_references(
                cur,
                title=args.title,
                author=args.author,
                pmc_id=args.pmc_id,
                ref_id=args.ref_id,
                general_search=args.search
            )

            if results:
                print(f"\nFound {len(results)} result(s):\n")
                for row in results:
                    print(format_result(row))
                print()
            else:
                print("\nNo results found.\n")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
