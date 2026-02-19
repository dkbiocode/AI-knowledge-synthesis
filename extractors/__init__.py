"""
extractors

Source-specific extraction modules for chunking scientific literature into
sections with embeddings and citation metadata.

Each extractor implements the BaseExtractor interface:
  - chunk()                  → list of chunk dicts with plain text
  - extract_refs()           → reference index dict
  - html_fragment(section_id) → marked-up HTML for display (optional)

Available extractors:
  - PMCExtractor       (extractors/pmc.py) — PubMed Central HTML
  - ScienceExtractor   (extractors/science.py) — AAAS Science journals (TODO)
  - PDFExtractor       (extractors/pdf.py) — Fallback PDF parser (TODO)
"""

from .base import BaseExtractor
from .pmc import PMCExtractor

__all__ = ["BaseExtractor", "PMCExtractor"]
