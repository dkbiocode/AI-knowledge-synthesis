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


# ---------------------------------------------------------------------------
# Connection  (same pattern as load_chunks.py)
# ---------------------------------------------------------------------------

def get_conn(dbname: str):
    params = {
        "host":     os.environ.get("PGHOST", "localhost"),
        "port":     int(os.environ.get("PGPORT", 5432)),
        "user":     os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname":   dbname,
    }
    return psycopg2.connect(**{k: v for k, v in params.items() if v != ""})


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
    GROUP BY rc.id, rc.heading, rc.parent_heading, rc.text, rs.title
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
    GROUP BY pc.id, pc.heading, pc.parent_heading, pc.text, p.title, p.pmc_id
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
    Each hit gets a label showing its source and ref_ids.
    """
    lines = []
    for i, h in enumerate(hits, 1):
        ref_ids = h["ref_ids"] or []
        if ref_ids:
            cite_label = ", ".join(sorted(set(ref_ids)))
        else:
            cite_label = "review article" if h["source_type"] == "review" else "cited paper"

        heading = h["heading"] or ""
        parent  = h["parent_heading"] or ""
        section = f"{parent} > {heading}".strip(" >") if parent else heading

        lines.append(
            f"[{i}] Source: {cite_label} | {h['doc_title'] or ''} | {section}\n"
            f"Score: {h['score']:.3f}\n"
            f"{h['text'].strip()}\n"
        )
    return "\n---\n".join(lines)


# ---------------------------------------------------------------------------
# Step 4 — Generate answer
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a specialist in infectious disease diagnostics and metagenomics.
Answer the user's question using ONLY the provided context passages.
Cite sources using the reference IDs shown (e.g. B5, B12).
If a passage comes from the review article itself, note that.
If the context does not contain enough information to answer, say so.
Be concise but complete. Use bullet points where appropriate.\
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


def print_quotes(hits: list[dict], question: str, n: int):
    """
    For each retrieved chunk, print the top-n BM25-ranked sentences as
    verbatim supporting evidence.
    """
    print(f"\n{'─' * 72}")
    print(f"  SUPPORTING QUOTES  (top {n} sentence(s) per chunk, ranked by BM25)")
    print(f"{'─' * 72}\n")

    for i, h in enumerate(hits, 1):
        ref_ids = h["ref_ids"] or []
        cite_label = ", ".join(sorted(set(ref_ids))) if ref_ids else (
            "review article" if h["source_type"] == "review" else "cited paper"
        )
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
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
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
    conn = get_conn(args.dbname)
    cur = conn.cursor()
    try:
        hits = search(cur, query_vec, args.top_k, args.min_score)
    finally:
        cur.close()
        conn.close()

    if not hits:
        print("No results found above the minimum score threshold.")
        print("Try lowering --min-score or broadening your question.")
        return

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
        print_quotes(hits, question, args.quote_n)


if __name__ == "__main__":
    main()
