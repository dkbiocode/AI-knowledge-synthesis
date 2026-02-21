"""
parse_pdf_article.py

Parse PDF scientific articles into structured sections when PMC HTML is not available.

Uses PyMuPDF (fitz) to extract text with font information, then identifies section
headings based on font size, style (bold/semibold), and text patterns.

Outputs a JSON structure similar to PMCExtractor for consistency with the workflow.

Installation:
  pip install pymupdf

Usage:
  # Basic parsing
  python parse_pdf_article.py --pdf article.pdf

  # With output file
  python parse_pdf_article.py --pdf article.pdf --output article_sections.json

  # Show debug info (font analysis)
  python parse_pdf_article.py --pdf article.pdf --debug

  # Adjust heading detection thresholds
  python parse_pdf_article.py --pdf article.pdf --min-heading-size 9.0
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Tuple


try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF not installed")
    print("Install with: pip install pymupdf")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Font-based heading detection
# ---------------------------------------------------------------------------

class HeadingDetector:
    """Detect section headings based on font size and style."""

    def __init__(self, min_heading_size: float = 8.5, body_text_size: float = 8.2):
        self.min_heading_size = min_heading_size
        self.body_text_size = body_text_size
        self.font_stats = defaultdict(lambda: {"count": 0, "sizes": []})

    def analyze_fonts(self, doc: fitz.Document, sample_pages: int = 5):
        """
        Analyze font usage across sample pages to establish baselines.
        """
        pages_to_check = min(sample_pages, len(doc))

        for page_num in range(pages_to_check):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if "lines" not in block:
                    continue

                for line in block["lines"]:
                    for span in line["spans"]:
                        font = span["font"]
                        size = span["size"]
                        text = span["text"].strip()

                        if len(text) > 0:
                            self.font_stats[font]["count"] += 1
                            self.font_stats[font]["sizes"].append(size)

        # Calculate average sizes
        for font, stats in self.font_stats.items():
            if stats["sizes"]:
                stats["avg_size"] = sum(stats["sizes"]) / len(stats["sizes"])
                stats["max_size"] = max(stats["sizes"])

        return self.font_stats

    def is_heading(self, font: str, size: float, text: str) -> Tuple[bool, int]:
        """
        Determine if a text span is a heading and its level.

        Returns: (is_heading, level)
        """
        text = text.strip()

        # Skip very short or very long text
        if len(text) < 3 or len(text) > 150:
            return False, 0

        # Skip page numbers, citations, etc.
        if text.isdigit() or re.match(r'^[\d\s,\-]+$', text):
            return False, 0

        # Blacklist common false positives
        blacklist = [
            r'^Article$',
            r'^Check for updates',
            r'^(Received|Accepted|Published|Revised):',
            r'^https?://',
            r'^\d+$',  # Pure numbers
            r'^Page \d+',
            r'^\w+\s+\w+\s+\|\s+Volume',  # Journal headers
            r'nature\s+(methods|communications|genetics)',
        ]

        if any(re.match(pat, text, re.IGNORECASE) for pat in blacklist):
            return False, 0

        # Skip if text is mostly author names format (contains multiple commas and numbers)
        if text.count(',') >= 2 and re.search(r'\d', text):
            return False, 0

        # Skip abstract-like paragraphs (long sentences with common words)
        if len(text) > 100 and any(word in text.lower() for word in
                                   ['we developed', 'we applied', 'we can', 'here we']):
            return False, 0

        # Font style indicators
        is_bold = "Bold" in font
        is_semibold = "Semibold" in font

        # Size-based detection
        large_heading = size >= self.min_heading_size + 2.0  # Level 1
        medium_heading = size >= self.min_heading_size        # Level 2
        small_heading = (is_bold or is_semibold) and size >= self.body_text_size  # Level 3

        # Pattern-based detection (common section names)
        heading_patterns = [
            r'^(Abstract|Introduction|Background|Methods?|Results?|Discussion|Conclusion)',
            r'^(Materials? and Methods?|Experimental Procedures?)',
            r'^(Acknowledgements?|References|Supplementary|Appendix)',
            r'^(Data Availability|Author Contributions?|Competing Interests?|Additional Information)',
            r'^(Ethics|Sample|DNA|Library|Sequencing|Benchmarking|Analysis)',
            r'^(Online content|Code availability)',
            r'^\d+[.\s]+[A-Z]',  # "1. Introduction" or "1 Methods"
        ]

        matches_pattern = any(re.match(pat, text, re.IGNORECASE) for pat in heading_patterns)

        # Level determination
        if large_heading and (matches_pattern or is_bold):
            return True, 1
        elif medium_heading and (matches_pattern or is_semibold):
            return True, 2
        elif small_heading and matches_pattern:
            return True, 3

        return False, 0


# ---------------------------------------------------------------------------
# PDF Section Extractor
# ---------------------------------------------------------------------------

class PDFSectionExtractor:
    """Extract structured sections from a PDF document."""

    def __init__(self, pdf_path: str, min_heading_size: float = 8.5, debug: bool = False):
        self.pdf_path = Path(pdf_path)
        self.debug = debug
        self.doc = fitz.open(str(self.pdf_path))
        self.detector = HeadingDetector(min_heading_size=min_heading_size)

        # Article boundary markers
        self.article_start_page = None
        self.article_start_position = None
        self.article_end_page = None
        self.article_end_position = None

        # Analyze fonts in document
        if self.debug:
            print("Analyzing font usage...")
        self.font_stats = self.detector.analyze_fonts(self.doc)

        if self.debug:
            self._print_font_stats()

    def _print_font_stats(self):
        """Print font statistics for debugging."""
        print("\n" + "="*70)
        print("Font Statistics")
        print("="*70)
        sorted_fonts = sorted(self.font_stats.items(),
                             key=lambda x: x[1]["count"], reverse=True)

        for font, stats in sorted_fonts[:15]:
            avg_size = stats.get("avg_size", 0)
            max_size = stats.get("max_size", 0)
            count = stats["count"]
            print(f"  {font:35s} | avg:{avg_size:4.1f} max:{max_size:4.1f} count:{count:5d}")
        print()

    def extract_metadata(self) -> Dict:
        """Extract PDF metadata."""
        meta = self.doc.metadata

        return {
            "title": meta.get("title", ""),
            "authors": meta.get("author", ""),
            "subject": meta.get("subject", ""),
            "keywords": meta.get("keywords", ""),
            "creator": meta.get("creator", ""),
            "created": meta.get("creationDate", ""),
            "pages": len(self.doc),
        }

    def detect_article_boundaries(self, title: str = None) -> Tuple[int, int]:
        """
        Detect article start and end boundaries.

        Start: First occurrence of article title (from metadata)
        End: References section

        Returns: (start_page, end_page) or (None, None) if not found
        """
        if title is None:
            title = self.doc.metadata.get("title", "")

        if not title:
            if self.debug:
                print("No title in metadata - cannot detect article boundaries")
            return None, None

        # Normalize title for matching (remove extra whitespace, lowercase)
        title_normalized = " ".join(title.lower().split())
        title_words = title_normalized.split()[:10]  # Use first 10 words for matching

        start_page = None
        end_page = None

        # Find article start (title)
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text().lower()
            text_normalized = " ".join(text.split())

            # Check if title appears in this page
            if len(title_words) >= 5:
                # Match first 5+ words of title
                title_snippet = " ".join(title_words[:5])
                if title_snippet in text_normalized:
                    start_page = page_num
                    if self.debug:
                        print(f"Article start detected on page {page_num + 1} (title match)")
                    break

        # Find article end (References section)
        references_patterns = [
            r'\bReferences and Notes\b',
            r'\bReferences\b',
            r'\bREFERENCES\b',
            r'\bLiterature Cited\b',
            r'\bBibliography\b',
        ]

        for page_num in range(start_page if start_page else 0, len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text()

            # Check for references section
            for pattern in references_patterns:
                if re.search(pattern, text):
                    end_page = page_num
                    if self.debug:
                        print(f"Article end detected on page {page_num + 1} (References section)")
                    break

            if end_page:
                break

        self.article_start_page = start_page
        self.article_end_page = end_page

        return start_page, end_page

    def extract_sections(self) -> List[Dict]:
        """
        Extract sections from the PDF.

        Returns list of section dicts with:
          - heading: section heading text
          - level: heading level (1, 2, 3)
          - text: section body text
          - page: page number where section starts
          - parent_heading: parent section heading (for hierarchy)
        """
        sections = []
        current_section = None
        heading_stack = [None, None, None, None]  # Track hierarchy

        # Determine page range to process
        start_page = self.article_start_page if self.article_start_page is not None else 0
        end_page = self.article_end_page if self.article_end_page is not None else len(self.doc) - 1

        if self.debug and (self.article_start_page is not None or self.article_end_page is not None):
            print(f"Processing pages {start_page + 1} to {end_page + 1} (article boundaries detected)")

        in_references = False  # Flag to skip content after References heading

        for page_num in range(start_page, end_page + 1):
            page = self.doc[page_num]
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if "lines" not in block:
                    continue

                for line in block["lines"]:
                    line_text = ""
                    line_fonts = []

                    # Collect all spans in this line
                    for span in line["spans"]:
                        font = span["font"]
                        size = span["size"]
                        text = span["text"]
                        line_text += text
                        line_fonts.append((font, size, text))

                    line_text = line_text.strip()

                    if not line_text:
                        continue

                    # Check if this line is a heading
                    # Use the first span's font for detection
                    if line_fonts:
                        first_font, first_size, first_text = line_fonts[0]
                        is_heading, level = self.detector.is_heading(
                            first_font, first_size, line_text
                        )

                        if is_heading:
                            # Check if this is the References section - stop processing after this
                            if re.match(r'\b(References|REFERENCES|References and Notes|Literature Cited)\b', line_text):
                                in_references = True
                                if self.debug:
                                    print(f"[Page {page_num + 1}] Reached References section - stopping content extraction")

                            # Save previous section
                            if current_section:
                                current_section["text"] = current_section["text"].strip()
                                if current_section["text"] or current_section["heading"]:
                                    sections.append(current_section)

                            # Determine parent heading
                            parent_heading = None
                            if level > 1:
                                # Find nearest higher-level heading in stack
                                for i in range(level - 1, 0, -1):
                                    if heading_stack[i]:
                                        parent_heading = heading_stack[i]
                                        break

                            # Start new section
                            current_section = {
                                "heading": line_text,
                                "level": level,
                                "text": "",
                                "page": page_num + 1,
                                "parent_heading": parent_heading,
                            }

                            # Update heading stack
                            heading_stack[level] = line_text
                            # Clear lower levels
                            for i in range(level + 1, len(heading_stack)):
                                heading_stack[i] = None

                            if self.debug:
                                indent = "  " * (level - 1)
                                print(f"[Page {page_num + 1}] {indent}{'='*level}> {line_text}")

                            # If we just entered references, break out
                            if in_references:
                                break

                        else:
                            # Regular text - append to current section (but not if we're in references)
                            if current_section and not in_references:
                                current_section["text"] += line_text + " "

                # Break out of block loop if we hit references
                if in_references:
                    break

            # Break out of page loop if we hit references
            if in_references:
                break

        # Save last section
        if current_section:
            current_section["text"] = current_section["text"].strip()
            if current_section["text"] or current_section["heading"]:
                sections.append(current_section)

        return sections

    def extract_as_single_block(self) -> List[Dict]:
        """
        Extract article content as a single continuous block (no section detection).

        Useful for articles without clear section headings.
        """
        # Determine page range
        start_page = self.article_start_page if self.article_start_page is not None else 0
        end_page = self.article_end_page if self.article_end_page is not None else len(self.doc) - 1

        metadata = self.extract_metadata()
        title = metadata.get("title", "")
        title_normalized = " ".join(title.lower().split())
        title_words = title_normalized.split()[:5]  # First 5 words

        full_text = []
        found_title = False

        for page_num in range(start_page, end_page + 1):
            page = self.doc[page_num]
            text = page.get_text()

            # On the start page, skip everything before the title
            if page_num == start_page and title and len(title_words) >= 3:
                text_lower = text.lower()
                title_snippet = " ".join(title_words)

                # Find where title appears
                title_pos = text_lower.find(title_snippet)
                if title_pos != -1:
                    # Start extracting from the title
                    text = text[title_pos:]
                    found_title = True

            # Stop at References section
            if re.search(r'\b(References and Notes|References|REFERENCES|Literature Cited)\b', text):
                # Extract only text before references
                match = re.search(r'\b(References and Notes|References|REFERENCES|Literature Cited)\b', text)
                text = text[:match.start()]
                full_text.append(text)
                break

            full_text.append(text)

        # Combine and clean
        combined_text = " ".join(full_text)
        combined_text = re.sub(r'\s+', ' ', combined_text).strip()

        # Create single section
        metadata = self.extract_metadata()
        title = metadata.get("title", "Article")

        section = {
            "heading": title,
            "level": 1,
            "text": combined_text,
            "page": start_page + 1,
            "parent_heading": None,
        }

        return [section]

    def extract_all(self, no_sections: bool = False) -> Tuple[List[Dict], Dict]:
        """
        Extract sections and metadata.

        Args:
            no_sections: If True, extract as single continuous block

        Returns: (sections, metadata)
        """
        metadata = self.extract_metadata()

        # Detect article boundaries (title to references)
        self.detect_article_boundaries()

        if no_sections:
            sections = self.extract_as_single_block()
        else:
            sections = self.extract_sections()

        return sections, metadata

    def close(self):
        """Close the PDF document."""
        self.doc.close()


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def sections_to_json(sections: List[Dict], metadata: Dict) -> Dict:
    """
    Convert sections to JSON format compatible with PMCExtractor output.
    """
    output = {
        "metadata": metadata,
        "sections": sections,
        "section_count": len(sections),
    }

    return output


def print_section_tree(sections: List[Dict]):
    """Print section hierarchy as a tree."""
    print("\n" + "="*70)
    print("Section Hierarchy")
    print("="*70)

    for section in sections:
        level = section["level"]
        heading = section["heading"]
        text_preview = section["text"][:60].replace("\n", " ")
        indent = "  " * (level - 1)
        marker = "■" * level

        print(f"{indent}{marker} {heading}")
        if text_preview:
            print(f"{indent}   {text_preview}...")


def print_summary(sections: List[Dict], metadata: Dict, extractor=None):
    """Print extraction summary."""
    print("\n" + "="*70)
    print("Extraction Summary")
    print("="*70)

    if metadata.get("title"):
        print(f"Title: {metadata['title']}")
    if metadata.get("authors"):
        print(f"Authors: {metadata['authors']}")
    if metadata.get("subject"):
        print(f"Subject: {metadata['subject']}")
    print(f"Pages: {metadata.get('pages', 'N/A')}")

    # Show article boundaries if detected
    if extractor and extractor.article_start_page is not None:
        print(f"Article boundaries: pages {extractor.article_start_page + 1} to {extractor.article_end_page + 1}")

    print(f"Sections extracted: {len(sections)}")

    # Count by level
    level_counts = defaultdict(int)
    for section in sections:
        level_counts[section["level"]] += 1

    for level in sorted(level_counts.keys()):
        print(f"  Level {level}: {level_counts[level]}")

    # Total text
    total_chars = sum(len(s["text"]) for s in sections)
    print(f"Total text: {total_chars:,} characters")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pdf", required=True,
        help="Path to PDF file to parse"
    )
    parser.add_argument(
        "--output",
        help="Output JSON file (default: <pdf_name>_sections.json)"
    )
    parser.add_argument(
        "--min-heading-size", type=float, default=8.5,
        help="Minimum font size for headings (default: 8.5)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print debug information (font analysis, section detection)"
    )
    parser.add_argument(
        "--show-tree", action="store_true",
        help="Print section hierarchy tree"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress summary output"
    )
    parser.add_argument(
        "--no-sections", action="store_true",
        help="Extract as single continuous text (no section detection)"
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"Error: PDF file not found: {pdf_path}")

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = pdf_path.parent / f"{pdf_path.stem}_sections.json"

    # Extract sections
    print(f"Parsing PDF: {pdf_path}")
    extractor = PDFSectionExtractor(
        str(pdf_path),
        min_heading_size=args.min_heading_size,
        debug=args.debug
    )

    sections, metadata = extractor.extract_all(no_sections=args.no_sections)

    # Print results
    if not args.quiet:
        print_summary(sections, metadata, extractor)
        if args.no_sections:
            print("  (Extracted as single continuous block - no section detection)")

    if args.show_tree:
        print_section_tree(sections)

    extractor.close()

    # Save to JSON
    output_data = sections_to_json(sections, metadata)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Sections saved to: {output_path}")
    print(f"  {len(sections)} sections extracted")


if __name__ == "__main__":
    main()
