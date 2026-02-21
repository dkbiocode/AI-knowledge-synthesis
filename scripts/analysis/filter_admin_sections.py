"""
filter_admin_sections.py

Filter out administrative/boilerplate sections from chunks.

Two modes:
  1. Clean existing database (delete administrative chunks)
  2. Generate blacklist for use in extractors

Usage:
  # Show statistics
  python filter_admin_sections.py --dry-run

  # Clean database (delete administrative chunks)
  python filter_admin_sections.py --clean

  # Export blacklist for extractors
  python filter_admin_sections.py --export-blacklist
"""

import argparse
import os
import re

import psycopg2


# ---------------------------------------------------------------------------
# Administrative section patterns
# ---------------------------------------------------------------------------

ADMIN_SECTION_PATTERNS = [
    # Ethics and consent
    r'^ethics?\s*(approval|statement|review)?$',
    r'^consent\s*(for\s*publication|statement)?$',
    r'^institutional\s*review\s*board',
    r'^irb\s*approval',

    # Author metadata
    r'^author[\'s]?\s*contributions?$',
    r'^author[\'s]?\s*information',
    r'^authors?.*contributions?',
    r'^acknowledgeme?nts?$',
    r'^footnotes?$',

    # Conflicts and competing interests
    r'^conflicts?\s*of\s*interests?$',
    r'^competing\s*interests?$',
    r'^disclosure',
    r'^financial\s*disclosure',

    # Data availability
    r'^data\s*availability\s*statement',
    r'^availability\s*of\s*data',
    r'^associated\s*data$',
    r'^supplementary\s*(materials?|information|data|figures?|tables?)',
    r'^electronic\s*supplementary',
    r'^additional\s*files?',

    # Funding
    r'^funding\s*statement',
    r'^funding\s*information',
    r'^funding$',
    r'^financial\s*support',
    r'^grants?$',

    # Publishing metadata
    r'^copyright',
    r'^open\s*access',
    r'^abbreviations?$',
    r'^publisher.*note',
    r'^received:',
    r'^accepted:',
    r'^published:',

    # Note: Tables and figures can contain protocol data, so we keep them
    # Only filter if they're obviously just captions (contains "legend", "caption")
    r'^(figure|table|fig\.)\s*\d+\s*(legend|caption)',
]

# Compile patterns (case-insensitive)
ADMIN_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in ADMIN_SECTION_PATTERNS]


def is_admin_section(heading: str) -> bool:
    """
    Check if a heading matches administrative section patterns.
    """
    if not heading:
        return False

    heading_clean = heading.strip()

    for pattern in ADMIN_PATTERNS_COMPILED:
        if pattern.search(heading_clean):
            return True

    return False


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def get_conn(dbname: str):
    params = {
        "host":     os.environ.get("PGHOST", "localhost"),
        "port":     int(os.environ.get("PGPORT", 5432)),
        "user":     os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname":   dbname,
    }
    return psycopg2.connect(**{k: v for k, v in params.items() if v != ""})


def analyze_admin_chunks(cur):
    """
    Analyze how many chunks would be filtered.
    Returns: (review_stats, paper_stats)
    """
    # Review chunks
    cur.execute("SELECT id, heading FROM review_chunks WHERE heading IS NOT NULL")
    review_chunks = cur.fetchall()

    review_admin = [(cid, h) for cid, h in review_chunks if is_admin_section(h)]

    # Paper chunks
    cur.execute("SELECT id, heading FROM paper_chunks WHERE heading IS NOT NULL")
    paper_chunks = cur.fetchall()

    paper_admin = [(cid, h) for cid, h in paper_chunks if is_admin_section(h)]

    return {
        'review_total': len(review_chunks),
        'review_admin': len(review_admin),
        'review_admin_chunks': review_admin,
        'paper_total': len(paper_chunks),
        'paper_admin': len(paper_admin),
        'paper_admin_chunks': paper_admin,
    }


