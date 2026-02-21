"""
extractors/pmc.py

PubMed Central (PMC) HTML extractor.

Parses PMC full-text HTML articles into section-based chunks with embedded
citation metadata. PMC HTML uses <section> tags for structure and <xref>
links for citations.

Usage:
    from extractors import PMCExtractor

    extractor = PMCExtractor("html/B32_PMC7031966.html")
    chunks, refs = extractor.extract_all()
"""

import re
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup, NavigableString, Tag

from .base import BaseExtractor


class PMCExtractor(BaseExtractor):
    """Extract chunks and references from PubMed Central HTML."""

    def __init__(self, source_path, filter_admin=False):
        super().__init__(source_path)
        self._soup = None
        self._ref_lookup = None
        self._filter_admin = filter_admin
        self._admin_filter_fn = None

        # Load admin filter if requested
        if self._filter_admin:
            try:
                from admin_blacklist import is_admin_section
                self._admin_filter_fn = is_admin_section
            except ImportError:
                print("Warning: admin_blacklist.py not found, admin filtering disabled")
                self._filter_admin = False

    @property
    def soup(self) -> BeautifulSoup:
        """Lazy-load and cache the parsed BeautifulSoup tree."""
        if self._soup is None:
            with open(self.source_path, encoding="utf-8") as fh:
                self._soup = BeautifulSoup(fh, "html.parser")
        return self._soup

    # -----------------------------------------------------------------------
    # HTML → clean text helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _table_to_text(table_tag: Tag) -> str:
        """Convert an HTML table to a compact readable representation."""
        rows = []
        for tr in table_tag.find_all("tr"):
            cells = [cell.get_text(separator=" ", strip=True)
                     for cell in tr.find_all(["th", "td"])]
            rows.append(" | ".join(cells))
        return "\n".join(rows)

    @staticmethod
    def _figure_to_text(fig_tag: Tag) -> str:
        """Extract figure caption text."""
        caption = fig_tag.find("figcaption")
        if caption:
            return "[Figure: " + caption.get_text(separator=" ", strip=True) + "]"
        return ""

    @classmethod
    def _element_to_text(cls, element: Tag) -> str:
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
                    parts.append(cls._table_to_text(child))
                elif child.name == "figure":
                    parts.append(cls._figure_to_text(child))
                elif child.name in ("script", "style", "img"):
                    pass
                else:
                    parts.append(cls._element_to_text(child))
        text = " ".join(parts)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalise whitespace and strip stray Unicode artifacts."""
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # -----------------------------------------------------------------------
    # Reference list parser
    # -----------------------------------------------------------------------

    def extract_refs(self) -> dict[str, dict]:
        """
        Parse all <li id="B..."> or <li id="R..."> reference entries.

        Returns a dict keyed by ref_id (e.g. "B45" or "R1") with full citation metadata.
        """
        if self._ref_lookup is not None:
            return self._ref_lookup

        refs = {}
        # PMC uses either <ol> or <ul> with class="ref-list"
        ref_list = self.soup.find(["ol", "ul"], class_="ref-list")
        if ref_list is None:
            self._ref_lookup = refs
            return refs

        # Ref IDs can be B1, B2, ... or R1, R2, ... depending on PMC template
        for li in ref_list.find_all("li", id=re.compile(r"^[BR]\d+")):
            ref_id = li["id"]
            entry: dict = {"ref_id": ref_id}

            # --- Cite text (authors + year shortform) ---
            cite_tag = li.find("cite")
            entry["cite_text"] = self._clean_text(cite_tag.get_text()) if cite_tag else ""

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

        self._ref_lookup = refs
        return refs

    # -----------------------------------------------------------------------
    # Inline citation extractor
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_inline_citations(element: Tag) -> list[str]:
        """
        Return a deduplicated ordered list of ref_ids (e.g. ["B45", "R16"])
        cited anywhere within this element (including descendants).
        """
        seen = set()
        ordered = []
        for a in element.find_all("a", href=re.compile(r"^#[BR]\d+")):
            ref_id = a["href"].lstrip("#")
            if ref_id not in seen:
                seen.add(ref_id)
                ordered.append(ref_id)
        return ordered

    # -----------------------------------------------------------------------
    # Section extractor
    # -----------------------------------------------------------------------

    def chunk(self) -> list[dict]:
        """
        Walk the HTML section tree and return a flat list of chunk dicts.

        Each chunk has: section_id, heading, parent_heading, level, text,
        full_text, char_count, token_estimate, citations.
        """
        # Ensure refs are parsed first (needed for build_citation_list)
        if self._ref_lookup is None:
            self.extract_refs()

        chunks = []

        def get_heading(section: Tag) -> tuple[str, int]:
            h = section.find(["h2", "h3"], recursive=False)
            if h is None:
                h = section.find(["h2", "h3"])
            if h is None:
                return ("", 0)
            level = int(h.name[1])
            return (self._clean_text(h.get_text(separator=" ")), level)

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
                        parts.append(self._table_to_text(child))
                    elif child.name == "figure":
                        parts.append(self._figure_to_text(child))
                    elif child.name not in ("script", "style"):
                        parts.append(self._element_to_text(child))

                    # Collect citations from this child element
                    for ref_id in self._extract_inline_citations(child):
                        if ref_id not in seen_refs:
                            seen_refs.add(ref_id)
                            ref_ids.append(ref_id)

            return self._clean_text(" ".join(parts)), ref_ids

        def build_citation_list(ref_ids: list[str]) -> list[dict]:
            """Resolve ref_ids to full citation metadata dicts."""
            citations = []
            for ref_id in ref_ids:
                if ref_id in self._ref_lookup:
                    r = self._ref_lookup[ref_id]
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

            # Skip administrative sections if filtering is enabled
            if self._filter_admin and self._admin_filter_fn and self._admin_filter_fn(heading):
                # Still recurse into children in case they're not administrative
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

        body = self.soup.find("section", class_="main-article-body")
        if body is None:
            body = self.soup

        for top_section in body.find_all("section", recursive=False):
            walk(top_section, parent_heading=None)

        return chunks

    # -----------------------------------------------------------------------
    # HTML fragment extraction (for web UI display)
    # -----------------------------------------------------------------------

    def html_fragment(self, section_id: str) -> str | None:
        """
        Return the raw HTML content of the section with the given section_id,
        preserving <a>, <sup>, <em>, etc. for display in a web UI.

        Returns None if the section is not found.
        """
        section = self.soup.find("section", id=section_id)
        if section is None:
            return None

        # Clone the section and remove nested <section> tags (we only want
        # the direct content, not subsections)
        content_parts = []
        for child in section.children:
            if isinstance(child, NavigableString):
                content_parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name not in ["section", "h2", "h3"]:
                    content_parts.append(str(child))

        return "".join(content_parts).strip()
