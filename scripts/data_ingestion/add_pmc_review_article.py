"""
add_pmc_review_article.py

Add a review article to the database with citation extraction:
  1. Download from PMC (if PMCID provided) or use existing HTML file
  2. Extract chunks and citations with admin filtering
  3. Generate embeddings
  4. Load into database (review_sources, review_chunks, citations)
  5. Export citations to JSON file for bulk download

Review articles are loaded into review_sources/review_chunks (not papers/paper_chunks).

Checks for duplicates and skips if review already exists.

Usage:
  # Add by PMCID with auto-generated doc-key
  python add_pmc_review_article.py --pmcid PMC11171117 --domain veterinary \\
    --title "Diagnostic applications of next-generation sequencing in veterinary medicine" \\
    --authors "Momoi Y et al."

  # Add from existing HTML file with custom doc-key
  python add_pmc_review_article.py --html review.html --domain medical \\
    --doc-key my-review-2024 --title "My Review Title"

  # Skip embedding generation
  python add_pmc_review_article.py --pmcid PMC11171117 --domain veterinary \\
    --title "..." --no-embed

  # Export citations to custom file
  python add_pmc_review_article.py --pmcid PMC11171117 --domain veterinary \\
    --title "..." --citations-output my_refs.json
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import psycopg2
import requests


PMC_BASE_URL = "https://pmc.ncbi.nlm.nih.gov/articles"


# ---------------------------------------------------------------------------
# Database helpers
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


def check_review_exists(cur, doc_key: str) -> tuple[bool, int | None]:
    """Check if a review with this doc_key already exists. Returns (exists, source_id)."""
    cur.execute("SELECT id FROM review_sources WHERE doc_key = %s", (doc_key,))
    row = cur.fetchone()
    if row:
        return True, row[0]
    return False, None


def upsert_review_source(cur, doc_key: str, metadata: dict) -> int:
    """Insert or update review_sources row. Returns source_id."""
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
        metadata.get("title"),
        metadata.get("authors"),
        metadata.get("journal"),
        metadata.get("year"),
        metadata.get("doi"),
        metadata.get("pubmed_id"),
        metadata.get("pmc_id"),
        metadata.get("open_access", True),
        metadata.get("domain", "medical"),
        metadata.get("html_path"),
        metadata.get("pdf_path"),
    ))
    return cur.fetchone()[0]


def load_citations(cur, source_id: int, reference_index: dict) -> dict[str, int]:
    """
    Insert citations from reference index.
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


def clear_review_data(cur, source_id: int):
    """Remove existing chunks and citations for this source."""
    cur.execute("DELETE FROM review_chunks WHERE source_id = %s", (source_id,))
    deleted_chunks = cur.rowcount
    cur.execute("DELETE FROM citations WHERE source_id = %s", (source_id,))
    deleted_citations = cur.rowcount
    return deleted_chunks, deleted_citations


def insert_review_chunks(cur, source_id: int, chunks: list[dict],
                        ref_id_to_db_id: dict) -> int:
    """Insert review_chunks and chunk_citations rows. Returns count inserted."""
    inserted = 0
    for chunk in chunks:
        emb = chunk.get("embedding")
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


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_pmc_article(pmc_id: str, dest_path: Path) -> tuple[bool, str]:
    """Download PMC article HTML. Returns (success, message)."""
    url = f"{PMC_BASE_URL}/{pmc_id}/"
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (research KB builder; contact: see repo)"
        })
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            dest_path.write_bytes(response.content)
            size_kb = len(response.content) // 1024
            return True, f"Downloaded ({size_kb} KB)"
        else:
            return False, f"HTTP {response.status_code}"
    except requests.RequestException as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Extract chunks and citations
# ---------------------------------------------------------------------------

def extract_chunks_and_citations(html_path: Path, filter_admin: bool = True) -> tuple[list[dict], dict, dict]:
    """
    Extract chunks and citations from PMC HTML.
    Returns (chunks, citations_dict, metadata).
    """
    try:
        from src.extractors import PMCExtractor
    except ImportError:
        sys.exit("extractors package not found. Check your installation.")

    extractor = PMCExtractor(str(html_path), filter_admin=filter_admin)
    chunks, refs = extractor.extract_all()

    # Convert refs to reference_index format
    reference_index = {}
    for ref_id, ref_data in refs.items():
        reference_index[ref_id] = {
            "ref_id": ref_id,
            "cite_text": ref_data.get("cite_text", ""),
            "doi": ref_data.get("doi"),
            "pubmed_id": ref_data.get("pubmed_id"),
            "pmc_id": ref_data.get("pmc_id"),
            "title": ref_data.get("title"),
            "authors": ref_data.get("authors"),
            "year": ref_data.get("year"),
            "journal": ref_data.get("journal"),
            "open_access": ref_data.get("open_access", False),
        }

    # Extract metadata
    metadata = {}
    soup = extractor.soup

    title_tag = soup.find("h1", class_="content-title")
    if title_tag:
        metadata["title"] = title_tag.get_text(strip=True)

    contrib_group = soup.find("div", class_="contrib-group")
    if contrib_group:
        authors = [a.get_text(strip=True) for a in contrib_group.find_all("a", class_="name")]
        if authors:
            metadata["authors"] = ", ".join(authors[:3])
            if len(authors) > 3:
                metadata["authors"] += " et al."

    journal_tag = soup.find("meta", {"name": "citation_journal_title"})
    if journal_tag:
        metadata["journal"] = journal_tag.get("content")

    year_tag = soup.find("meta", {"name": "citation_publication_date"})
    if year_tag:
        year_str = year_tag.get("content", "").split("/")[0]
        try:
            metadata["year"] = int(year_str)
        except (ValueError, IndexError):
            pass

    doi_tag = soup.find("meta", {"name": "citation_doi"})
    if doi_tag:
        metadata["doi"] = doi_tag.get("content")

    pubmed_tag = soup.find("meta", {"name": "citation_pmid"})
    if pubmed_tag:
        metadata["pubmed_id"] = pubmed_tag.get("content")

    return chunks, reference_index, metadata


