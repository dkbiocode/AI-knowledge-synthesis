"""
load_chunks.py

Load chunks.json (and optionally embeddings.json) into the PostgreSQL
knowledge base, populating:
  - review_sources   (one row for the review article)
  - review_chunks    (one row per section chunk)
  - citations        (one row per unique reference)
  - chunk_citations  (join table linking chunks to their citations)

Run after:
  1. python chunk_article.py       -> chunks.json + reference_index.json
  2. python embed_chunks.py        -> embeddings.json  (optional at this stage)
  3. python setup_db.py            -> database + schema

Usage:
  conda activate openai

  # Load chunks without embeddings (embeddings can be added later):
  python load_chunks.py

  # Load chunks with embeddings:
  python load_chunks.py --embeddings embeddings.json

  # Reload from scratch (clears existing data for this source):
  python load_chunks.py --replace

Connection env vars: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
"""

import argparse
import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values


# ---------------------------------------------------------------------------
# Connection
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
# Loaders
# ---------------------------------------------------------------------------

def upsert_review_source(cur, doc_key: str, meta: dict) -> int:
    """Insert or update the review_sources row. Returns source_id."""
    cur.execute("""
        INSERT INTO review_sources
            (doc_key, title, authors, journal, year, doi, pubmed_id, pmc_id,
             open_access, source_type, domain, html_path, pdf_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'review', %s, %s, %s)
        ON CONFLICT (doc_key) DO UPDATE SET
            title       = EXCLUDED.title,
            authors     = EXCLUDED.authors,
            journal     = EXCLUDED.journal,
            year        = EXCLUDED.year,
            doi         = EXCLUDED.doi,
            pubmed_id   = EXCLUDED.pubmed_id,
            pmc_id      = EXCLUDED.pmc_id,
            open_access = EXCLUDED.open_access,
            domain      = EXCLUDED.domain,
            html_path   = EXCLUDED.html_path,
            pdf_path    = EXCLUDED.pdf_path
        RETURNING id
    """, (
        doc_key,
        meta.get("title"),
        meta.get("authors"),
        meta.get("journal"),
        meta.get("year"),
        meta.get("doi"),
        meta.get("pubmed_id"),
        meta.get("pmc_id"),
        meta.get("open_access", False),
        meta.get("domain", "medical"),
        meta.get("html_path"),
        meta.get("pdf_path"),
    ))
    return cur.fetchone()[0]


def load_citations(cur, source_id: int, reference_index: dict) -> dict[str, int]:
    """
    Insert all citations from reference_index.
    Returns dict mapping ref_id -> citation db id.
    """
    ref_id_to_db_id = {}
    for ref_id, ref in reference_index.items():
        year = ref.get("year")
        try:
            year = int(year) if year else None
        except (ValueError, TypeError):
            year = None

        cur.execute("""
            INSERT INTO citations
                (ref_id, source_id, cite_text, doi, pubmed_id, pmc_id,
                 title, authors, year, journal, open_access)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ref_id, source_id) DO UPDATE SET
                cite_text   = EXCLUDED.cite_text,
                doi         = EXCLUDED.doi,
                pubmed_id   = EXCLUDED.pubmed_id,
                pmc_id      = EXCLUDED.pmc_id,
                title       = EXCLUDED.title,
                authors     = EXCLUDED.authors,
                year        = EXCLUDED.year,
                journal     = EXCLUDED.journal,
                open_access = EXCLUDED.open_access
            RETURNING id
        """, (
            ref_id,
            source_id,
            ref.get("cite_text"),
            ref.get("doi"),
            ref.get("pubmed_id"),
            ref.get("pmc_id"),
            ref.get("title"),
            ref.get("authors"),
            year,
            ref.get("journal"),
            ref.get("open_access", False),
        ))
        ref_id_to_db_id[ref_id] = cur.fetchone()[0]

    return ref_id_to_db_id


