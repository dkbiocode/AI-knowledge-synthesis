"""
load_paper_chunks.py

Load cited paper chunks from pmc_chunks/ into the PostgreSQL knowledge base.

For each file in pmc_chunks/ (e.g. B5_PMC2581791.json or B5_PMC2581791_chunks.json):
  - Parse ref_id (e.g. "B5") and pmc_id (e.g. "PMC2581791") from the filename
  - Look up the matching citations row by (ref_id, source_id) and set citations.paper_id
  - Insert one row into papers per article
  - Insert paper_chunks rows (with embeddings if provided)

Run after:
  1. python load_chunks.py          -> populates citations table
  2. (optional) generate embeddings for pmc chunks

Usage:
  conda activate openai

  # Load all chunk files without embeddings:
  python load_paper_chunks.py

  # Load a single file:
  python load_paper_chunks.py --file pmc_chunks/B5_PMC2581791.json

  # Load with embeddings from a JSON file:
  python load_paper_chunks.py --embeddings pmc_embeddings.json

  # Reload from scratch (deletes existing paper_chunks for each paper):
  python load_paper_chunks.py --replace

Connection env vars: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


# ---------------------------------------------------------------------------
# Connection  (same pattern as load_chunks.py)
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


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

# Matches: B5_PMC2581791.json  or  B5_PMC2581791_chunks.json
# Also matches: B10-animals-14-01578_PMC10904690.json (longer ref_id format)
_FILENAME_RE = re.compile(r"^(B[\d\-\w]+)_(PMC\d+)(?:_chunks)?\.json$", re.IGNORECASE)


def parse_filename(filename: str):
    """
    Return (ref_id, pmc_id) parsed from a pmc_chunks filename, or raise ValueError.

    Examples:
      "B5_PMC2581791.json"        -> ("B5", "PMC2581791")
      "B5_PMC2581791_chunks.json" -> ("B5", "PMC2581791")
    """
    m = _FILENAME_RE.match(filename)
    if not m:
        raise ValueError(f"Cannot parse ref_id/pmc_id from filename: {filename!r}")
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_source_id(cur, doc_key: str) -> int:
    """Return the review_sources.id for the given doc_key."""
    cur.execute("SELECT id FROM review_sources WHERE doc_key = %s", (doc_key,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"review_sources row not found for doc_key={doc_key!r}. "
            "Run load_chunks.py first."
        )
    return row[0]


def upsert_paper(cur, pmc_id: str, citation_meta: dict, domain: str = "medical") -> int:
    """
    Insert or update a papers row derived from the citations record.
    Returns papers.id.

    citation_meta keys: doi, pubmed_id, pmc_id, title, authors, year,
                        journal, open_access
    """
    cur.execute("""
        INSERT INTO papers
            (doi, pubmed_id, pmc_id, title, authors, journal, year, open_access, domain)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (doi) DO UPDATE SET
            pubmed_id   = COALESCE(EXCLUDED.pubmed_id,  papers.pubmed_id),
            pmc_id      = COALESCE(EXCLUDED.pmc_id,     papers.pmc_id),
            title       = COALESCE(EXCLUDED.title,       papers.title),
            authors     = COALESCE(EXCLUDED.authors,     papers.authors),
            journal     = COALESCE(EXCLUDED.journal,     papers.journal),
            year        = COALESCE(EXCLUDED.year,        papers.year),
            open_access = COALESCE(EXCLUDED.open_access, papers.open_access),
            domain      = COALESCE(EXCLUDED.domain,      papers.domain)
        RETURNING id
    """, (
        citation_meta.get("doi") or None,
        citation_meta.get("pubmed_id") or None,
        pmc_id,
        citation_meta.get("title") or None,
        citation_meta.get("authors") or None,
        citation_meta.get("journal") or None,
        citation_meta.get("year") or None,
        citation_meta.get("open_access", False),
        domain,
    ))
    row = cur.fetchone()
    if row:
        return row[0]

    # ON CONFLICT DO UPDATE … RETURNING only returns when a row changed.
    # If the row already existed and no columns changed, fetch it explicitly.
    cur.execute("SELECT id FROM papers WHERE pmc_id = %s", (pmc_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    raise RuntimeError(f"Failed to upsert papers row for pmc_id={pmc_id!r}")


def upsert_paper_no_doi(cur, pmc_id: str, citation_meta: dict, domain: str = "medical") -> int:
    """
    Upsert a papers row when doi is NULL (use pmc_id as the unique key).
    Returns papers.id.
    """
    cur.execute("SELECT id FROM papers WHERE pmc_id = %s", (pmc_id,))
    row = cur.fetchone()
    if row:
        paper_id = row[0]
        # Update any newly available metadata
        cur.execute("""
            UPDATE papers SET
                pubmed_id   = COALESCE(%s, pubmed_id),
                title       = COALESCE(%s, title),
                authors     = COALESCE(%s, authors),
                journal     = COALESCE(%s, journal),
                year        = COALESCE(%s, year),
                open_access = COALESCE(%s, open_access),
                domain      = COALESCE(%s, domain)
            WHERE id = %s
        """, (
            citation_meta.get("pubmed_id") or None,
            citation_meta.get("title") or None,
            citation_meta.get("authors") or None,
            citation_meta.get("journal") or None,
            citation_meta.get("year") or None,
            citation_meta.get("open_access", False),
            domain,
            paper_id,
        ))
        return paper_id

    cur.execute("""
        INSERT INTO papers
            (doi, pubmed_id, pmc_id, title, authors, journal, year, open_access, domain)
        VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        citation_meta.get("pubmed_id") or None,
        pmc_id,
        citation_meta.get("title") or None,
        citation_meta.get("authors") or None,
        citation_meta.get("journal") or None,
        citation_meta.get("year") or None,
        citation_meta.get("open_access", False),
        domain,
    ))
    return cur.fetchone()[0]


