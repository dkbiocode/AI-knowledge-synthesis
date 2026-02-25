"""
query_kb.py

Query the mNGS knowledge base using RAG (Retrieval-Augmented Generation).

Pipeline:
  1. Embed the question using the OpenAI embeddings API
  2. Search review_chunks and paper_chunks with pgvector cosine similarity
  3. Collect matching text chunks with their citation ref_ids
  4. Send a second OpenAI call to a chat model to generate a cited answer
  5. (--quote) Re-rank sentences within each chunk using BM25 and print
     the top verbatim supporting sentences alongside each citation

Usage:
  conda activate openai

  # Interactive mode (prompts for question):
  python query_kb.py

  # Pass question directly:
  python query_kb.py --question "what methods test for arthropod-born diseases"

  # Show verbatim supporting sentences from each retrieved chunk:
  python query_kb.py -q "..." --quote

  # Control how many sentences are shown per chunk (default: 2):
  python query_kb.py -q "..." --quote --quote-n 3

  # Tune retrieval:
  python query_kb.py -q "..." --top-k 10 --min-score 0.3

  # Use a specific chat model:
  python query_kb.py -q "..." --chat-model gpt-4o

Connection env vars: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
"""

import argparse
import os
import re
import sys
import textwrap

import psycopg2

# Add parent directory to path for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from config.db_config import get_connection


# ---------------------------------------------------------------------------
# Connection  (updated to use config module)
# ---------------------------------------------------------------------------

def get_conn(db_config: str = "local"):
    """Get database connection using config module.

    Args:
        db_config: Configuration name ('local' or 'supabase'). Default: 'local'

    Returns:
        psycopg2 connection object
    """
    return get_connection(db_config)


# ---------------------------------------------------------------------------
# Step 1 — Embed the query
# ---------------------------------------------------------------------------

def embed_query(question: str, model: str) -> list[float]:
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package not found. Run: conda activate openai")

    client = OpenAI()  # reads OPENAI_API_KEY from environment
    response = client.embeddings.create(input=question, model=model, dimensions=1536)
    return response.data[0].embedding


# ---------------------------------------------------------------------------
# Step 2 — Vector search
# ---------------------------------------------------------------------------

SEARCH_SQL = """
WITH review_hits AS (
    SELECT
        'review'                    AS source_type,
        rc.id                       AS chunk_id,
        rc.heading,
        rc.parent_heading,
        rc.text,
        rs.title                    AS doc_title,
        rs.domain                   AS domain,
        NULL::text                  AS paper_pmc_id,
        -- Collect all ref_ids cited in this review chunk
        COALESCE(
            array_agg(c.ref_id ORDER BY cc.position)
            FILTER (WHERE c.ref_id IS NOT NULL),
            '{}'
        )                           AS ref_ids,
        1 - (rc.embedding <=> %(qvec)s::vector) AS score
    FROM review_chunks rc
    JOIN review_sources rs ON rs.id = rc.source_id
    LEFT JOIN chunk_citations cc ON cc.chunk_id = rc.id
    LEFT JOIN citations c        ON c.id = cc.citation_id
    WHERE rc.embedding IS NOT NULL
    GROUP BY rc.id, rc.heading, rc.parent_heading, rc.text, rs.title, rs.domain
    HAVING 1 - (rc.embedding <=> %(qvec)s::vector) >= %(min_score)s

),
paper_hits AS (
    SELECT
        'paper'                     AS source_type,
        pc.id                       AS chunk_id,
        pc.heading,
        pc.parent_heading,
        pc.text,
        p.title                     AS doc_title,
        p.domain                    AS domain,
        p.pmc_id                    AS paper_pmc_id,
        -- ref_ids of citations that point to this paper
        COALESCE(
            array_agg(DISTINCT c.ref_id)
            FILTER (WHERE c.ref_id IS NOT NULL),
            '{}'
        )                           AS ref_ids,
        1 - (pc.embedding <=> %(qvec)s::vector) AS score
    FROM paper_chunks pc
    JOIN papers p    ON p.id = pc.paper_id
    LEFT JOIN citations c ON c.paper_id = p.id
    WHERE pc.embedding IS NOT NULL
    GROUP BY pc.id, pc.heading, pc.parent_heading, pc.text, p.title, p.domain, p.pmc_id
    HAVING 1 - (pc.embedding <=> %(qvec)s::vector) >= %(min_score)s
)
SELECT * FROM review_hits
UNION ALL
SELECT * FROM paper_hits
ORDER BY score DESC
LIMIT %(top_k)s
"""