def load_chunks(cur, source_id: int, chunks: list[dict],
                embeddings_map: dict, ref_id_to_db_id: dict) -> int:
    """
    Insert review_chunks and chunk_citations rows.
    embeddings_map: dict keyed by section_id -> embedding list (may be empty)
    Returns count of chunks inserted.
    """
    inserted = 0
    for chunk in chunks:
        emb = embeddings_map.get(chunk["section_id"])
        emb_str = f"[{','.join(str(x) for x in emb)}]" if emb else None
        emb_model = chunk.get("embedding_model") if emb else None
        tokens_used = chunk.get("tokens_used") if emb else None

        cur.execute("""
            INSERT INTO review_chunks
                (source_id, section_id, heading, parent_heading, level,
                 text, full_text, char_count, token_estimate,
                 embedding, embedding_model, tokens_used)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::vector, %s, %s)
            RETURNING id
        """, (
            source_id,
            chunk.get("section_id"),
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
        chunk_db_id = cur.fetchone()[0]
        inserted += 1

        # Insert chunk_citations join rows
        for pos, cit in enumerate(chunk.get("citations", [])):
            ref_id = cit["ref_id"]
            citation_db_id = ref_id_to_db_id.get(ref_id)
            if citation_db_id:
                cur.execute("""
                    INSERT INTO chunk_citations (chunk_id, citation_id, position)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (chunk_id, citation_id) DO NOTHING
                """, (chunk_db_id, citation_db_id, pos))

    return inserted


def clear_existing(cur, source_id: int):
    """Remove all chunks and citations for this source (cascades to chunk_citations)."""
    cur.execute("DELETE FROM review_chunks WHERE source_id = %s", (source_id,))
    cur.execute("DELETE FROM citations WHERE source_id = %s", (source_id,))
    print("  Cleared existing chunks and citations for this source.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunks", default="chunks.json",
                        help="chunks.json from chunk_article.py (default: chunks.json)")
    parser.add_argument("--refs", default="reference_index.json",
                        help="reference_index.json from chunk_article.py (default: reference_index.json)")
    parser.add_argument("--embeddings", default=None,
                        help="embeddings.json from embed_chunks.py (optional)")
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
    parser.add_argument("--replace", action="store_true",
                        help="Delete and reload existing data for this source")

    # Review article metadata
    parser.add_argument("--doc-key", default="fcimb-14-1458316",
                        help="Unique key for this document (default: fcimb-14-1458316)")
    parser.add_argument("--title",
                        default="Application of metagenomic next-generation sequencing in the diagnosis of infectious diseases")
    parser.add_argument("--authors", default="Zhao Y, Zhang W, Zhang X")
    parser.add_argument("--journal", default="Frontiers in Cellular and Infection Microbiology")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--doi", default="https://doi.org/10.3389/fcimb.2024.1458316")
    parser.add_argument("--pmc-id", default=None)
    parser.add_argument("--domain", default="medical",
                        choices=["medical", "veterinary", "both"],
                        help="Domain classification (default: medical)")
    parser.add_argument("--html-path", default="main-article-body.html")
    parser.add_argument("--pdf-path", default="fcimb-14-1458316.pdf")

    args = parser.parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    def resolve(p):
        return p if (p is None or os.path.isabs(p)) else os.path.join(script_dir, p)

    chunks_path = resolve(args.chunks)
    refs_path   = resolve(args.refs)
    emb_path    = resolve(args.embeddings)

    for path, name in [(chunks_path, "chunks"), (refs_path, "reference index")]:
        if not os.path.exists(path):
            sys.exit(f"{name} file not found: {path}\nRun chunk_article.py first.")

    # Load JSON files
    print(f"Loading {chunks_path} ...")
    with open(chunks_path) as f:
        chunks = json.load(f)

    print(f"Loading {refs_path} ...")
    with open(refs_path) as f:
        reference_index = json.load(f)

    # Build embeddings map: section_id -> embedding vector
    embeddings_map = {}
    if emb_path and os.path.exists(emb_path):
        print(f"Loading {emb_path} ...")
        with open(emb_path) as f:
            emb_data = json.load(f)
        for item in emb_data:
            if "embedding" in item and item.get("section_id"):
                embeddings_map[item["section_id"]] = item["embedding"]
        print(f"  {len(embeddings_map)} embeddings loaded.")
    else:
        print("No embeddings file provided — chunks will be loaded without embeddings.")
        print("Run embed_chunks.py then reload with --embeddings embeddings.json")

    # Connect and load
    print(f"\nConnecting to database '{args.dbname}' ...")
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        # Upsert source record
        meta = {
            "title":      args.title,
            "authors":    args.authors,
            "journal":    args.journal,
            "year":       args.year,
            "doi":        args.doi,
            "pmc_id":     args.pmc_id,
            "open_access": True,   # Frontiers is OA
            "domain":     args.domain,
            "html_path":  args.html_path,
            "pdf_path":   args.pdf_path,
        }
        source_id = upsert_review_source(cur, args.doc_key, meta)
        print(f"  review_sources id = {source_id}")

        if args.replace:
            clear_existing(cur, source_id)

        # Load citations
        print(f"  Loading {len(reference_index)} citations ...")
        ref_id_to_db_id = load_citations(cur, source_id, reference_index)
        print(f"  Citations loaded.")

        # Load chunks + chunk_citations
        print(f"  Loading {len(chunks)} chunks ...")
        n = load_chunks(cur, source_id, chunks, embeddings_map, ref_id_to_db_id)
        print(f"  {n} chunks loaded.")

        conn.commit()
        print(f"\nDone. Database '{args.dbname}' populated.")

        # Summary query
        cur.execute("SELECT COUNT(*) FROM review_chunks WHERE source_id = %s", (source_id,))
        print(f"  review_chunks rows : {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM citations WHERE source_id = %s", (source_id,))
        print(f"  citations rows     : {cur.fetchone()[0]}")
        cur.execute("""
            SELECT COUNT(*) FROM chunk_citations cc
            JOIN review_chunks rc ON rc.id = cc.chunk_id
            WHERE rc.source_id = %s
        """, (source_id,))
        print(f"  chunk_citations    : {cur.fetchone()[0]}")
        cur.execute("""
            SELECT COUNT(*) FROM review_chunks
            WHERE source_id = %s AND embedding IS NOT NULL
        """, (source_id,))
        print(f"  chunks with embeds : {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        sys.exit(f"Error: {e}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
