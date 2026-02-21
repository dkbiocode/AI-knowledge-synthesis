"""
export_citations.py

Export citations from the database to a reference_index.json file compatible
with download_pmc.py.

Usage:
  # Export all citations from a specific review source
  python export_citations.py --source-id 3 --output vet_references_export.json

  # Export only citations with PMC IDs
  python export_citations.py --source-id 3 --pmc-only --output vet_pmc_refs.json
"""

import argparse
import json
import os
import sys

import psycopg2


def get_conn(dbname: str):
    params = {
        "host":     os.environ.get("PGHOST", "localhost"),
        "port":     int(os.environ.get("PGPORT", 5432)),
        "user":     os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname":   dbname,
    }
    return psycopg2.connect(**{k: v for k, v in params.items() if v != ""})


def export_citations(source_id: int, pmc_only: bool, dbname: str) -> dict:
    """
    Export citations from the database to a dict keyed by ref_id.
    Returns format compatible with download_pmc.py.
    """
    conn = get_conn(dbname)
    cur = conn.cursor()

    query = """
        SELECT ref_id, cite_text, doi, pubmed_id, pmc_id,
               title, authors, year, journal, open_access
        FROM citations
        WHERE source_id = %s
    """

    if pmc_only:
        query += " AND pmc_id IS NOT NULL"

    query += " ORDER BY ref_id"

    cur.execute(query, (source_id,))
    rows = cur.fetchall()

    reference_index = {}
    for row in rows:
        ref_id, cite_text, doi, pubmed_id, pmc_id, title, authors, year, journal, open_access = row
        reference_index[ref_id] = {
            "ref_id": ref_id,
            "cite_text": cite_text,
            "doi": doi,
            "pubmed_id": pubmed_id,
            "pmc_id": pmc_id,
            "title": title,
            "authors": authors,
            "year": str(year) if year else None,
            "journal": journal,
            "open_access": open_access,
        }

    cur.close()
    conn.close()

    return reference_index


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-id", type=int, required=True,
                        help="Review source ID to export citations from")
    parser.add_argument("--output", default="reference_index_export.json",
                        help="Output JSON file (default: reference_index_export.json)")
    parser.add_argument("--pmc-only", action="store_true",
                        help="Only export citations with PMC IDs")
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = args.output if os.path.isabs(args.output) else os.path.join(script_dir, args.output)

    print(f"Exporting citations from source_id={args.source_id} ...")
    reference_index = export_citations(args.source_id, args.pmc_only, args.dbname)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(reference_index, f, indent=2, ensure_ascii=False)

    total = len(reference_index)
    with_pmc = sum(1 for ref in reference_index.values() if ref.get("pmc_id"))

    print(f"  Exported {total} citations")
    print(f"  {with_pmc} with PMC IDs")
    print(f"  Saved to {out_path}")

    if with_pmc > 0:
        print(f"\nNext step:")
        print(f"  python download_pmc.py --refs {os.path.basename(out_path)} \\")
        print(f"    --outdir html/vet --log vet_download_log.json")


if __name__ == "__main__":
    main()
