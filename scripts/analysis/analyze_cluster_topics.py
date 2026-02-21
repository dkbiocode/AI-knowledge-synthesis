"""
analyze_cluster_topics.py

Identify NGS-specific topics within clusters using:
  1. TF-IDF analysis to extract distinctive terms per cluster
  2. NGS keyword matching to identify protocol-heavy clusters
  3. Sample representative chunks for manual review

Usage:
  python analyze_cluster_topics.py
  python analyze_cluster_topics.py --top-terms 10
  python analyze_cluster_topics.py --cluster 7  # Focus on specific cluster
"""

import argparse
import os
import re
from collections import Counter, defaultdict

import numpy as np
import psycopg2
from sklearn.feature_extraction.text import TfidfVectorizer


# ---------------------------------------------------------------------------
# NGS-specific keywords
# ---------------------------------------------------------------------------

NGS_KEYWORDS = {
    # Sequencing technologies
    'ngs', 'next-generation sequencing', 'illumina', 'ion torrent', 'oxford nanopore',
    'pacbio', 'minion', 'sequel', 'novaseq', 'miseq', 'hiseq',

    # NGS modalities
    'mngs', 'metagenomic', 'metagenomics', 'whole genome sequencing', 'wgs',
    'targeted sequencing', 'amplicon sequencing', 'rna-seq', 'transcriptome',
    '16s rrna', '16s sequencing', 'shotgun sequencing',

    # NGS workflows
    'library preparation', 'adapter ligation', 'index', 'multiplexing',
    'demultiplexing', 'base calling', 'quality score', 'phred',

    # Bioinformatics
    'alignment', 'mapping', 'bwa', 'bowtie', 'blast', 'kraken', 'metaphlan',
    'trinity', 'spades', 'variant calling', 'snp', 'indel',
    'coverage', 'read depth', 'fastq', 'bam', 'vcf',

    # Clinical NGS
    'pathogen detection', 'microbial identification', 'antimicrobial resistance',
    'virulence factors', 'outbreak investigation', 'molecular diagnostics',

    # Specimen types
    'csf', 'cerebrospinal fluid', 'blood', 'plasma', 'serum', 'tissue',
    'biopsy', 'swab', 'bronchoalveolar lavage', 'bal',
}


# ---------------------------------------------------------------------------
# Database connection
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
# Data loading
# ---------------------------------------------------------------------------

def load_cluster_chunks(cur, cluster_id=None):
    """
    Load chunk text and metadata for all clusters or a specific cluster.
    Returns: list of dicts with keys: cluster_id, chunk_id, heading, text, domain
    """
    query = """
        SELECT
            cc.cluster_id,
            cc.chunk_id,
            cc.chunk_type,
            CASE
                WHEN cc.chunk_type = 'review' THEN rc.heading
                WHEN cc.chunk_type = 'paper' THEN pc.heading
            END as heading,
            CASE
                WHEN cc.chunk_type = 'review' THEN rc.text
                WHEN cc.chunk_type = 'paper' THEN pc.text
            END as text,
            CASE
                WHEN cc.chunk_type = 'review' THEN rs.domain
                WHEN cc.chunk_type = 'paper' THEN p.domain
            END as domain
        FROM chunk_clusters cc
        LEFT JOIN review_chunks rc ON cc.chunk_id = 'review_' || rc.id
        LEFT JOIN review_sources rs ON rc.source_id = rs.id
        LEFT JOIN paper_chunks pc ON cc.chunk_id = 'paper_' || pc.id
        LEFT JOIN papers p ON pc.paper_id = p.id
        WHERE cc.cluster_id != -1  -- Exclude noise
    """

    params = []
    if cluster_id is not None:
        query += " AND cc.cluster_id = %s"
        params.append(cluster_id)

    query += " ORDER BY cc.cluster_id, cc.chunk_id"

    cur.execute(query, params)

    chunks = []
    for row in cur.fetchall():
        cluster_id, chunk_id, chunk_type, heading, text, domain = row
        chunks.append({
            "cluster_id": cluster_id,
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "heading": heading or "",
            "text": text or "",
            "domain": domain or "unknown",
        })

    return chunks


# ---------------------------------------------------------------------------
# TF-IDF analysis
# ---------------------------------------------------------------------------

