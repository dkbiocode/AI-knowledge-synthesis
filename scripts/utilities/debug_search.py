"""
Debug script to check for duplicate chunks in search results.

Usage:
  python debug_search.py "what diagnostic methods use long read sequencing methods?"
"""

import sys
from scripts.query.query_kb import embed_query, search, get_conn

def debug_search(query: str):
    """Run a search and check for duplicates."""
    print(f"Query: {query}\n")

    # Embed query
    print("Embedding query...")
    query_vec = embed_query(query, "text-embedding-3-small")

    # Search
    print("Searching database...\n")
    conn = get_conn("mngs_kb")
    cur = conn.cursor()

    hits = search(cur, query_vec, top_k=20, min_score=0.25)

    print(f"Found {len(hits)} chunks\n")
    print("=" * 100)

    # Check for duplicate chunk_ids
    chunk_ids = []
    duplicates = []

    for i, hit in enumerate(hits, 1):
        chunk_id = hit['chunk_id']
        source_type = hit['source_type']
        doc_title = hit['doc_title']
        heading = hit['heading'] or "(no heading)"
        parent_heading = hit['parent_heading'] or ""
        score = hit['score']
        text_preview = hit['text'][:100].replace('\n', ' ')

        # Check for duplicate
        if chunk_id in chunk_ids:
            duplicates.append((i, chunk_id))
            print(f"⚠️  DUPLICATE DETECTED")

        chunk_ids.append(chunk_id)

        section = f"{parent_heading} › {heading}" if parent_heading else heading

        print(f"{i:2}. [{source_type.upper():6}] Chunk ID: {chunk_id:5} | Score: {score:.3f}")
        print(f"    Doc: {doc_title[:60]}")
        print(f"    Section: {section[:70]}")
        print(f"    Text: {text_preview}...")
        print()

    print("=" * 100)

    if duplicates:
        print(f"\n❌ Found {len(duplicates)} duplicate chunk IDs:")
        for idx, chunk_id in duplicates:
            print(f"   Position {idx}: Chunk ID {chunk_id}")
    else:
        print("\n✅ No duplicate chunk IDs found")

    # Check for chunks from same paper/section
    print("\n" + "=" * 100)
    print("Chunks from same source:")

    sources = {}
    for i, hit in enumerate(hits, 1):
        doc_title = hit['doc_title']
        heading = hit['heading'] or "(no heading)"
        parent_heading = hit['parent_heading'] or ""
        section = f"{parent_heading} › {heading}" if parent_heading else heading

        key = (doc_title, section)
        if key not in sources:
            sources[key] = []
        sources[key].append((i, hit['chunk_id'], hit['score']))

    for (doc, section), chunks in sources.items():
        if len(chunks) > 1:
            print(f"\n📄 {doc}")
            print(f"   Section: {section}")
            print(f"   {len(chunks)} chunks:")
            for idx, chunk_id, score in chunks:
                print(f"      Position {idx}: Chunk ID {chunk_id} (score: {score:.3f})")

    cur.close()
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_search.py 'your query here'")
        sys.exit(1)

    query = ' '.join(sys.argv[1:])
    debug_search(query)