def search(cur, query_vec: list[float], top_k: int, min_score: float) -> list[dict]:
    vec_str = f"[{','.join(str(x) for x in query_vec)}]"
    cur.execute(SEARCH_SQL, {"qvec": vec_str, "min_score": min_score, "top_k": top_k})
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Step 3 — Build context block for the LLM
# ---------------------------------------------------------------------------

def build_context(hits: list[dict]) -> str:
    """
    Format retrieved chunks into a numbered context block.
    Each hit gets a label showing its domain, source, and ref_ids.
    Chunks are grouped by domain (medical first, then veterinary).
    """
    lines = []
    current_domain = None

    for i, h in enumerate(hits, 1):
        # Add domain section header when domain changes
        domain = h.get("domain", "unknown").upper()
        if domain != current_domain:
            if current_domain is not None:
                lines.append("")  # Add spacing between domain sections
            lines.append(f"=== {domain} LITERATURE ===")
            current_domain = domain

        ref_ids = h["ref_ids"] or []
        if ref_ids:
            cite_label = ", ".join(sorted(set(ref_ids)))
        else:
            cite_label = "review article" if h["source_type"] == "review" else "cited paper"

        heading = h["heading"] or ""
        parent  = h["parent_heading"] or ""
        section = f"{parent} > {heading}".strip(" >") if parent else heading

        lines.append(
            f"[{i}] Domain: {h.get('domain', 'unknown')} | Source: {cite_label} | {h['doc_title'] or ''} | {section}\n"
            f"Score: {h['score']:.3f}\n"
            f"{h['text'].strip()}\n"
        )
    return "\n---\n".join(lines)


# ---------------------------------------------------------------------------
# Step 4 — Generate answer
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a specialist in infectious disease diagnostics and metagenomics with expertise in both medical and veterinary applications.

Answer the user's question using ONLY the provided context passages. Follow these strict rules:

**CRITICAL RULES:**
1. NEVER make generalizations when specific details are requested
2. If the user asks for specific items (e.g., "what specific pathogens", "which methods", "list the protocols"), you MUST:
   - Extract and list the EXACT names/details mentioned in the context
   - If specific details are NOT in the context, explicitly state: "The retrieved sources do not provide specific [pathogen names/methods/details]"
   - NEVER use vague terms like "various pathogens", "multiple methods", or "several approaches" when specific information was requested
3. Always cite sources using reference IDs (e.g., B5, B12)
4. Distinguish clearly between what IS stated in the sources vs. what is NOT

**Answer Format:**

1. **Medical Literature**: Present findings from medical (human) sources first.
   - If specific details requested but not found: State "Specific [details] not provided in retrieved medical sources"
   - If general information found: Summarize with citations

2. **Veterinary Literature**: Present findings from veterinary sources second.
   - Same rules as above

3. **Cross-Domain Synthesis**: ONLY if relevant information was found in both domains:
   - Highlight connections, overlaps, or knowledge-sharing opportunities
   - If insufficient information: State "Insufficient specific information for cross-domain comparison"