def compute_tfidf_per_cluster(chunks, top_n=10):
    """
    Compute TF-IDF scores per cluster to identify distinctive terms.
    Returns: dict {cluster_id: [(term, score), ...]}
    """
    # Group chunks by cluster
    cluster_texts = defaultdict(list)
    for chunk in chunks:
        combined_text = f"{chunk['heading']} {chunk['text']}"
        cluster_texts[chunk['cluster_id']].append(combined_text)

    # Combine all texts per cluster into single document
    cluster_docs = {}
    cluster_ids = []
    for cluster_id in sorted(cluster_texts.keys()):
        cluster_docs[cluster_id] = " ".join(cluster_texts[cluster_id])
        cluster_ids.append(cluster_id)

    docs = [cluster_docs[cid] for cid in cluster_ids]

    # Compute TF-IDF
    # Adjust min_df and max_df based on number of documents
    if len(docs) == 1:
        min_df_val = 1
        max_df_val = 1.0
    elif len(docs) == 2:
        min_df_val = 1
        max_df_val = 1.0
    else:
        min_df_val = 2
        max_df_val = 0.8

    vectorizer = TfidfVectorizer(
        max_features=500,
        stop_words='english',
        ngram_range=(1, 2),  # Include bigrams
        min_df=min_df_val,
        max_df=max_df_val,
    )

    tfidf_matrix = vectorizer.fit_transform(docs)
    feature_names = vectorizer.get_feature_names_out()

    # Extract top terms per cluster
    top_terms = {}
    for i, cluster_id in enumerate(cluster_ids):
        scores = tfidf_matrix[i].toarray().flatten()
        top_indices = scores.argsort()[-top_n:][::-1]
        top_terms[cluster_id] = [(feature_names[idx], scores[idx]) for idx in top_indices]

    return top_terms


# ---------------------------------------------------------------------------
# NGS keyword matching
# ---------------------------------------------------------------------------

def count_ngs_keywords(chunks):
    """
    Count NGS-specific keywords per cluster.
    Returns: dict {cluster_id: {keyword: count}}
    """
    cluster_keywords = defaultdict(lambda: defaultdict(int))

    for chunk in chunks:
        text_lower = f"{chunk['heading']} {chunk['text']}".lower()

        for keyword in NGS_KEYWORDS:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(keyword) + r'\b'
            count = len(re.findall(pattern, text_lower))
            if count > 0:
                cluster_keywords[chunk['cluster_id']][keyword] += count

    return cluster_keywords


def ngs_relevance_score(keyword_counts):
    """
    Compute NGS relevance score per cluster based on keyword frequency.
    Returns: dict {cluster_id: score}
    """
    scores = {}
    for cluster_id, keywords in keyword_counts.items():
        # Sum of keyword occurrences
        total = sum(keywords.values())
        # Unique keywords
        unique = len(keywords)
        # Combined score (weighted more toward diversity)
        scores[cluster_id] = total + (unique * 2)

    return scores


# ---------------------------------------------------------------------------
# Representative chunks
# ---------------------------------------------------------------------------

def get_representative_chunks(chunks, n=5):
    """
    Get representative chunks per cluster (highest NGS keyword density).
    Returns: dict {cluster_id: [chunk_dict, ...]}
    """
    cluster_chunks = defaultdict(list)

    for chunk in chunks:
        text_lower = f"{chunk['heading']} {chunk['text']}".lower()

        # Count NGS keywords in this chunk
        keyword_count = 0
        for keyword in NGS_KEYWORDS:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            keyword_count += len(re.findall(pattern, text_lower))

        # Normalize by text length
        text_len = len(chunk['text'])
        density = keyword_count / max(text_len, 1) * 1000  # Per 1000 chars

        chunk['ngs_density'] = density
        cluster_chunks[chunk['cluster_id']].append(chunk)

    # Sort by density and take top N
    representatives = {}
    for cluster_id, chunk_list in cluster_chunks.items():
        sorted_chunks = sorted(chunk_list, key=lambda x: x['ngs_density'], reverse=True)
        representatives[cluster_id] = sorted_chunks[:n]

    return representatives


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_cluster_report(cluster_id, top_terms, keyword_counts, representatives, gap_scores):
    """
    Print a detailed report for a single cluster.
    """
    print(f"\n{'='*80}")
    print(f"CLUSTER {cluster_id}")
    print(f"{'='*80}")

    # Gap score
    if cluster_id in gap_scores:
        gap = gap_scores[cluster_id]
        print(f"Gap Score: {gap['gap_score']:.2f} ({gap['gap_label']})")
        print(f"Composition: {gap['medical_count']} medical, {gap['vet_count']} vet, {gap['total_count']} total")

    # Top TF-IDF terms
    print(f"\nTop Distinctive Terms (TF-IDF):")
    for term, score in top_terms.get(cluster_id, []):
        print(f"  {term:30s} {score:.3f}")

    # NGS keywords
    keywords = keyword_counts.get(cluster_id, {})
    if keywords:
        print(f"\nTop NGS Keywords:")
        sorted_kw = sorted(keywords.items(), key=lambda x: x[1], reverse=True)[:10]
        for kw, count in sorted_kw:
            print(f"  {kw:30s} {count:4d}")
    else:
        print(f"\nNo NGS keywords detected")

    # Representative chunks
    print(f"\nRepresentative Chunks:")
    for i, chunk in enumerate(representatives.get(cluster_id, [])[:3], 1):
        print(f"\n  [{i}] {chunk['heading'][:60]} ({chunk['domain']})")
        print(f"      NGS density: {chunk['ngs_density']:.2f} per 1000 chars")
        print(f"      {chunk['text'][:150]}...")


