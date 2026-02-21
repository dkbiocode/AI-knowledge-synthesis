"""
chunk_article.py

Parse main-article-body.html into section-based chunks, with full citation
metadata embedded in each chunk. Saves chunks.json.

Each chunk includes a `citations` list — every reference cited in that section,
with ref_id, cite_key, DOI, PubMed ID, PMC ID, title, authors, year, journal,
and open_access flag. This allows direct two-hop retrieval when the cited papers
are later added to the knowledge base.

Usage:
  python chunk_article.py
  python chunk_article.py --input other.html --output my_chunks.json
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup, NavigableString, Tag


# ---------------------------------------------------------------------------
# HTML → clean text helpers
# ---------------------------------------------------------------------------

def table_to_text(table_tag: Tag) -> str:
    """Convert an HTML table to a compact readable representation."""
    rows = []
    for tr in table_tag.find_all("tr"):
        cells = [cell.get_text(separator=" ", strip=True)
                 for cell in tr.find_all(["th", "td"])]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def figure_to_text(fig_tag: Tag) -> str:
    """Extract figure caption text."""
    caption = fig_tag.find("figcaption")
    if caption:
        return "[Figure: " + caption.get_text(separator=" ", strip=True) + "]"
    return ""


def element_to_text(element: Tag) -> str:
    """
    Recursively convert a BeautifulSoup element to clean plain text.
    Tables and figures get special handling; everything else uses get_text().
    """
    parts = []
    for child in element.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name == "table":
                parts.append(table_to_text(child))
            elif child.name == "figure":
                parts.append(figure_to_text(child))
            elif child.name in ("script", "style", "img"):
                pass
            else:
                parts.append(element_to_text(child))
    text = " ".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_text(text: str) -> str:
    """Normalise whitespace and strip stray Unicode artifacts."""
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Reference list parser
# ---------------------------------------------------------------------------

def parse_reference_list(soup: BeautifulSoup) -> dict[str, dict]:
    """
    Parse all <li id="B..."> reference entries.

    Returns a dict keyed by ref_id (e.g. "B45") with:
      {
        "ref_id"     : "B45",
        "cite_text"  : "Gu et al., 2019",   # raw <cite> text, cleaned
        "doi"        : "https://doi.org/...",
        "pubmed_id"  : "12345678",
        "pmc_id"     : "PMC1234567",
        "title"      : "...",    # from Google Scholar URL param
        "authors"    : "...",    # from Google Scholar URL param
        "year"       : "2019",   # from Google Scholar URL param
        "journal"    : "...",    # from Google Scholar URL param
        "open_access": bool,     # true if PMC free article link present
      }
    """
    refs = {}

    ref_section = soup.find("ol", class_="ref-list")
    if ref_section is None:
        return refs

    for li in ref_section.find_all("li", id=re.compile(r"^B\d+")):
        ref_id = li["id"]
        entry: dict = {"ref_id": ref_id}

        # --- Cite text (authors + year shortform) ---
        cite_tag = li.find("cite")
        entry["cite_text"] = clean_text(cite_tag.get_text()) if cite_tag else ""

        # --- DOI ---
        doi_link = li.find("a", href=re.compile(r"https://doi\.org/"))
        entry["doi"] = doi_link["href"] if doi_link else None

        # --- PubMed ID ---
        pm_link = li.find("a", href=re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov"))
        if pm_link:
            pm_href = pm_link["href"]
            entry["pubmed_id"] = pm_href.rstrip("/").split("/")[-1]
        else:
            entry["pubmed_id"] = None

        # --- PMC ID + open_access flag ---
        pmc_link = li.find("a", string=re.compile(r"PMC free article", re.I))
        if pmc_link:
            pmc_href = pmc_link.get("href", "")
            # href is like /articles/PMC6764751/
            m = re.search(r"(PMC\d+)", pmc_href)
            entry["pmc_id"] = m.group(1) if m else None
            entry["open_access"] = True
        else:
            entry["pmc_id"] = None
            entry["open_access"] = False

        # --- Title, authors, year, journal from Google Scholar URL params ---
        gs_link = li.find("a", href=re.compile(r"scholar\.google\.com"))
        if gs_link:
            qs = parse_qs(urlparse(gs_link["href"]).query)
            entry["title"]   = qs.get("title", [None])[0]
            entry["journal"] = qs.get("journal", [None])[0]
            entry["year"]    = qs.get("publication_year", [None])[0]
            # authors is a repeated param: author=X&author=Y...
            authors = qs.get("author", [])
            entry["authors"] = "; ".join(authors) if authors else None
        else:
            entry["title"]   = None
            entry["journal"] = None
            entry["year"]    = None
            entry["authors"] = None

        refs[ref_id] = entry

    return refs


# ---------------------------------------------------------------------------
# Inline citation extractor
# ---------------------------------------------------------------------------

def extract_inline_citations(element: Tag) -> list[str]:
    """
    Return a deduplicated ordered list of ref_ids (e.g. ["B45", "B16"])
    cited anywhere within this element (including descendants).
    """
    seen = set()
    ordered = []
    for a in element.find_all("a", href=re.compile(r"^#B\d+")):
        ref_id = a["href"].lstrip("#")
        if ref_id not in seen:
            seen.add(ref_id)
            ordered.append(ref_id)
    return ordered


# ---------------------------------------------------------------------------
# Section extractor
# ---------------------------------------------------------------------------

def extract_sections(html_path: str) -> tuple[list[dict], dict[str, dict]]:
    """
    Walk the HTML section tree and return:
      - flat list of chunk dicts
      - reference lookup dict (ref_id → metadata)

    Each chunk dict:
      {
        "section_id"    : e.g. "s3_2",
        "heading"       : e.g. "3.2. Limitations of mNGS...",
        "parent_heading": parent section heading or None,
        "level"         : 1 (h2) or 2 (h3),
        "text"          : clean plain text (excl. sub-sections),
        "full_text"     : heading + text (ready to embed),
        "char_count"    : int,
        "token_estimate": int,
        "citations"     : [
            {
              "ref_id"     : "B45",
              "cite_key"   : "Gu et al., 2019",
              "doi"        : "https://doi.org/...",
              "pubmed_id"  : "...",
              "pmc_id"     : "PMC...",
              "title"      : "...",
              "authors"    : "...",
              "year"       : "2019",
              "journal"    : "...",
              "open_access": bool,
            },
            ...
        ],
      }
    """
    with open(html_path, encoding="utf-8") as fh:
        soup = BeautifulSoup(fh, "html.parser")

    ref_lookup = parse_reference_list(soup)
    chunks = []

    def get_heading(section: Tag) -> tuple[str, int]:
        h = section.find(["h2", "h3"], recursive=False)
        if h is None:
            h = section.find(["h2", "h3"])
        if h is None:
            return ("", 0)
        level = int(h.name[1])
        return (clean_text(h.get_text(separator=" ")), level)

    def section_own_content(section: Tag) -> tuple[str, list[str]]:
        """
        Returns (clean_text, [ref_ids]) for the direct content of this section,
        excluding child <section> elements.
        """
        parts = []
        ref_ids = []
        seen_refs = set()

        for child in section.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name == "section":
                    continue
                if child.name in ["h2", "h3"]:
                    continue
                if child.name == "table":
                    parts.append(table_to_text(child))
                elif child.name == "figure":
                    parts.append(figure_to_text(child))
                elif child.name not in ("script", "style"):
                    parts.append(element_to_text(child))

                # Collect citations from this child element
                for ref_id in extract_inline_citations(child):
                    if ref_id not in seen_refs:
                        seen_refs.add(ref_id)
                        ref_ids.append(ref_id)

        return clean_text(" ".join(parts)), ref_ids

    def build_citation_list(ref_ids: list[str]) -> list[dict]:
        """Resolve ref_ids to full citation metadata dicts."""
        citations = []
        for ref_id in ref_ids:
            if ref_id in ref_lookup:
                r = ref_lookup[ref_id]
                citations.append({
                    "ref_id":      ref_id,
                    "cite_key":    r.get("cite_text", ""),
                    "doi":         r.get("doi"),
                    "pubmed_id":   r.get("pubmed_id"),
                    "pmc_id":      r.get("pmc_id"),
                    "title":       r.get("title"),
                    "authors":     r.get("authors"),
                    "year":        r.get("year"),
                    "journal":     r.get("journal"),
                    "open_access": r.get("open_access", False),
                })
            else:
                citations.append({"ref_id": ref_id, "cite_key": ref_id})
        return citations

    def walk(section: Tag, parent_heading: str | None = None):
        heading, level = get_heading(section)
        if not heading:
            for child in section.find_all("section", recursive=False):
                walk(child, parent_heading)
            return

        own_text, ref_ids = section_own_content(section)

        if own_text or level <= 1:
            full_text = f"{heading}\n\n{own_text}".strip()
            citations = build_citation_list(ref_ids)
            chunks.append({
                "section_id":     section.get("id", ""),
                "heading":        heading,
                "parent_heading": parent_heading,
                "level":          level,
                "text":           own_text,
                "full_text":      full_text,
                "char_count":     len(full_text),
                "token_estimate": max(1, len(full_text) // 4),
                "citations":      citations,
            })

        for child in section.find_all("section", recursive=False):
            walk(child, parent_heading=heading)

    body = soup.find("section", class_="main-article-body")
    if body is None:
        body = soup

    for top_section in body.find_all("section", recursive=False):
        walk(top_section, parent_heading=None)

    return chunks, ref_lookup


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="main-article-body.html",
                        help="Path to HTML file (default: main-article-body.html)")
    parser.add_argument("--output", default="chunks.json",
                        help="Output chunks JSON file (default: chunks.json)")
    parser.add_argument("--refs-output", default="reference_index.json",
                        help="Output reference index JSON file (default: reference_index.json)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = args.input if os.path.isabs(args.input) \
        else os.path.join(".", args.input)

    if not os.path.exists(html_path):
        sys.exit(f"Input file not found: {html_path}")

    print(f"Parsing {html_path} ...")
    chunks, ref_lookup = extract_sections(html_path)

    # Summary table
    print(f"\n{'ID':<12} {'Lvl':<5} {'~Tok':<7} {'Cites':<7} Heading")
    print("-" * 85)
    total_tokens = 0
    for c in chunks:
        total_tokens += c["token_estimate"]
        print(f"{c['section_id']:<12} {c['level']:<5} {c['token_estimate']:<7} "
              f"{len(c['citations']):<7} {c['heading'][:50]}")

    print(f"\nTotal chunks     : {len(chunks)}")
    print(f"Total ~tokens    : {total_tokens:,}")
    print(f"References parsed: {len(ref_lookup)}")

    # Save chunks
    out_path = args.output if os.path.isabs(args.output) \
        else os.path.join(".", args.output)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(chunks, fh, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(chunks)} chunks → {out_path}")

    # Save reference index (useful for building cited_papers records later)
    refs_path = args.refs_output if os.path.isabs(args.refs_output) \
        else os.path.join(script_dir, args.refs_output)
    # Add cited_in back-links to the reference index
    for ref_id, ref in ref_lookup.items():
        ref["cited_in"] = []
    for c in chunks:
        for cit in c["citations"]:
            rid = cit["ref_id"]
            if rid in ref_lookup:
                ref_lookup[rid]["cited_in"].append({
                    "section_id": c["section_id"],
                    "heading":    c["heading"],
                })
    with open(refs_path, "w", encoding="utf-8") as fh:
        json.dump(ref_lookup, fh, indent=2, ensure_ascii=False)
    print(f"Saved reference index ({len(ref_lookup)} entries) → {refs_path}")


if __name__ == "__main__":
    main()