**Output Style:**
- Use bullet points and tables for lists of specific items
- Be concise but complete
- Prefer "Not specified in sources" over vague generalizations\
"""


def generate_answer(question: str, context: str, model: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package not found. Run: conda activate openai")

    client = OpenAI()

    user_message = (
        f"Question: {question}\n\n"
        f"Context passages:\n\n{context}"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Citation metadata helper
# ---------------------------------------------------------------------------

def fetch_citation_metadata(cur, ref_ids: list[str]) -> dict[str, dict]:
    """
    Fetch citation metadata (authors, year, title, journal) for a list of ref_ids.
    Returns a dict mapping ref_id -> {authors, year, title, journal}.
    """
    if not ref_ids:
        return {}

    placeholders = ','.join(['%s'] * len(ref_ids))
    query = f"""
        SELECT ref_id, authors, year, title, journal
        FROM citations
        WHERE ref_id IN ({placeholders})
    """
    cur.execute(query, ref_ids)

    result = {}
    for row in cur.fetchall():
        ref_id, authors, year, title, journal = row
        result[ref_id] = {
            'authors': authors,
            'year': year,
            'title': title,
            'journal': journal
        }
    return result


def format_citation(ref_id: str, metadata: dict) -> str:
    """
    Format a citation in author-list style.
    Example: "Yi et al. 2024" or "Smith & Jones 2023"
    """
    if not metadata:
        return ref_id  # Fallback to ref_id if no metadata

    authors = metadata.get('authors', '')
    year = metadata.get('year', '')

    if not authors:
        return f"{ref_id} ({year})" if year else ref_id

    # Parse author list (format: "Last1; Last2; Last3" or "First Last; First Last")
    author_parts = [a.strip() for a in authors.split(';')]

    if len(author_parts) == 0:
        first_author = ref_id
    elif len(author_parts) == 1:
        # Extract last name from "First Last" or just use "Last"
        name_parts = author_parts[0].split()
        first_author = name_parts[-1] if name_parts else author_parts[0]
    elif len(author_parts) == 2:
        # Two authors: "Smith & Jones"
        first = author_parts[0].split()[-1] if author_parts[0].split() else author_parts[0]
        second = author_parts[1].split()[-1] if author_parts[1].split() else author_parts[1]
        first_author = f"{first} & {second}"
    else:
        # Three or more: "Smith et al."
        first = author_parts[0].split()[-1] if author_parts[0].split() else author_parts[0]
        first_author = f"{first} et al."

    return f"{first_author} {year}" if year else first_author


# ---------------------------------------------------------------------------
# Step 5 (optional) — BM25 sentence re-ranking for verbatim quotes
# ---------------------------------------------------------------------------

# Simple naive splitter; fragments are merged below in split_sentences().
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9\"])')

# Abbreviations that end with a period but do NOT end a sentence.
_ABBREV_RE = re.compile(
    r'\b(Fig|et al|vs|Dr|Mr|Mrs|Prof|Jr|Sr|e\.g|i\.e|approx|dept|est)\.$',
    re.IGNORECASE,
)

# Stop-words to drop before BM25 tokenisation so they don't dominate scores.
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by from is are was were "
    "be been being have has had do does did will would could should may might "
    "this that these those it its we our they their can".split()
)


def _clean_sentence(text: str) -> str:
    """Strip inline citation numbers (e.g. '1 , 17 – 21', '1,2') from display text."""
    # Remove patterns like:  1 , 17 – 21   or   1,2,3   or   ( Fig. 2B )
    text = re.sub(r'\(\s*Fig\..*?\)', '', text)           # (Fig. 2B)
    text = re.sub(r'\b\d+\s*[,–\-]\s*\d+\b', '', text)   # 17 – 21
    text = re.sub(r'(?<!\w)\d+\s*(?=[,.]|$|\s)', '', text)  # lone numbers
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, remove stop-words."""
    tokens = re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
    return [t for t in tokens if t not in _STOPWORDS]


def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentences, merging fragments that follow an abbreviation
    period so that e.g. 'Fig. 2B' doesn't create a false split.
    """
    raw = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    merged: list[str] = []
    for frag in raw:
        if merged and _ABBREV_RE.search(merged[-1]):
            merged[-1] = merged[-1] + " " + frag
        else:
            merged.append(frag)
    return merged


def top_sentences(question: str, chunk_text: str, n: int = 2) -> list[tuple[str, float]]:
    """
    Split chunk_text into sentences, rank them against question using BM25,
    and return the top-n as (sentence, score) tuples in original text order.

    Returns an empty list if rank_bm25 is not installed or no sentences found.
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return []

    sentences = _split_sentences(chunk_text)
    if not sentences:
        return []

    # Tokenise
    tokenized = [_tokenize(s) for s in sentences]
    query_tokens = _tokenize(question)

    # BM25 needs at least one non-empty document
    if not any(tokenized):
        return []

    bm25 = BM25Okapi(tokenized)
    scores = bm25.get_scores(query_tokens)

    # Pair each sentence with its score, sort descending, take top-n
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    top_indices = sorted(idx for idx, _ in ranked[:n])  # restore original order

    return [(sentences[i], float(scores[i])) for i in top_indices]