def clean_admin_chunks(cur, dry_run=True):
    """
    Delete administrative chunks from database.
    """
    stats = analyze_admin_chunks(cur)

    print(f"\nReview chunks:")
    print(f"  Total: {stats['review_total']}")
    print(f"  Administrative: {stats['review_admin']} ({100*stats['review_admin']/max(stats['review_total'],1):.1f}%)")

    print(f"\nPaper chunks:")
    print(f"  Total: {stats['paper_total']}")
    print(f"  Administrative: {stats['paper_admin']} ({100*stats['paper_admin']/max(stats['paper_total'],1):.1f}%)")

    print(f"\nTotal to delete: {stats['review_admin'] + stats['paper_admin']}")

    if dry_run:
        print("\nDry-run mode: no changes made")
        print("\nSample administrative headings that would be deleted:")
        sample_headings = set()
        for _, h in stats['review_admin_chunks'][:5] + stats['paper_admin_chunks'][:10]:
            sample_headings.add(h)
        for h in sorted(sample_headings)[:15]:
            print(f"  - {h}")
        return 0

    # Delete review chunks
    if stats['review_admin'] > 0:
        review_ids = [cid for cid, _ in stats['review_admin_chunks']]
        cur.execute("""
            DELETE FROM review_chunks
            WHERE id = ANY(%s)
        """, (review_ids,))
        print(f"\nDeleted {cur.rowcount} review chunks")

    # Delete paper chunks
    if stats['paper_admin'] > 0:
        paper_ids = [cid for cid, _ in stats['paper_admin_chunks']]
        cur.execute("""
            DELETE FROM paper_chunks
            WHERE id = ANY(%s)
        """, (paper_ids,))
        print(f"Deleted {cur.rowcount} paper chunks")

    return stats['review_admin'] + stats['paper_admin']


def export_blacklist(output_path):
    """
    Export blacklist patterns to a file for use in extractors.
    """
    with open(output_path, 'w') as f:
        f.write("# Administrative Section Blacklist\n")
        f.write("# Generated by filter_admin_sections.py\n")
        f.write("#\n")
        f.write("# Usage in extractors:\n")
        f.write("#   from src.admin_blacklist import ADMIN_SECTION_PATTERNS\n")
        f.write("#   if any(re.match(p, heading, re.I) for p in ADMIN_SECTION_PATTERNS):\n")
        f.write("#       skip_this_chunk()\n")
        f.write("\n")
        f.write("import re\n\n")
        f.write("ADMIN_SECTION_PATTERNS = [\n")
        for pattern in ADMIN_SECTION_PATTERNS:
            # Use raw string, no escaping needed
            f.write(f"    r'{pattern}',\n")
        f.write("]\n\n")
        f.write("ADMIN_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in ADMIN_SECTION_PATTERNS]\n\n")
        f.write("def is_admin_section(heading: str) -> bool:\n")
        f.write("    if not heading:\n")
        f.write("        return False\n")
        f.write("    for pattern in ADMIN_PATTERNS_COMPILED:\n")
        f.write("        if pattern.search(heading.strip()):\n")
        f.write("            return True\n")
        f.write("    return False\n")

    print(f"Blacklist exported to {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show statistics without making changes")
    parser.add_argument("--clean", action="store_true",
                        help="Delete administrative chunks from database")
    parser.add_argument("--export-blacklist", action="store_true",
                        help="Export blacklist to admin_blacklist.py")
    parser.add_argument("--output", default="admin_blacklist.py",
                        help="Output file for blacklist (default: admin_blacklist.py)")

    args = parser.parse_args()

    if args.export_blacklist:
        export_blacklist(args.output)
        return

    print(f"Connecting to database '{args.dbname}' ...")
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        deleted = clean_admin_chunks(cur, dry_run=args.dry_run or not args.clean)

        if args.clean and not args.dry_run:
            conn.commit()
            print(f"\n✓ Successfully deleted {deleted} administrative chunks")
            print(f"\nRecommendation: Re-run clustering after cleanup:")
            print(f"  python cluster_topics.py --plot")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
