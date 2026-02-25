"""
add_pmc_article.py

Add a single PMC article to the database with a streamlined workflow:
  1. Download from PMC (if PMCID provided) or use existing HTML file
  2. Extract chunks with admin filtering
  3. Generate embeddings
  4. Load into database

Checks for duplicates and skips if article already exists.

Usage:
  # Add by PMCID (downloads automatically)
  python add_pmc_article.py --pmcid PMC2581791 --domain medical

  # Add from existing HTML file
  python add_pmc_article.py --html html/article.html --domain veterinary

  # Skip embedding generation (chunks only)
  python add_pmc_article.py --pmcid PMC2581791 --domain medical --no-embed

  # Force reload even if exists
  python add_pmc_article.py --pmcid PMC2581791 --domain medical --force
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
from psycopg2.extras import execute_values

# Import PubMed metadata fetcher
sys.path.insert(0, str(Path(__file__).parent.parent / "utilities"))
from fetch_pubmed_metadata import fetch_metadata


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


def check_paper_exists(cur, pmc_id: str) -> tuple[bool, int | None]:
    """Check if a paper with this PMC ID already exists. Returns (exists, paper_id)."""
    cur.execute("SELECT id FROM papers WHERE pmc_id = %s", (pmc_id,))
    row = cur.fetchone()
    if row:
        return True, row[0]
    return False, None


def upsert_paper(cur, pmc_id: str, metadata: dict, domain: str) -> int:
    """
    Insert or update a papers row.
    Returns papers.id.
    """
    doi = metadata.get("doi") or None

    if doi:
        # Use DOI as unique key
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
            doi,
            metadata.get("pubmed_id"),
            pmc_id,
            metadata.get("title"),
            metadata.get("authors"),
            metadata.get("journal"),
            metadata.get("year"),
            metadata.get("open_access", True),
            domain,
        ))
        row = cur.fetchone()
        if row:
            return row[0]
        # Fetch existing row if no update
        cur.execute("SELECT id FROM papers WHERE doi = %s", (doi,))
        return cur.fetchone()[0]
    else:
        # Use PMC ID as unique key
        cur.execute("SELECT id FROM papers WHERE pmc_id = %s", (pmc_id,))
        row = cur.fetchone()
        if row:
            paper_id = row[0]
            # Update metadata
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
                metadata.get("pubmed_id"),
                metadata.get("title"),
                metadata.get("authors"),
                metadata.get("journal"),
                metadata.get("year"),
                metadata.get("open_access", True),
                domain,
                paper_id,
            ))
            return paper_id

        # Insert new
        cur.execute("""
            INSERT INTO papers
                (doi, pubmed_id, pmc_id, title, authors, journal, year, open_access, domain)
            VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            metadata.get("pubmed_id"),
            pmc_id,
            metadata.get("title"),
            metadata.get("authors"),
            metadata.get("journal"),
            metadata.get("year"),
            metadata.get("open_access", True),
            domain,
        ))
        return cur.fetchone()[0]


def clear_paper_chunks(cur, paper_id: int):
    """Delete existing paper_chunks for this paper."""
    cur.execute("DELETE FROM paper_chunks WHERE paper_id = %s", (paper_id,))
    return cur.rowcount


def update_pubmed_metadata(cur, paper_id: int, pubmed_id: str) -> bool:
    """
    Fetch abstract and keywords from PubMed and update paper.
    Returns True if successful, False otherwise.
    """
    if not pubmed_id:
        return False

    print(f"\nFetching metadata from PubMed (PMID: {pubmed_id})...")
    try:
        metadata = fetch_metadata(pubmed_id)
        if metadata:
            cur.execute("""
                UPDATE papers
                SET abstract = %s,
                    mesh_terms = %s,
                    author_keywords = %s
                WHERE id = %s
            """, (
                metadata['abstract'],
                metadata['mesh_terms'],
                metadata['author_keywords'],
                paper_id,
            ))
            print(f"  ✓ Abstract: {'Yes' if metadata['abstract'] else 'No'}")
            print(f"  ✓ MeSH terms: {len(metadata['mesh_terms'])}")
            print(f"  ✓ Author keywords: {len(metadata['author_keywords'])}")
            return True
        else:
            print(f"  ✗ Failed to fetch metadata")
            return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def insert_paper_chunks(cur, paper_id: int, chunks: list[dict]) -> int:
    """Insert paper_chunks rows. Returns count inserted."""
    inserted = 0
    for chunk in chunks:
        emb = chunk.get("embedding")
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
        inserted += 1
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
# Extract chunks
# ---------------------------------------------------------------------------