# ---------------------------------------------------------------------------
# Embed chunks
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 chars for English text."""
    return max(1, len(text) // 4)


def embed_chunks(chunks: list[dict], model: str = "text-embedding-3-small") -> list[dict]:
    """Add embeddings to chunks using OpenAI API."""
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package not found. Activate the correct conda environment.")

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY environment variable not set.")

    client = OpenAI()

    for i, chunk in enumerate(chunks):
        text = chunk["full_text"]
        tokens = estimate_tokens(text)

        TOKEN_LIMIT = 8191
        if tokens > TOKEN_LIMIT:
            text = text[: TOKEN_LIMIT * 4]
            print(f"    [warn] chunk '{chunk['heading'][:50]}' truncated to ~{TOKEN_LIMIT} tokens")

        print(f"    [{i+1}/{len(chunks)}] Embedding ~{tokens} tokens  {chunk['heading'][:55]}")

        response = client.embeddings.create(input=text, model=model, dimensions=1536)

        chunk["embedding"] = response.data[0].embedding
        chunk["embedding_model"] = model
        chunk["tokens_used"] = response.usage.total_tokens

        if i < len(chunks) - 1:
            time.sleep(0.05)

    return chunks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pmcid",
        help="PMC ID to download and process (e.g., PMC11171117)",
    )
    parser.add_argument(
        "--html",
        help="Path to existing PMC HTML file",
    )
    parser.add_argument(
        "--doc-key",
        help="Unique document key (default: auto-generated from PMC ID)",
    )
    parser.add_argument(
        "--title",
        help="Review article title (extracted from HTML if not provided)",
    )
    parser.add_argument(
        "--authors",
        help="Authors (extracted from HTML if not provided)",
    )
    parser.add_argument(
        "--domain", required=True,
        choices=["medical", "veterinary", "both"],
        help="Domain classification (medical/veterinary/both)",
    )
    parser.add_argument(
        "--dbname", default="mngs_kb",
        help="Database name (default: mngs_kb)",
    )
    parser.add_argument(
        "--citations-output",
        help="Output file for citations JSON (default: <doc_key>_references.json)",
    )
    parser.add_argument(
        "--pmc-only", action="store_true",
        help="Export only citations with PMC IDs in citations file",
    )
    parser.add_argument(
        "--no-embed", action="store_true",
        help="Skip embedding generation (chunks only)",
    )
    parser.add_argument(
        "--no-filter-admin", action="store_true",
        help="Don't filter administrative sections",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force reload even if review already exists",
    )
    parser.add_argument(
        "--keep-html", action="store_true",
        help="Keep downloaded HTML file (saves to html/ directory)",
    )
    args = parser.parse_args()

    if not args.pmcid and not args.html:
        sys.exit("Error: Must provide either --pmcid or --html")

    if args.pmcid and args.html:
        sys.exit("Error: Provide only one of --pmcid or --html")

    script_dir = Path(__file__).parent

    # Determine PMC ID and HTML path
    if args.pmcid:
        pmc_id = args.pmcid.upper()
        if not pmc_id.startswith("PMC"):
            pmc_id = f"PMC{pmc_id}"

        # Generate doc_key if not provided
        if not args.doc_key:
            doc_key = pmc_id
        else:
            doc_key = args.doc_key

        # Download
        if args.keep_html:
            html_dir = script_dir / "html"
            html_dir.mkdir(exist_ok=True)
            html_path = html_dir / f"{pmc_id}.html"
            temp_html = False
        else:
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            html_path = Path(temp_file.name)
            temp_file.close()
            temp_html = True

        print(f"Downloading {pmc_id} from PMC...")
        ok, msg = download_pmc_article(pmc_id, html_path)
        if not ok:
            if temp_html and html_path.exists():
                html_path.unlink()
            sys.exit(f"Error: Failed to download {pmc_id}: {msg}")
        print(f"  {msg}")
    else:
        html_path = Path(args.html)
        if not html_path.exists():
            sys.exit(f"Error: HTML file not found: {html_path}")

        # Try to extract PMC ID from filename
        import re
        match = re.search(r"(PMC\d+)", html_path.name, re.IGNORECASE)
        if match:
            pmc_id = match.group(1).upper()
        else:
            pmc_id = None

        # doc_key is required for HTML input
        if not args.doc_key:
            sys.exit("Error: --doc-key required when using --html")
        doc_key = args.doc_key
        temp_html = False

    # Connect to database
    print(f"\nConnecting to database '{args.dbname}'...")
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        # Check if already exists
        exists, source_id = check_review_exists(cur, doc_key)
        if exists and not args.force:
            print(f"\n✓ Review {doc_key} already exists in database (source_id={source_id})")
            print(f"  Use --force to reload")
            cur.close()
            conn.close()
            if temp_html and html_path.exists():
                html_path.unlink()
            return

        if exists and args.force:
            print(f"\nReview {doc_key} exists (source_id={source_id}), reloading (--force)...")
            deleted_chunks, deleted_citations = clear_review_data(cur, source_id)
            print(f"  Cleared {deleted_chunks} chunks, {deleted_citations} citations")

        # Extract chunks and citations
        print(f"\nExtracting chunks and citations from HTML...")
        print(f"  Admin filtering: {'enabled' if not args.no_filter_admin else 'disabled'}")
        chunks, reference_index, html_metadata = extract_chunks_and_citations(
            html_path,
            filter_admin=not args.no_filter_admin
        )
        print(f"  Extracted {len(chunks)} chunks")
        print(f"  Extracted {len(reference_index)} citations")

        # Build metadata (CLI args override HTML extraction)
        metadata = {
            "title": args.title or html_metadata.get("title"),
            "authors": args.authors or html_metadata.get("authors"),
            "journal": html_metadata.get("journal"),
            "year": html_metadata.get("year"),
            "doi": html_metadata.get("doi"),
            "pubmed_id": html_metadata.get("pubmed_id"),
            "pmc_id": pmc_id,
            "domain": args.domain,
            "open_access": True,
            "html_path": str(html_path) if not temp_html else None,
        }

        # Show metadata
        if metadata.get("title"):
            print(f"  Title: {metadata['title'][:80]}")
        if metadata.get("authors"):
            print(f"  Authors: {metadata['authors'][:60]}")
        if metadata.get("journal"):
            print(f"  Journal: {metadata['journal']}")
        if metadata.get("year"):
            print(f"  Year: {metadata['year']}")

        # Embed chunks (unless --no-embed)
        if not args.no_embed:
            print(f"\nGenerating embeddings...")
            total_tokens = sum(estimate_tokens(c["full_text"]) for c in chunks)
            cost = (total_tokens / 1_000_000) * 0.02
            print(f"  Est. tokens: ~{total_tokens:,}  Cost: ~${cost:.4f}")

            chunks = embed_chunks(chunks)
            actual_tokens = sum(c.get("tokens_used", 0) for c in chunks)
            print(f"  Actual tokens: {actual_tokens:,}")
        else:
            print(f"\nSkipping embeddings (--no-embed)")

        # Upsert review source
        source_id = upsert_review_source(cur, doc_key, metadata)
        print(f"\nReview source upserted: source_id={source_id}")

        # Load citations
        print(f"Loading {len(reference_index)} citations...")
        ref_id_to_db_id = load_citations(cur, source_id, reference_index)
        print(f"  Citations loaded")

        # Insert chunks
        print(f"Loading {len(chunks)} chunks into database...")
        inserted = insert_review_chunks(cur, source_id, chunks, ref_id_to_db_id)
        print(f"  Inserted {inserted} chunks")

        conn.commit()

        # Export citations
        citations_file = args.citations_output or f"{doc_key}_references.json"
        if not Path(citations_file).is_absolute():
            citations_file = script_dir / citations_file

        # Filter for PMC only if requested
        if args.pmc_only:
            export_refs = {k: v for k, v in reference_index.items() if v.get("pmc_id")}
        else:
            export_refs = reference_index

        with open(citations_file, "w", encoding="utf-8") as f:
            json.dump(export_refs, f, indent=2, ensure_ascii=False)

        pmc_count = sum(1 for ref in reference_index.values() if ref.get("pmc_id"))
        print(f"\nCitations exported to {citations_file}")
        print(f"  Total citations: {len(reference_index)}")
        print(f"  With PMC IDs: {pmc_count}")
        if args.pmc_only:
            print(f"  Exported (PMC only): {len(export_refs)}")

        # Summary
        print(f"\n✓ Successfully added review {doc_key} to database")
        print(f"  source_id: {source_id}")
        print(f"  domain: {args.domain}")
        print(f"  chunks: {inserted}")
        with_emb = sum(1 for c in chunks if c.get("embedding"))
        print(f"  with embeddings: {with_emb}")
        print(f"  citations: {len(reference_index)}")

        # Suggest next step
        if pmc_count > 0:
            print(f"\nNext step - download cited papers:")
            print(f"  python download_pmc_from_file.py --input {citations_file.name} \\")
            print(f"    --outdir html/{args.domain}")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()
        if temp_html and html_path.exists():
            html_path.unlink()


if __name__ == "__main__":
    main()