def link_citation_to_paper(cur, ref_id: str, source_id: int, paper_id: int) -> bool:
    """
    Set citations.paper_id for the row matching (ref_id, source_id).
    Returns True if a row was updated, False if not found.
    """
    cur.execute("""
        UPDATE citations
        SET paper_id = %s
        WHERE ref_id = %s AND source_id = %s
    """, (paper_id, ref_id, source_id))
    return cur.rowcount > 0


def get_citation_meta(cur, ref_id: str, source_id: int) -> dict | None:
    """
    Fetch metadata stored in the citations row for this reference.
    Returns a dict or None if not found.
    """
    cur.execute("""
        SELECT doi, pubmed_id, pmc_id, title, authors, year, journal, open_access
        FROM citations
        WHERE ref_id = %s AND source_id = %s
    """, (ref_id, source_id))
    row = cur.fetchone()
    if row is None:
        return None
    keys = ["doi", "pubmed_id", "pmc_id", "title", "authors", "year",
            "journal", "open_access"]
    return dict(zip(keys, row))


def clear_paper_chunks(cur, paper_id: int):
    """Delete existing paper_chunks for this paper."""
    cur.execute("DELETE FROM paper_chunks WHERE paper_id = %s", (paper_id,))
    deleted = cur.rowcount
    if deleted:
        print(f"    Cleared {deleted} existing paper_chunks rows.")


def insert_paper_chunks(cur, paper_id: int, chunks: list[dict],
                         embeddings_map: dict) -> int:
    """
    Insert paper_chunks rows for one paper.
    embeddings_map: dict keyed by section_id -> embedding list (may be empty).
    Returns the count of rows inserted.
    """
    inserted = 0
    for chunk in chunks:
        section_id = chunk.get("section_id")
        emb = embeddings_map.get(section_id)
        emb_str = f"[{','.join(str(x) for x in emb)}]" if emb else None
        emb_model = chunk.get("embedding_model") if emb else None
        tokens_used = chunk.get("tokens_used") if emb else None

        cur.execute("""
            INSERT INTO paper_chunks
                (paper_id, section_id, heading, parent_heading, level,
                 text, full_text, char_count, token_estimate,
                 embedding, embedding_model, tokens_used)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::vector, %s, %s)
        """, (
            paper_id,
            section_id,
            chunk.get("heading"),
            chunk.get("parent_heading"),
            chunk.get("level"),
            chunk.get("text"),
            chunk.get("full_text"),
            chunk.get("char_count"),
            chunk.get("token_estimate"),
            emb_str,
            emb_model,
            tokens_used,
        ))
        inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# Per-file processor
# ---------------------------------------------------------------------------