def print_summary_table(top_terms, ngs_scores, gap_scores):
    """
    Print summary table of all clusters.
    """
    print(f"\n{'='*100}")
    print(f"CLUSTER SUMMARY")
    print(f"{'='*100}")
    print(f"{'Cluster':<10} {'Gap':<8} {'NGS':<8} {'Label':<20} {'Top Terms':<50}")
    print(f"{'-'*100}")

    for cluster_id in sorted(top_terms.keys()):
        gap = gap_scores.get(cluster_id, {})
        gap_score = gap.get('gap_score', 0)
        gap_label = gap.get('gap_label', 'unknown')
        ngs_score = ngs_scores.get(cluster_id, 0)

        # Top 3 terms
        terms = [t[0] for t in top_terms.get(cluster_id, [])[:3]]
        terms_str = ", ".join(terms)[:48]

        print(f"{cluster_id:<10} {gap_score:<8.2f} {ngs_score:<8} {gap_label:<20} {terms_str}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
    parser.add_argument("--cluster", type=int, default=None,
                        help="Analyze specific cluster only")
    parser.add_argument("--top-terms", type=int, default=10,
                        help="Number of top TF-IDF terms to show (default: 10)")
    parser.add_argument("--summary-only", action="store_true",
                        help="Show only summary table, not detailed reports")

    args = parser.parse_args()

    print(f"Connecting to database '{args.dbname}' ...")
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        # Load gap scores
        cur.execute("""
            SELECT cluster_id, medical_count, vet_count, total_count, gap_score, gap_label
            FROM cluster_gap_scores
        """)
        gap_scores = {
            row[0]: {
                "medical_count": row[1],
                "vet_count": row[2],
                "total_count": row[3],
                "gap_score": row[4],
                "gap_label": row[5],
            }
            for row in cur.fetchall()
        }

        # Load chunks
        print(f"Loading chunks ...")
        chunks = load_cluster_chunks(cur, args.cluster)
        print(f"  Loaded {len(chunks)} chunks")

        if not chunks:
            print("No chunks found. Run cluster_topics.py first.")
            return

        # TF-IDF analysis
        print(f"Computing TF-IDF ...")
        top_terms = compute_tfidf_per_cluster(chunks, args.top_terms)

        # NGS keyword analysis
        print(f"Analyzing NGS keywords ...")
        keyword_counts = count_ngs_keywords(chunks)
        ngs_scores = ngs_relevance_score(keyword_counts)

        # Representative chunks
        print(f"Selecting representative chunks ...")
        representatives = get_representative_chunks(chunks, n=5)

        # Print results
        if args.summary_only:
            print_summary_table(top_terms, ngs_scores, gap_scores)
        else:
            print_summary_table(top_terms, ngs_scores, gap_scores)

            cluster_ids = [args.cluster] if args.cluster is not None else sorted(top_terms.keys())
            for cluster_id in cluster_ids:
                print_cluster_report(cluster_id, top_terms, keyword_counts, representatives, gap_scores)

        print(f"\nDone!")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
