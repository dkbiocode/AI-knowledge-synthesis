#!/usr/bin/env python3
"""
Fetch abstract and keywords from PubMed using NCBI E-utilities API.

Usage:
    # Fetch and print metadata for a single PMID
    python fetch_pubmed_metadata.py --pmid 27704003

    # Update database for specific papers
    python fetch_pubmed_metadata.py --update --paper-ids 2,4,5

    # Update all papers missing abstracts
    python fetch_pubmed_metadata.py --update-missing

    # Batch update all papers (with rate limiting)
    python fetch_pubmed_metadata.py --update-all --delay 0.4

Requirements:
    - requests library
    - PostgreSQL database connection
"""

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import psycopg2
import requests


def fetch_pubmed_xml(pmid: str, email: str = "your_email@example.com") -> Optional[str]:
    """
    Fetch XML record from PubMed E-utilities.

    Args:
        pmid: PubMed ID
        email: Email for NCBI (polite usage, not required but recommended)

    Returns:
        XML string or None if error
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
        "rettype": "abstract",
        "email": email,
    }

    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching PMID {pmid}: {e}", file=sys.stderr)
        return None


def parse_pubmed_xml(xml_text: str) -> Dict[str, any]:
    """
    Parse PubMed XML to extract abstract and keywords.

    Returns:
        {
            'abstract': str or None,
            'mesh_terms': list of str,
            'author_keywords': list of str,
            'publication_types': list of str
        }
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"Error parsing XML: {e}", file=sys.stderr)
        return {
            "abstract": None,
            "mesh_terms": [],
            "author_keywords": [],
            "publication_types": [],
        }

    # Extract abstract
    abstract_parts = []
    abstract_elem = root.find(".//Abstract")
    if abstract_elem is not None:
        for abstract_text in abstract_elem.findall(".//AbstractText"):
            # Handle structured abstracts with labels
            label = abstract_text.get("Label", "")
            text = "".join(abstract_text.itertext()).strip()
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)

    abstract = "\n\n".join(abstract_parts) if abstract_parts else None

    # Extract MeSH terms
    mesh_terms = []
    mesh_list = root.find(".//MeshHeadingList")
    if mesh_list is not None:
        for mesh_heading in mesh_list.findall(".//MeshHeading"):
            descriptor = mesh_heading.find("DescriptorName")
            if descriptor is not None:
                mesh_terms.append(descriptor.text)

    # Extract author keywords
    author_keywords = []
    keyword_list = root.find(".//KeywordList")
    if keyword_list is not None:
        for keyword in keyword_list.findall(".//Keyword"):
            if keyword.text:
                author_keywords.append(keyword.text)

    # Extract publication types (bonus - useful for filtering reviews, etc.)
    publication_types = []
    pub_type_list = root.findall(".//PublicationType")
    for pub_type in pub_type_list:
        if pub_type.text:
            publication_types.append(pub_type.text)

    return {
        "abstract": abstract,
        "mesh_terms": mesh_terms,
        "author_keywords": author_keywords,
        "publication_types": publication_types,
    }


def fetch_metadata(pmid: str, email: str = "your_email@example.com") -> Optional[Dict]:
    """
    Fetch and parse metadata for a single PMID.

    Returns:
        Dictionary with metadata or None if error
    """
    xml_text = fetch_pubmed_xml(pmid, email)
    if xml_text is None:
        return None

    return parse_pubmed_xml(xml_text)


def update_paper_metadata(
    conn: psycopg2.extensions.connection,
    paper_id: int,
    pmid: str,
    email: str = "your_email@example.com",
) -> bool:
    """
    Fetch metadata from PubMed and update papers table.

    Returns:
        True if successful, False otherwise
    """
    metadata = fetch_metadata(pmid, email)
    if metadata is None:
        return False

    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE papers
            SET abstract = %s,
                mesh_terms = %s,
                author_keywords = %s
            WHERE id = %s
            """,
            (
                metadata["abstract"],
                metadata["mesh_terms"],
                metadata["author_keywords"],
                paper_id,
            ),
        )
        conn.commit()
        return True
    except psycopg2.Error as e:
        print(f"Database error for paper {paper_id}: {e}", file=sys.stderr)
        conn.rollback()
        return False
    finally:
        cur.close()


def get_db_connection() -> psycopg2.extensions.connection:
    """Connect to PostgreSQL database."""
    return psycopg2.connect(
        dbname="mngs_kb",
        user="david",
        host="localhost",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fetch abstract and keywords from PubMed"
    )
    parser.add_argument("--pmid", help="Single PMID to fetch")
    parser.add_argument(
        "--update", action="store_true", help="Update database (requires --paper-ids)"
    )
    parser.add_argument(
        "--paper-ids",
        help="Comma-separated paper IDs to update (e.g., '2,4,5')",
    )
    parser.add_argument(
        "--update-missing",
        action="store_true",
        help="Update all papers with NULL abstracts",
    )
    parser.add_argument(
        "--update-all", action="store_true", help="Update all papers"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Delay between requests in seconds (default: 0.4, max 3 req/sec per NCBI policy)",
    )
    parser.add_argument(
        "--email",
        default="your_email@example.com",
        help="Email for NCBI API (polite usage)",
    )
    parser.add_argument(
        "--limit", type=int, help="Limit number of papers to update (for testing)"
    )

    args = parser.parse_args()

    # Mode 1: Just fetch and print metadata
    if args.pmid and not args.update:
        print(f"Fetching metadata for PMID: {args.pmid}")
        metadata = fetch_metadata(args.pmid, args.email)
        if metadata:
            print(json.dumps(metadata, indent=2))
        else:
            print("Failed to fetch metadata", file=sys.stderr)
            sys.exit(1)
        return

    # Mode 2: Update database
    if args.update or args.update_missing or args.update_all:
        conn = get_db_connection()
        cur = conn.cursor()

        # Determine which papers to update
        if args.paper_ids:
            paper_ids = [int(x.strip()) for x in args.paper_ids.split(",")]
            cur.execute(
                "SELECT id, pubmed_id FROM papers WHERE id = ANY(%s) ORDER BY id",
                (paper_ids,),
            )
        elif args.update_missing:
            cur.execute(
                "SELECT id, pubmed_id FROM papers WHERE abstract IS NULL AND pubmed_id IS NOT NULL ORDER BY id"
            )
        elif args.update_all:
            cur.execute(
                "SELECT id, pubmed_id FROM papers WHERE pubmed_id IS NOT NULL ORDER BY id"
            )
        else:
            print("Error: Must specify --paper-ids, --update-missing, or --update-all")
            sys.exit(1)

        papers = cur.fetchall()
        cur.close()

        if args.limit:
            papers = papers[: args.limit]

        print(f"Updating {len(papers)} papers...")

        success_count = 0
        fail_count = 0

        for i, (paper_id, pmid) in enumerate(papers, 1):
            print(f"[{i}/{len(papers)}] Processing paper ID {paper_id} (PMID: {pmid})...", end=" ")

            if update_paper_metadata(conn, paper_id, pmid, args.email):
                print("✓")
                success_count += 1
            else:
                print("✗")
                fail_count += 1

            # Rate limiting (NCBI allows 3 requests/second without API key)
            if i < len(papers):
                time.sleep(args.delay)

        conn.close()

        print(f"\nResults: {success_count} successful, {fail_count} failed")
        return

    # No valid mode specified
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