def process_file(cur, chunk_file: Path, source_id: int,
                 embeddings_map: dict, replace: bool, domain: str = "medical") -> dict:
    """
    Process one pmc_chunks JSON file.
    Returns a stats dict: {chunks, linked, skipped_reason}
    """
    try:
        ref_id, pmc_id = parse_filename(chunk_file.name)
    except ValueError as e:
        return {"chunks": 0, "linked": False, "skipped_reason": str(e)}

    with open(chunk_file) as f:
        chunks = json.load(f)

    if not isinstance(chunks, list):
        return {"chunks": 0, "linked": False,
                "skipped_reason": "JSON root is not a list"}

    # Fetch citation metadata stored when load_chunks.py ran
    citation_meta = get_citation_meta(cur, ref_id, source_id)
    if citation_meta is None:
        return {"chunks": 0, "linked": False,
                "skipped_reason": f"No citations row for ref_id={ref_id!r}"}

    # Upsert the papers row
    doi = citation_meta.get("doi")
    if doi:
        paper_id = upsert_paper(cur, pmc_id, citation_meta, domain)
    else:
        paper_id = upsert_paper_no_doi(cur, pmc_id, citation_meta, domain)

    # Link the citation back to the paper
    linked = link_citation_to_paper(cur, ref_id, source_id, paper_id)

    # Replace existing chunks if requested
    if replace:
        clear_paper_chunks(cur, paper_id)

    # Build per-file embeddings subset (section_id keys)
    file_embeddings = {k: v for k, v in embeddings_map.items()}

    n = insert_paper_chunks(cur, paper_id, chunks, file_embeddings)
    return {"chunks": n, "linked": linked, "skipped_reason": None, "paper_id": paper_id}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--chunks-dir", default="pmc_chunks",
        help="Directory of pmc_chunks JSON files (default: pmc_chunks)",
    )
    parser.add_argument(
        "--file", default=None,
        help="Process a single chunk file instead of the whole directory",
    )
    parser.add_argument(
        "--embeddings", default=None,
        help="JSON file mapping section_id -> embedding vector (optional)",
    )
    parser.add_argument(
        "--dbname", default="mngs_kb",
        help="Database name (default: mngs_kb)",
    )
    parser.add_argument(
        "--doc-key", default="fcimb-14-1458316",
        help="doc_key of the parent review in review_sources (default: fcimb-14-1458316)",
    )
    parser.add_argument(
        "--domain", default="medical",
        choices=["medical", "veterinary", "both"],
        help="Domain classification for papers (default: medical)",
    )
    parser.add_argument(
        "--replace", action="store_true",
        help="Delete and reload existing paper_chunks for each paper",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent

    def resolve(p):
        if p is None:
            return None
        p = Path(p)
        return p if p.is_absolute() else script_dir / p

    chunks_dir = resolve(args.chunks_dir)
    emb_path   = resolve(args.embeddings)

    # Collect files to process
    if args.file:
        target = resolve(args.file)
        if not target.exists():
            sys.exit(f"File not found: {target}")
        files = [target]
    else:
        if not chunks_dir.is_dir():
            sys.exit(f"pmc_chunks directory not found: {chunks_dir}\n"
                     "Run download_pmc.py and chunk papers first.")
        files = sorted(chunks_dir.glob("*.json"))
        if not files:
            sys.exit(f"No .json files found in {chunks_dir}")

    # Load embeddings if provided
    embeddings_map: dict[str, list] = {}
    if emb_path and emb_path.exists():
        print(f"Loading embeddings from {emb_path} ...")
        with open(emb_path) as f:
            emb_data = json.load(f)
        # Support both list-of-dicts and dict formats
        if isinstance(emb_data, list):
            for item in emb_data:
                if "embedding" in item and item.get("section_id"):
                    embeddings_map[item["section_id"]] = item["embedding"]
        elif isinstance(emb_data, dict):
            embeddings_map = emb_data
        print(f"  {len(embeddings_map)} embeddings loaded.")
    else:
        print("No embeddings file provided — paper_chunks will be loaded without embeddings.")

    # Connect
    print(f"\nConnecting to database '{args.dbname}' ...")
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        source_id = get_source_id(cur, args.doc_key)
        print(f"  review_sources id = {source_id}  (doc_key={args.doc_key!r})")
        print(f"  Processing {len(files)} file(s) ...\n")

        total_chunks  = 0
        total_papers  = 0
        total_linked  = 0
        skipped       = []

        for chunk_file in files:
            stats = process_file(cur, chunk_file, source_id, embeddings_map, args.replace, args.domain)
            if stats["skipped_reason"]:
                skipped.append((chunk_file.name, stats["skipped_reason"]))
                print(f"  SKIP  {chunk_file.name}: {stats['skipped_reason']}")
            else:
                total_papers += 1
                total_chunks += stats["chunks"]
                if stats["linked"]:
                    total_linked += 1
                link_mark = "linked" if stats["linked"] else "already linked"
                print(f"  OK    {chunk_file.name}  "
                      f"paper_id={stats['paper_id']}  "
                      f"{stats['chunks']} chunks  ({link_mark})")

        conn.commit()

        # Summary
        print(f"\nDone.")
        print(f"  Papers upserted   : {total_papers}")
        print(f"  Citations linked  : {total_linked}")
        print(f"  Chunks inserted   : {total_chunks}")
        if skipped:
            print(f"  Skipped           : {len(skipped)}")
            for name, reason in skipped:
                print(f"    {name}: {reason}")

        # DB summary
        cur.execute("SELECT COUNT(*) FROM papers")
        print(f"\n  papers rows total        : {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM paper_chunks")
        print(f"  paper_chunks rows total  : {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM paper_chunks WHERE embedding IS NOT NULL")
        print(f"  paper_chunks with embeds : {cur.fetchone()[0]}")
        cur.execute(
            "SELECT COUNT(*) FROM citations WHERE source_id = %s AND paper_id IS NOT NULL",
            (source_id,),
        )
        print(f"  citations linked to paper: {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        sys.exit(f"Error: {e}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