def print_quotes(hits: list[dict], question: str, n: int, cur):
    """
    For each retrieved chunk, print the top-n BM25-ranked sentences as
    verbatim supporting evidence with author-list style citations.
    """
    # Collect all ref_ids from hits to fetch metadata in one query
    all_ref_ids = []
    for h in hits:
        ref_ids = h.get("ref_ids") or []
        all_ref_ids.extend(ref_ids)
    all_ref_ids = list(set(all_ref_ids))  # Remove duplicates

    # Fetch citation metadata
    citation_metadata = fetch_citation_metadata(cur, all_ref_ids)

    print(f"\n{'─' * 72}")
    print(f"  SUPPORTING QUOTES  (top {n} sentence(s) per chunk, ranked by BM25)")
    print(f"{'─' * 72}\n")

    for i, h in enumerate(hits, 1):
        ref_ids = h["ref_ids"] or []

        # Format citations in author-list style
        if ref_ids:
            formatted_cites = []
            for ref_id in sorted(set(ref_ids)):
                metadata = citation_metadata.get(ref_id, {})
                formatted_cites.append(format_citation(ref_id, metadata))
            cite_label = ", ".join(formatted_cites)
        else:
            cite_label = "review article" if h["source_type"] == "review" else "cited paper"

        heading = h["heading"] or "(no heading)"

        sents = top_sentences(question, h["text"], n)

        print(f"  [{i}] {cite_label}  |  {heading}  (chunk score {h['score']:.3f})")
        if not sents:
            print("      (no sentences extracted)")
        else:
            for sent, bm25_score in sents:
                display = _clean_sentence(sent)
                # Wrap at 76 chars, indent continuation lines
                wrapped = textwrap.fill(display, width=76,
                                        initial_indent='      "',
                                        subsequent_indent='       ')
                # Close the quote on the last line
                print(f'{wrapped}"  [bm25={bm25_score:.2f}]')
        print()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

DIVIDER = "=" * 72


def print_hits(hits: list[dict]):
    print(f"\n{'─' * 72}")
    print(f"  Retrieved {len(hits)} chunk(s)")
    print(f"{'─' * 72}")
    for i, h in enumerate(hits, 1):
        ref_ids = h["ref_ids"] or []
        cite_label = ", ".join(sorted(set(ref_ids))) if ref_ids else "—"
        source_tag = f"[{h['source_type'].upper()}]"
        heading = h["heading"] or "(no heading)"
        snippet = h["text"].strip()[:200].replace("\n", " ")
        print(f"  {i:>2}. {source_tag} score={h['score']:.3f}  refs={cite_label}")
        print(f"      {heading}")
        print(f"      {snippet}…")
    print()


def print_answer(answer: str):
    print(DIVIDER)
    print("ANSWER")
    print(DIVIDER)
    # Wrap long lines for terminal readability
    for line in answer.splitlines():
        if len(line) > 80:
            print(textwrap.fill(line, width=80))
        else:
            print(line)
    print(DIVIDER)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-q", "--question", default=None,
                        help="Question to answer (prompted if omitted)")
    parser.add_argument("--top-k", type=int, default=8,
                        help="Number of chunks to retrieve (default: 8)")
    parser.add_argument("--min-score", type=float, default=0.25,
                        help="Minimum cosine similarity score 0-1 (default: 0.25)")
    parser.add_argument("--embed-model", default="text-embedding-3-small",
                        help="OpenAI embedding model (default: text-embedding-3-small)")
    parser.add_argument("--chat-model", default="gpt-4o-mini",
                        help="OpenAI chat model for answer generation (default: gpt-4o-mini)")
    parser.add_argument("--db-config", default="local",
                        help="Database configuration: 'local' or 'supabase' (default: local)")
    parser.add_argument("--show-chunks", action="store_true",
                        help="Print retrieved chunks before the answer")
    parser.add_argument("--quote", action="store_true",
                        help="After the answer, print BM25-ranked verbatim "
                             "sentences from each retrieved chunk")
    parser.add_argument("--quote-n", type=int, default=2, metavar="N",
                        help="Number of sentences to quote per chunk (default: 2)")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY environment variable not set.")

    question = args.question
    if not question:
        question = input("Question: ").strip()
    if not question:
        sys.exit("No question provided.")

    print(f"\nQuestion: {question}")

    # Step 1 — embed
    print("Embedding query ...")
    query_vec = embed_query(question, args.embed_model)

    # Step 2 — search
    print(f"Searching (top_k={args.top_k}, min_score={args.min_score}) ...")
    conn = get_conn(args.db_config)
    cur = conn.cursor()
    try:
        hits = search(cur, query_vec, args.top_k, args.min_score)

        if not hits:
            print("No results found above the minimum score threshold.")
            print("Try lowering --min-score or broadening your question.")
            return

        # Sort hits by domain (medical first) for organized presentation to LLM
        # while preserving the score-based retrieval quality
        hits.sort(key=lambda h: (h.get('domain', 'unknown'), -h['score']))

        if args.show_chunks:
            print_hits(hits)

        # Step 3 — build context
        context = build_context(hits)

        # Step 4 — generate answer
        print(f"Generating answer with {args.chat_model} ...")
        answer = generate_answer(question, context, args.chat_model)

        print_answer(answer)

        # Step 5 (optional) — verbatim BM25 quotes
        if args.quote:
            print_quotes(hits, question, args.quote_n, cur)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
