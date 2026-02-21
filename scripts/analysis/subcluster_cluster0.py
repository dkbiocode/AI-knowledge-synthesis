#!/usr/bin/env python3
"""
subcluster_cluster0.py

Sub-cluster Cluster 0 using pathogen-centric approach.

Strategy:
  1. Load all chunks from Cluster 0
  2. Classify chunks by pathogen mentions (bacteria, virus, fungus, parasite)
  3. Run tighter HDBSCAN clustering (smaller min_cluster_size)
  4. Store results in new table: cluster0_subclusters
  5. Generate visualizations

Usage:
  python subcluster_cluster0.py
  python subcluster_cluster0.py --min-cluster-size 15 --plot
"""

import argparse
import os
import sys
import re
from collections import Counter

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

import hdbscan
from umap import UMAP
import matplotlib.pyplot as plt


def get_conn(dbname: str):
    params = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", 5432)),
        "user": os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname": dbname,
    }
    return psycopg2.connect(**{k: v for k, v in params.items() if v != ""})


def load_cluster0_data(cur):
    """Load embeddings and metadata for all chunks in Cluster 0."""
    print("Loading Cluster 0 chunks from database ...")

    query = """
        SELECT
            cc.chunk_id,
            cc.chunk_type,
            COALESCE(rs.domain, p.domain) as domain,
            COALESCE(rc.heading, pc.heading) as heading,
            COALESCE(rc.text, pc.text) as text,
            COALESCE(rc.embedding, pc.embedding) as embedding,
            cc.umap_x,
            cc.umap_y
        FROM chunk_clusters cc
        LEFT JOIN review_chunks rc ON cc.chunk_id = 'review_' || rc.id::text AND cc.chunk_type = 'review'
        LEFT JOIN review_sources rs ON rc.source_id = rs.id
        LEFT JOIN paper_chunks pc ON cc.chunk_id = 'paper_' || pc.id::text AND cc.chunk_type = 'paper'
        LEFT JOIN papers p ON pc.paper_id = p.id
        WHERE cc.cluster_id = 0
        ORDER BY cc.chunk_id
    """

    cur.execute(query)
    rows = cur.fetchall()

    print(f"  Loaded {len(rows)} chunks from Cluster 0")

    # Convert to arrays
    # Parse embeddings (they come as strings from postgres, need to be converted)
    import json
    embeddings_list = []
    for row in rows:
        emb = row[5]
        if isinstance(emb, str):
            # Parse JSON string
            emb = json.loads(emb)
        embeddings_list.append(emb)

    embeddings = np.array(embeddings_list, dtype=np.float32)

    metadata = [
        {
            "chunk_id": row[0],
            "chunk_type": row[1],
            "domain": row[2],
            "heading": row[3],
            "text": row[4],
            "umap_x": row[6],
            "umap_y": row[7],
        }
        for row in rows
    ]

    return embeddings, metadata


def classify_pathogen_type(text: str) -> str:
    """
    Classify chunk by primary pathogen mention.
    Returns: 'bacteria', 'virus', 'fungus', 'parasite', 'mixed', or 'unknown'
    """
    if not text:
        return 'unknown'

    text_lower = text.lower()

    # Count mentions
    bacteria_count = len(re.findall(r'\bbacter[ia][a-z]*\b', text_lower))
    virus_count = len(re.findall(r'\bvir[ua][sl][a-z]*\b', text_lower))
    fungus_count = len(re.findall(r'\bfung[iu][s]?\b|\bmycoses\b|\byeast\b', text_lower))
    parasite_count = len(re.findall(r'\bparasite[s]?\b|\bprotozoa[n]?\b', text_lower))

    counts = {
        'bacteria': bacteria_count,
        'virus': virus_count,
        'fungus': fungus_count,
        'parasite': parasite_count,
    }

    # Filter non-zero counts
    non_zero = {k: v for k, v in counts.items() if v > 0}

    if len(non_zero) == 0:
        return 'unknown'
    elif len(non_zero) > 2:
        return 'mixed'
    elif len(non_zero) == 1:
        return list(non_zero.keys())[0]
    else:
        # Two pathogen types - check if one dominates (2x+)
        sorted_counts = sorted(non_zero.items(), key=lambda x: x[1], reverse=True)
        if sorted_counts[0][1] >= 2 * sorted_counts[1][1]:
            return sorted_counts[0][0]
        else:
            return 'mixed'


def cluster_pathogen_groups(embeddings, metadata, min_cluster_size=15, min_samples=10):
    """
    Sub-cluster Cluster 0 using HDBSCAN.
    Returns cluster labels.
    """
    print(f"\nRunning HDBSCAN sub-clustering ...")
    print(f"  min_cluster_size: {min_cluster_size}")
    print(f"  min_samples: {min_samples}")

    # Normalize embeddings (L2 norm)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings_norm = embeddings / norms

    # Run HDBSCAN
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric='euclidean',  # cosine distance via L2-normalized embeddings
        cluster_selection_method='eom',
        prediction_data=True
    )

    labels = clusterer.fit_predict(embeddings_norm)

    # Count clusters
    unique_labels = set(labels)
    n_clusters = len([l for l in unique_labels if l != -1])
    n_noise = list(labels).count(-1)

    print(f"\n  Found {n_clusters} sub-clusters")
    print(f"  Noise points: {n_noise} ({100*n_noise/len(labels):.1f}%)")

    # Show cluster sizes
    cluster_counts = Counter(labels)
    print(f"\n  Sub-cluster sizes:")
    for label in sorted(cluster_counts.keys()):
        if label == -1:
            print(f"    Noise: {cluster_counts[label]}")
        else:
            print(f"    Sub-cluster {label}: {cluster_counts[label]}")

    return labels


