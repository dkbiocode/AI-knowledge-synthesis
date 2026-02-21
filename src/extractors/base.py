"""
extractors/base.py

Abstract base class for all source-specific extractors.

Each extractor takes a source document (HTML, PDF, etc.) and produces:
  1. A list of chunk dicts with plain text + citation metadata (for embedding)
  2. A reference index dict (ref_id → full citation metadata)
  3. Optionally, marked-up HTML fragments for display in a web UI

Chunk dict schema (returned by chunk()):
  {
    "section_id"     : str,      # unique ID within document
    "heading"        : str,      # section heading
    "parent_heading" : str|None, # parent section heading
    "level"          : int,      # 1=h2, 2=h3, etc.
    "text"           : str,      # clean body text
    "full_text"      : str,      # heading + text (ready to embed)
    "char_count"     : int,
    "token_estimate" : int,
    "citations"      : [         # inline citations appearing in this chunk
      {
        "ref_id"     : str,      # e.g. "B45"
        "cite_key"   : str,      # e.g. "Gu et al., 2019"
        "doi"        : str|None,
        "pubmed_id"  : str|None,
        "pmc_id"     : str|None,
        "title"      : str|None,
        "authors"    : str|None,
        "year"       : str|None,
        "journal"    : str|None,
        "open_access": bool,
      },
      ...
    ],
  }

Reference index schema (returned by extract_refs()):
  {
    "B45": {
      "ref_id"     : "B45",
      "cite_text"  : "Full citation text",
      "doi"        : "https://doi.org/...",
      "pubmed_id"  : "12345678",
      "pmc_id"     : "PMC1234567",
      "title"      : "...",
      "authors"    : "...",
      "year"       : "2019",
      "journal"    : "...",
      "open_access": bool,
      "cited_in"   : [           # back-links to chunks citing this ref
        {"section_id": "s3_2", "heading": "..."},
        ...
      ],
    },
    ...
  }
"""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseExtractor(ABC):
    """
    Abstract base class for source-specific extractors.

    Subclasses must implement chunk() and extract_refs().
    html_fragment() is optional.
    """

    def __init__(self, source_path: str | Path):
        """
        Args:
            source_path: Path to the source document (HTML, PDF, etc.)
        """
        self.source_path = Path(source_path)
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source file not found: {self.source_path}")

    @abstractmethod
    def chunk(self) -> list[dict]:
        """
        Parse the source document into semantic chunks.

        Returns:
            List of chunk dicts (see module docstring for schema).
        """
        pass

    @abstractmethod
    def extract_refs(self) -> dict[str, dict]:
        """
        Extract the reference list / bibliography from the source.

        Returns:
            Dict keyed by ref_id (e.g. "B45") with full citation metadata
            (see module docstring for schema).
        """
        pass

    def html_fragment(self, section_id: str) -> str | None:
        """
        Return the marked-up HTML fragment for a given section.

        This is optional — used by web UIs to display verbatim excerpts with
        inline citations, emphasis, etc. preserved.

        Args:
            section_id: The section_id from a chunk dict

        Returns:
            HTML string, or None if not supported/available
        """
        return None

    def extract_all(self) -> tuple[list[dict], dict[str, dict]]:
        """
        Convenience method: calls chunk() and extract_refs() together.

        Returns:
            (chunks, reference_index)
        """
        chunks = self.chunk()
        refs = self.extract_refs()

        # Add cited_in back-links to reference index
        for ref_id in refs:
            refs[ref_id]["cited_in"] = []
        for c in chunks:
            for cit in c["citations"]:
                rid = cit["ref_id"]
                if rid in refs:
                    refs[rid]["cited_in"].append({
                        "section_id": c["section_id"],
                        "heading":    c["heading"],
                    })

        return chunks, refs