def extract_chunks_from_html(html_path: Path, filter_admin: bool = True) -> tuple[list[dict], dict]:
    """
    Extract chunks from PMC HTML.
    Returns (chunks, metadata).
    """
    try:
        from src.extractors import PMCExtractor
    except ImportError:
        sys.exit("extractors package not found. Check your installation.")

    extractor = PMCExtractor(str(html_path), filter_admin=filter_admin)
    chunks, refs = extractor.extract_all()

    # Extract metadata from HTML
    metadata = {}
    soup = extractor.soup

    # Try to get title
    title_tag = soup.find("h1", class_="content-title")
    if title_tag:
        metadata["title"] = title_tag.get_text(strip=True)

    # Try to get authors (simplified)
    contrib_group = soup.find("div", class_="contrib-group")
    if contrib_group:
        authors = [a.get_text(strip=True) for a in contrib_group.find_all("a", class_="name")]
        if authors:
            metadata["authors"] = ", ".join(authors[:3])  # First 3 authors
            if len(authors) > 3:
                metadata["authors"] += " et al."

    # Try to get journal and year from citation meta
    journal_tag = soup.find("meta", {"name": "citation_journal_title"})
    if journal_tag:
        metadata["journal"] = journal_tag.get("content")

    year_tag = soup.find("meta", {"name": "citation_publication_date"})
    if year_tag:
        year_str = year_tag.get("content", "").split("/")[0]  # YYYY/MM/DD format
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

    return chunks, metadata


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

        # Truncate if over limit
        TOKEN_LIMIT = 8191
        if tokens > TOKEN_LIMIT:
            text = text[: TOKEN_LIMIT * 4]
            print(f"    [warn] chunk '{chunk['heading'][:50]}' truncated to ~{TOKEN_LIMIT} tokens")

        print(f"    [{i+1}/{len(chunks)}] Embedding ~{tokens} tokens  {chunk['heading'][:55]}")

        response = client.embeddings.create(input=text, model=model, dimensions=1536)

        chunk["embedding"] = response.data[0].embedding
        chunk["embedding_model"] = model
        chunk["tokens_used"] = response.usage.total_tokens

        # Brief pause to stay within rate limits
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
        help="PMC ID to download and process (e.g., PMC2581791)",
    )
    parser.add_argument(
        "--html",
        help="Path to existing PMC HTML file",
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
        "--no-embed", action="store_true",
        help="Skip embedding generation (chunks only)",
    )
    parser.add_argument(
        "--no-filter-admin", action="store_true",
        help="Don't filter administrative sections",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force reload even if article already exists",
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

        # Download to temp or permanent location
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
            sys.exit("Error: Could not extract PMC ID from filename. "
                     "Please use format containing PMC ID (e.g., PMC2581791.html)")
        temp_html = False

    # Connect to database
    print(f"\nConnecting to database '{args.dbname}'...")
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        # Check if already exists
        exists, paper_id = check_paper_exists(cur, pmc_id)
        if exists and not args.force:
            print(f"\n✓ Article {pmc_id} already exists in database (paper_id={paper_id})")
            print(f"  Use --force to reload")
            cur.close()
            conn.close()
            if temp_html and html_path.exists():
                html_path.unlink()
            return

        if exists and args.force:
            print(f"\nArticle {pmc_id} exists (paper_id={paper_id}), reloading (--force)...")
            deleted = clear_paper_chunks(cur, paper_id)
            if deleted:
                print(f"  Cleared {deleted} existing chunks")

        # Extract chunks
        print(f"\nExtracting chunks from HTML...")
        print(f"  Admin filtering: {'enabled' if not args.no_filter_admin else 'disabled'}")
        chunks, metadata = extract_chunks_from_html(
            html_path,
            filter_admin=not args.no_filter_admin
        )
        print(f"  Extracted {len(chunks)} chunks")

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
            cost = (total_tokens / 1_000_000) * 0.02  # text-embedding-3-small
            print(f"  Est. tokens: ~{total_tokens:,}  Cost: ~${cost:.4f}")

            chunks = embed_chunks(chunks)
            actual_tokens = sum(c.get("tokens_used", 0) for c in chunks)
            print(f"  Actual tokens: {actual_tokens:,}")
        else:
            print(f"\nSkipping embeddings (--no-embed)")

        # Upsert paper
        paper_id = upsert_paper(cur, pmc_id, metadata, args.domain)
        print(f"\nPaper upserted: paper_id={paper_id}")

        # Fetch and update PubMed metadata (abstract, keywords)
        if metadata.get("pubmed_id"):
            update_pubmed_metadata(cur, paper_id, metadata["pubmed_id"])

        # Insert chunks
        print(f"Loading {len(chunks)} chunks into database...")
        inserted = insert_paper_chunks(cur, paper_id, chunks)
        print(f"  Inserted {inserted} chunks")

        conn.commit()

        # Summary
        print(f"\n✓ Successfully added {pmc_id} to database")
        print(f"  paper_id: {paper_id}")
        print(f"  domain: {args.domain}")
        print(f"  chunks: {inserted}")
        with_emb = sum(1 for c in chunks if c.get("embedding"))
        print(f"  with embeddings: {with_emb}")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()
        # Clean up temp file
        if temp_html and html_path.exists():
            html_path.unlink()


if __name__ == "__main__":
    main()
