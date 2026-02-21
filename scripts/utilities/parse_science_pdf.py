"""
parse_science_pdf.py

Specialized parser for Science journal PDFs which have unique characteristics:
- No traditional section headings (continuous text format)
- Title often in image/header (not extractable as text)
- Multi-article PDFs with previous/next article bleed
- DOI-based article boundaries
- Extra author metadata pages appended

Uses DOI from metadata to identify article boundaries and extracts as continuous text.

Installation:
  pip install pymupdf

Usage:
  # Basic parsing
  python parse_science_pdf.py --pdf science.1181498.pdf

  # With output file
  python parse_science_pdf.py --pdf science.1181498.pdf --output article.json

  # Debug mode
  python parse_science_pdf.py --pdf science.1181498.pdf --debug
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF not installed")
    print("Install with: pip install pymupdf")
    sys.exit(1)


class SciencePDFExtractor:
    """Extract article content from Science journal PDFs."""

    def __init__(self, pdf_path: str, debug: bool = False):
        self.pdf_path = Path(pdf_path)
        self.debug = debug
        self.doc = fitz.open(str(self.pdf_path))

    def extract_metadata(self) -> Dict:
        """Extract PDF metadata."""
        meta = self.doc.metadata

        # Extract DOI from multiple sources
        doi = None

        # 1. Try subject field
        subject = meta.get("subject", "")
        if "doi:" in subject.lower():
            match = re.search(r'doi:(10\.\d+/[\w.]+)', subject, re.IGNORECASE)
            if match:
                doi = match.group(1)

        # 2. Try filename (e.g., science.1181498.pdf)
        if not doi:
            filename = self.pdf_path.name
            match = re.search(r'science\.(\d+)', filename, re.IGNORECASE)
            if match:
                doi = f"10.1126/science.{match.group(1)}"

        # 3. Search in PDF text
        if not doi:
            for page_num in range(min(5, len(self.doc))):  # Check first 5 pages
                page = self.doc[page_num]
                text = page.get_text()
                match = re.search(r'10\.1126/science\.\d+', text)
                if match:
                    doi = match.group(0)
                    break

        return {
            "title": meta.get("title", ""),
            "authors": meta.get("author", ""),
            "subject": subject,
            "doi": doi,
            "keywords": meta.get("keywords", ""),
            "creator": meta.get("creator", ""),
            "created": meta.get("creationDate", ""),
            "pages": len(self.doc),
        }

    def find_article_by_doi(self, doi: str = None) -> Tuple[int, int]:
        """
        Find article boundaries using DOI markers.

        Science PDFs often contain multiple articles. The target article's DOI
        appears somewhere in the PDF (usually at the end of the article).

        Returns: (start_page, end_page) indices (0-based)
        """
        if doi is None:
            metadata = self.extract_metadata()
            doi = metadata.get("doi")

        if not doi:
            if self.debug:
                print("Warning: No DOI found in metadata - using fallback detection")
            return self._fallback_boundaries()

        if self.debug:
            print(f"Searching for article with DOI: {doi}")

        # Find all DOIs in the document
        doi_pages = []
        other_dois = set()

        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text()

            # Find all DOIs on this page
            found_dois = re.findall(r'10\.\d+/[\w.]+', text)

            for found_doi in found_dois:
                if found_doi == doi:
                    doi_pages.append(page_num)
                    if self.debug:
                        print(f"  Target DOI found on page {page_num + 1}")
                else:
                    other_dois.add(found_doi)

        if not doi_pages:
            if self.debug:
                print(f"Warning: Target DOI {doi} not found in PDF text")
            return self._fallback_boundaries()

        # The article likely ends on the first page where the target DOI appears
        # (subsequent appearances may be on author metadata pages)
        end_page = min(doi_pages)

        # Start page: Look for where previous article ends (References section)
        # The target article starts after the previous article's References section
        start_page = 0

        # Scan from beginning to find where previous article's References ends
        for page_num in range(min(doi_pages)):  # Only check pages before target DOI
            page = self.doc[page_num]
            text = page.get_text()

            # Check for previous article's DOI
            has_other_doi = any(other_doi in text for other_doi in other_dois)

            if has_other_doi:
                # This page has previous article - look for References section
                refs_match = re.search(
                    r'\b(References and Notes|References|REFERENCES)\b',
                    text
                )
                if refs_match:
                    # Previous article ends here - our article starts on same or next page
                    # Check if there's substantial text after References
                    text_after_refs = text[refs_match.end():]
                    if len(text_after_refs.strip()) > 500:
                        # Substantial content after References - article starts on this page
                        start_page = page_num
                        if self.debug:
                            print(f"  Previous article References on page {page_num + 1}, target article follows")
                    else:
                        # Not much after References - article starts on next page
                        start_page = page_num + 1
                        if self.debug:
                            print(f"  Previous article ends on page {page_num + 1}, target starts on {start_page + 1}")
                    break
            else:
                # No other DOI on this page - could be start of target article
                start_page = page_num
                break

        if self.debug:
            print(f"Article boundaries: pages {start_page + 1} to {end_page + 1}")

        return start_page, end_page

    def _fallback_boundaries(self) -> Tuple[int, int]:
        """
        Fallback boundary detection when DOI is not available.

        Assumes first page is start, and searches for References section as end.
        """
        start_page = 0
        end_page = len(self.doc) - 1

        # Find References section
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text()

            if re.search(r'\b(References and Notes|References|REFERENCES)\b', text):
                end_page = page_num
                if self.debug:
                    print(f"References section found on page {page_num + 1}")
                break

        return start_page, end_page

    def extract_text(self, start_page: int = None, end_page: int = None) -> str:
        """
        Extract article text as continuous block.

        Args:
            start_page: Starting page (0-indexed). If None, auto-detect.
            end_page: Ending page (0-indexed). If None, auto-detect.

        Returns:
            Extracted text as single string
        """
        if start_page is None or end_page is None:
            start_page, end_page = self.find_article_by_doi()

        full_text = []

        for page_num in range(start_page, end_page + 1):
            page = self.doc[page_num]
            text = page.get_text()

            # On first page, skip content from previous article
            if page_num == start_page:
                # Look for previous article's DOI (appears AFTER its References section)
                # Structure: [...references...] "References" [date info] [DOI] [Target article title]

                # Find all DOIs on this page
                doi_matches = list(re.finditer(r'10\.\d+/[\w.]+', text))

                if len(doi_matches) > 1 and self.debug:
                    print(f"Multiple DOIs on page {page_num + 1}: {[m.group(0) for m in doi_matches]}")

                # If we have multiple DOIs, the first one(s) are likely from previous articles
                # Skip content up to and including the first DOI
                if doi_matches:
                    first_doi = doi_matches[0]

                    # Check if this is not our target article's DOI
                    metadata = self.extract_metadata()
                    target_doi = metadata.get('doi', '')

                    if first_doi.group(0) != target_doi:
                        # This is the previous article's DOI - skip everything up to its end
                        text = text[first_doi.end():]
                        if self.debug:
                            print(f"Skipped previous article (DOI: {first_doi.group(0)}) on page {page_num + 1}")
                            print(f"  New start: {text[:100]}...")

            # On last page, stop at References section
            if page_num == end_page:
                refs_match = re.search(
                    r'\b(References and Notes|References|REFERENCES|Literature Cited)\b',
                    text
                )
                if refs_match:
                    text = text[:refs_match.start()]
                    if self.debug:
                        print(f"Stopped at References section on page {page_num + 1}")

            full_text.append(text)

        # Combine pages, preserving paragraph structure
        combined = "\n\n".join(full_text)

        # Remove common headers/footers (do this before normalizing whitespace)
        combined = self._clean_headers_footers(combined)

        # Normalize whitespace within lines but preserve paragraph breaks
        # Replace multiple spaces/tabs with single space
        combined = re.sub(r'[ \t]+', ' ', combined)
        # Clean up lines
        lines = combined.split('\n')
        lines = [line.strip() for line in lines]
        combined = '\n'.join(lines)
        # Normalize multiple newlines to double newlines (paragraph breaks)
        combined = re.sub(r'\n{3,}', '\n\n', combined)

        return combined.strip()

    def _clean_headers_footers(self, text: str) -> str:
        """Remove common Science journal headers and footers."""
        # Common patterns to remove (line-based)
        patterns = [
            r'^REPORTS\s*$',
            r'^www\.sciencemag\.org\s+SCIENCE\s+VOL\s+\d+.*$',
            r'^\d+\s+(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4}.*$',
            r'^Downloaded from https://www\.science\.org.*$',
            r'^VOL\s+\d+\s+SCIENCE\s+www\.sciencemag\.org.*$',
            r'^\d{1,3}\s*$',  # Standalone page numbers
        ]

        lines = text.split('\n')
        cleaned_lines = []

        for line in lines:
            # Check if line matches any header/footer pattern
            is_header = False
            for pattern in patterns:
                if re.match(pattern, line.strip(), flags=re.IGNORECASE):
                    is_header = True
                    break

            if not is_header:
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def extract_all(self) -> Tuple[Dict, str]:
        """
        Extract metadata and full article text.

        Returns: (metadata, article_text)
        """
        metadata = self.extract_metadata()
        start_page, end_page = self.find_article_by_doi(metadata.get("doi"))

        # Add boundary info to metadata
        metadata["extracted_pages"] = f"{start_page + 1}-{end_page + 1}"

        article_text = self.extract_text(start_page, end_page)

        return metadata, article_text

    def close(self):
        """Close the PDF document."""
        self.doc.close()


def split_into_paragraphs(text: str, max_para_size: int = 3000) -> list[str]:
    """
    Split text into paragraphs.

    Paragraphs are separated by double newlines. Very large paragraphs
    are split further based on sentence boundaries.

    Args:
        text: Input text
        max_para_size: Maximum paragraph size in characters. Larger paragraphs
                       will be split at sentence boundaries.
    """
    # Split on double newlines
    paragraphs = re.split(r'\n\s*\n+', text)

    # Clean up and potentially split large paragraphs
    cleaned = []
    for para in paragraphs:
        para = para.strip()
        if not para or len(para) < 50:  # Skip very short fragments
            continue

        # If paragraph is too large, split it at sentence boundaries
        if len(para) > max_para_size:
            # Split into sentences
            sentences = re.split(r'([.!?])\s+', para)
            # Rejoin sentence + punctuation
            current = ""
            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                punct = sentences[i+1] if i+1 < len(sentences) else ""
                sentence_full = sentence + punct

                if len(current) + len(sentence_full) > max_para_size and current:
                    # Current chunk is full, save it
                    cleaned.append(current.strip())
                    current = sentence_full
                else:
                    current += " " + sentence_full if current else sentence_full

            if current.strip():
                cleaned.append(current.strip())
        else:
            cleaned.append(para)

    return cleaned


def create_paragraph_heading(paragraph: str, index: int) -> str:
    """
    Create a heading for a paragraph section.

    Uses the first sentence or first 60 characters as the heading.
    """
    # Normalize whitespace in paragraph for heading extraction
    para_normalized = re.sub(r'\s+', ' ', paragraph)

    # Try to get first sentence
    sentences = re.split(r'[.!?]\s+', para_normalized)
    if sentences and len(sentences[0]) < 100:
        heading = sentences[0]
        if not heading.endswith(('.', '!', '?')):
            heading += '.'
        return heading

    # Fallback: first 60 characters
    heading = para_normalized[:60].strip()
    if len(para_normalized) > 60:
        heading += '...'

    return heading


def create_output_json(metadata: Dict, text: str, use_paragraphs: bool = True) -> Dict:
    """
    Create output JSON in a format compatible with parse_pdf_article.py.

    Args:
        metadata: Article metadata
        text: Full article text
        use_paragraphs: If True, split into paragraph-based sections

    Returns JSON with sections (either single or paragraph-based).
    """
    if not use_paragraphs:
        # Single section mode
        return {
            "metadata": metadata,
            "sections": [
                {
                    "heading": metadata.get("title", "Article"),
                    "level": 1,
                    "text": text,
                    "page": 1,
                    "parent_heading": None,
                }
            ],
            "section_count": 1,
            "note": "Science journal article - extracted as continuous text (no section detection)",
        }

    # Paragraph mode - split into sections
    paragraphs = split_into_paragraphs(text)
    sections = []

    title = metadata.get("title", "Article")

    for i, para in enumerate(paragraphs):
        heading = create_paragraph_heading(para, i)

        section = {
            "heading": heading,
            "level": 2,  # All paragraphs are level 2
            "text": para,
            "page": 1,  # We don't track page-per-paragraph
            "parent_heading": title,
        }
        sections.append(section)

    return {
        "metadata": metadata,
        "sections": sections,
        "section_count": len(sections),
        "note": "Science journal article - extracted and split into paragraph sections",
    }


def print_summary(metadata: Dict, text: str):
    """Print extraction summary."""
    print("\n" + "="*70)
    print("Science PDF Extraction Summary")
    print("="*70)

    if metadata.get("title"):
        print(f"Title: {metadata['title']}")
    if metadata.get("subject"):
        print(f"Subject: {metadata['subject']}")
    if metadata.get("doi"):
        print(f"DOI: {metadata['doi']}")
    if metadata.get("extracted_pages"):
        print(f"Pages extracted: {metadata['extracted_pages']}")

    print(f"Total PDF pages: {metadata.get('pages', 'N/A')}")
    print(f"Extracted text: {len(text):,} characters")

    # Show preview
    print(f"\nText preview:")
    print("-" * 70)
    preview = text[:500] if len(text) > 500 else text
    print(preview + ("..." if len(text) > 500 else ""))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pdf", required=True,
        help="Path to Science journal PDF file"
    )
    parser.add_argument(
        "--output",
        help="Output JSON file (default: <pdf_name>_science.json)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print debug information"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress summary output"
    )
    parser.add_argument(
        "--text-only", action="store_true",
        help="Output plain text instead of JSON"
    )
    parser.add_argument(
        "--no-paragraphs", action="store_true",
        help="Extract as single section instead of paragraph sections (default: use paragraphs)"
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"Error: PDF file not found: {pdf_path}")

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        if args.text_only:
            output_path = pdf_path.parent / f"{pdf_path.stem}_science.txt"
        else:
            output_path = pdf_path.parent / f"{pdf_path.stem}_science.json"

    # Extract
    print(f"Parsing Science PDF: {pdf_path}")
    extractor = SciencePDFExtractor(str(pdf_path), debug=args.debug)

    metadata, text = extractor.extract_all()
    extractor.close()

    # Print summary
    if not args.quiet:
        print_summary(metadata, text)

    # Save output
    if args.text_only:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n✓ Text saved to: {output_path}")
    else:
        use_paragraphs = not args.no_paragraphs
        output_data = create_output_json(metadata, text, use_paragraphs=use_paragraphs)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Article data saved to: {output_path}")
        if use_paragraphs:
            print(f"  {output_data['section_count']} paragraph sections created")

    print(f"  {len(text):,} characters extracted")


if __name__ == "__main__":
    main()