def save_subclusters(cur, metadata, labels, pathogen_types):
    """Save sub-cluster assignments to database."""
    print("\nSaving sub-cluster assignments to database ...")

    # Create table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cluster0_subclusters (
            id SERIAL PRIMARY KEY,
            chunk_id TEXT NOT NULL,
            chunk_type TEXT NOT NULL CHECK (chunk_type IN ('review', 'paper')),
            subcluster_id INTEGER NOT NULL,
            pathogen_type TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(chunk_id)
        );

        CREATE INDEX IF NOT EXISTS idx_cluster0_subclusters_chunk
            ON cluster0_subclusters(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_cluster0_subclusters_subcluster
            ON cluster0_subclusters(subcluster_id);
    """)

    # Delete existing data
    cur.execute("DELETE FROM cluster0_subclusters;")

    # Insert new data
    values = [
        (
            meta['chunk_id'],
            meta['chunk_type'],
            int(label),
            pathogen_type
        )
        for meta, label, pathogen_type in zip(metadata, labels, pathogen_types)
    ]

    execute_values(
        cur,
        """
        INSERT INTO cluster0_subclusters (chunk_id, chunk_type, subcluster_id, pathogen_type)
        VALUES %s
        """,
        values
    )

    print(f"  Saved {len(values)} sub-cluster assignments")


def compute_subcluster_stats(cur):
    """Compute and display statistics for each sub-cluster."""
    print("\nComputing sub-cluster statistics ...")

    query = """
        SELECT
            sc.subcluster_id,
            sc.pathogen_type,
            COUNT(*) as total_chunks,
            COUNT(CASE WHEN cc.chunk_type = 'review' THEN 1 END) as review_chunks,
            COUNT(CASE WHEN cc.chunk_type = 'paper' THEN 1 END) as paper_chunks,
            COUNT(CASE WHEN p.domain = 'medical' OR rs.domain = 'medical' THEN 1 END) as medical_chunks,
            COUNT(CASE WHEN p.domain = 'veterinary' OR rs.domain = 'veterinary' THEN 1 END) as vet_chunks
        FROM cluster0_subclusters sc
        LEFT JOIN chunk_clusters cc ON sc.chunk_id = cc.chunk_id
        LEFT JOIN review_chunks rc ON cc.chunk_id = 'review_' || rc.id::text AND cc.chunk_type = 'review'
        LEFT JOIN review_sources rs ON rc.source_id = rs.id
        LEFT JOIN paper_chunks pc ON cc.chunk_id = 'paper_' || pc.id::text AND cc.chunk_type = 'paper'
        LEFT JOIN papers p ON pc.paper_id = p.id
        GROUP BY sc.subcluster_id, sc.pathogen_type
        ORDER BY sc.subcluster_id
    """

    cur.execute(query)
    rows = cur.fetchall()

    print("\n" + "=" * 80)
    print("SUB-CLUSTER STATISTICS")
    print("=" * 80)

    for row in rows:
        subcluster_id, pathogen_type, total, review, paper, medical, vet = row

        if subcluster_id == -1:
            cluster_name = "Noise"
        else:
            cluster_name = f"Sub-cluster {subcluster_id}"

        med_pct = 100 * medical / total if total > 0 else 0
        vet_pct = 100 * vet / total if total > 0 else 0
        gap_score = np.log2(medical / vet) if vet > 0 else float('inf')

        print(f"\n{cluster_name}")
        print(f"  Pathogen (primary): {pathogen_type or 'mixed/unknown'}")
        print(f"  Total chunks: {total}")
        print(f"  Medical: {medical} ({med_pct:.1f}%)")
        print(f"  Veterinary: {vet} ({vet_pct:.1f}%)")
        print(f"  Gap score: {gap_score:.2f}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
    parser.add_argument("--min-cluster-size", type=int, default=20,
                        help="HDBSCAN min_cluster_size (default: 20)")
    parser.add_argument("--min-samples", type=int, default=10,
                        help="HDBSCAN min_samples (default: 10)")
    parser.add_argument("--plot", action="store_true",
                        help="Generate UMAP plots after clustering")

    args = parser.parse_args()

    print("=" * 80)
    print("CLUSTER 0 SUB-CLUSTERING (Pathogen-Centric)")
    print("=" * 80)

    # Connect to database
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        # Load data
        embeddings, metadata = load_cluster0_data(cur)

        # Classify pathogen types
        print("\nClassifying chunks by pathogen type ...")
        pathogen_types = [classify_pathogen_type(meta['text']) for meta in metadata]
        pathogen_counts = Counter(pathogen_types)

        print("\nPathogen type distribution:")
        for pathogen_type, count in pathogen_counts.most_common():
            pct = 100 * count / len(pathogen_types)
            print(f"  {pathogen_type}: {count} ({pct:.1f}%)")

        # Run sub-clustering
        labels = cluster_pathogen_groups(
            embeddings, metadata,
            args.min_cluster_size, args.min_samples
        )

        # Save to database
        save_subclusters(cur, metadata, labels, pathogen_types)
        conn.commit()

        # Compute statistics
        compute_subcluster_stats(cur)

        print("\n✓ Sub-clustering complete!")

        if args.plot:
            print("\nPlots can be generated using plot_cluster0_umap.py")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
