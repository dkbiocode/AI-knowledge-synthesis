"""
chunk_vet_review.py

Chunk PMC11171117.html (veterinary NGS review) using the extractors package.

Outputs:
  - vet_chunks.json       (section chunks with metadata)
  - vet_references.json   (reference index for citations)

Usage:
  python chunk_vet_review.py
"""

import json
import os

from src.extractors import PMCExtractor


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(script_dir, "PMC11171117.html")

    if not os.path.exists(html_path):
        print(f"ERROR: {html_path} not found")
        return

    print(f"Chunking {html_path} ...")
    extractor = PMCExtractor(html_path)

    # Extract chunks
    chunks = extractor.chunk()
    print(f"  Extracted {len(chunks)} chunks")

    # Extract references
    references = extractor.extract_refs()
    print(f"  Extracted {len(references)} references")

    # Save chunks
    chunks_path = os.path.join(script_dir, "vet_chunks.json")
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    print(f"  Saved chunks to {chunks_path}")

    # Save references
    refs_path = os.path.join(script_dir, "vet_references.json")
    with open(refs_path, "w", encoding="utf-8") as f:
        json.dump(references, f, indent=2, ensure_ascii=False)
    print(f"  Saved references to {refs_path}")

    # Summary
    total_chars = sum(c["char_count"] for c in chunks)
    total_tokens = sum(c["token_estimate"] for c in chunks)
    total_citations = sum(len(c["citations"]) for c in chunks)

    print(f"\nSummary:")
    print(f"  Chunks:    {len(chunks)}")
    print(f"  Refs:      {len(references)}")
    print(f"  Chars:     {total_chars:,}")
    print(f"  Tokens:    {total_tokens:,}")
    print(f"  Citations: {total_citations}")
    print(f"\nNext steps:")
    print(f"  1. python embed_chunks.py --chunks vet_chunks.json --output vet_embeddings.json")
    print(f"  2. python load_chunks.py --chunks vet_chunks.json --refs vet_references.json --embeddings vet_embeddings.json \\")
    print(f"       --doc-key PMC11171117 --domain veterinary \\")
    print(f"       --title \"<title>\" --authors \"<authors>\" --journal \"<journal>\"")


if __name__ == "__main__":
    main()
