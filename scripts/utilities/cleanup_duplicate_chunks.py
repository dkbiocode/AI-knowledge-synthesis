"""
Cleanup duplicate paper chunks from the database.

This script identifies and removes duplicate chunks that have identical text
within the same paper, keeping only the chunk with the lowest ID.

Usage:
  python cleanup_duplicate_chunks.py --dry-run  # Preview what will be deleted
  python cleanup_duplicate_chunks.py           # Actually delete duplicates
"""

import argparse
import psycopg2
from scripts.query.query_kb import get_conn


def find_duplicates(cur):
    """Find duplicate chunks (same paper_id and text content)."""
    query = """
    WITH chunk_hashes AS (
        SELECT
            id,
            paper_id,
            md5(text) as text_hash,
            ROW_NUMBER() OVER (PARTITION BY paper_id, md5(text) ORDER BY id) as rn
        FROM paper_chunks
    )
    SELECT
        ch.id,
        ch.paper_id,
        ch.text_hash,
        p.pmc_id,
        p.title,
        pc.heading
    FROM chunk_hashes ch
    JOIN paper_chunks pc ON pc.id = ch.id
    JOIN papers p ON p.id = ch.paper_id
    WHERE ch.rn > 1  -- Keep first occurrence, mark rest as duplicates
    ORDER BY ch.paper_id, ch.text_hash, ch.id;
    """

    cur.execute(query)
    return cur.fetchall()


def delete_duplicates(cur, chunk_ids):
    """Delete duplicate chunks by ID."""
    if not chunk_ids:
        return

    placeholders = ','.join(['%s'] * len(chunk_ids))

    # Delete from chunk_clusters first (chunk_id is TEXT in this table)
    # Need to convert chunk_ids to strings and filter by chunk_type='paper'
    chunk_id_strings = [str(cid) for cid in chunk_ids]
    cur.execute(
        f"DELETE FROM chunk_clusters WHERE chunk_type = 'paper' AND chunk_id IN ({placeholders})",
        chunk_id_strings
    )

    # Delete from chunk_citations
    cur.execute(f"DELETE FROM chunk_citations WHERE chunk_id IN ({placeholders})", chunk_ids)

    # Delete from protocol_sources (if applicable)
    cur.execute(f"DELETE FROM protocol_sources WHERE paper_chunk_id IN ({placeholders})", chunk_ids)

    # Finally delete the chunks themselves
    cur.execute(f"DELETE FROM paper_chunks WHERE id IN ({placeholders})", chunk_ids)


def main():
    parser = argparse.ArgumentParser(
        description="Remove duplicate paper chunks from the database"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--dbname',
        default='mngs_kb',
        help='Database name (default: mngs_kb)'
    )

    args = parser.parse_args()

    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        print("Finding duplicate chunks...")
        duplicates = find_duplicates(cur)

        if not duplicates:
            print("✅ No duplicate chunks found!")
            return

        print(f"\n Found {len(duplicates)} duplicate chunks:")
        print("=" * 100)

        # Group by paper for display
        current_paper = None
        paper_dups = []

        for dup in duplicates:
            chunk_id, paper_id, text_hash, pmc_id, title, heading = dup

            if paper_id != current_paper:
                if current_paper is not None:
                    print(f"   {len(paper_dups)} duplicate chunks")
                    paper_dups = []

                current_paper = paper_id
                print(f"\n📄 Paper {paper_id}: {pmc_id}")
                print(f"   {title[:80]}")

            paper_dups.append(chunk_id)
            print(f"   - Chunk {chunk_id}: {heading[:60] if heading else '(no heading)'}")

        if paper_dups:
            print(f"   {len(paper_dups)} duplicate chunks")

        print("\n" + "=" * 100)
        print(f"\nTotal duplicates to remove: {len(duplicates)}")

        if args.dry_run:
            print("\n🔍 DRY RUN - No changes made")
        else:
            response = input("\n⚠️  Proceed with deletion? (yes/no): ")
            if response.lower() == 'yes':
                chunk_ids = [dup[0] for dup in duplicates]

                print("\nDeleting duplicates...")
                delete_duplicates(cur, chunk_ids)

                conn.commit()
                print(f"✅ Deleted {len(chunk_ids)} duplicate chunks")
            else:
                print("❌ Deletion cancelled")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
