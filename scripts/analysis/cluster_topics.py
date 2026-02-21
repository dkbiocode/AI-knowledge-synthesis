"""
cluster_topics.py

Cluster embedded chunks using HDBSCAN to identify topic groups and compute
medical-veterinary gap scores.

Workflow:
  1. Load all embeddings from database (review_chunks + paper_chunks)
  2. Run HDBSCAN clustering (cosine metric)
  3. Compute UMAP 2D projection for visualization
  4. Calculate gap scores per cluster
  5. Save results to database (chunk_clusters, cluster_gap_scores)
  6. Generate visualizations (UMAP scatter plots)

Usage:
  conda activate openai
  python cluster_topics.py
  python cluster_topics.py --min-cluster-size 30 --plot
  python cluster_topics.py --dry-run  # show params without running
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

import hdbscan
from umap import UMAP
import matplotlib.pyplot as plt
from sklearn.metrics import silhouette_score


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

def load_embeddings(cur):
    """
    Load all embeddings from review_chunks and paper_chunks.
    Returns: (embeddings_matrix, metadata_list)
      embeddings_matrix: np.array shape (N, 1536)
      metadata_list: list of dicts with keys: chunk_id, chunk_type, domain, heading
    """
    print("Loading embeddings from database ...")

    # Review chunks
    cur.execute("""
        SELECT
            'review_' || rc.id as chunk_id,
            'review' as chunk_type,
            rs.domain,
            rc.heading,
            rc.embedding
        FROM review_chunks rc
        JOIN review_sources rs ON rs.id = rc.source_id
        WHERE rc.embedding IS NOT NULL
        ORDER BY rc.id
    """)
    review_rows = cur.fetchall()

    # Paper chunks
    cur.execute("""
        SELECT
            'paper_' || pc.id as chunk_id,
            'paper' as chunk_type,
            p.domain,
            pc.heading,
            pc.embedding
        FROM paper_chunks pc
        JOIN papers p ON p.id = pc.paper_id
        WHERE pc.embedding IS NOT NULL
        ORDER BY pc.id
    """)
    paper_rows = cur.fetchall()

    all_rows = review_rows + paper_rows
    print(f"  Loaded {len(all_rows)} chunks ({len(review_rows)} review + {len(paper_rows)} paper)")

    # Parse embeddings and metadata
    embeddings = []
    metadata = []

    for chunk_id, chunk_type, domain, heading, embedding_str in all_rows:
        # Parse pgvector format: "[0.1,0.2,...]"
        embedding = np.array([float(x) for x in embedding_str.strip("[]").split(",")])
        embeddings.append(embedding)
        metadata.append({
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "domain": domain,
            "heading": heading,
        })

    embeddings_matrix = np.vstack(embeddings)
    print(f"  Embeddings shape: {embeddings_matrix.shape}")

    # Domain breakdown
    domain_counts = Counter(m["domain"] for m in metadata)
    for domain, count in sorted(domain_counts.items()):
        print(f"    {domain}: {count}")

    return embeddings_matrix, metadata


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def run_clustering(embeddings, min_cluster_size, min_samples):
    """
    Run HDBSCAN clustering on embeddings.
    Returns: cluster_labels (np.array of cluster IDs, -1 for noise)
    """
    print(f"\nRunning HDBSCAN clustering ...")
    print(f"  min_cluster_size: {min_cluster_size}")
    print(f"  min_samples: {min_samples}")

    # L2 normalize embeddings (euclidean on normalized = cosine similarity)
    embeddings_norm = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric='euclidean',
        cluster_selection_method='eom',
        core_dist_n_jobs=-1,  # Use all CPU cores
    )

    cluster_labels = clusterer.fit_predict(embeddings_norm)

    n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
    n_noise = np.sum(cluster_labels == -1)

    print(f"  Found {n_clusters} clusters")
    print(f"  Noise points: {n_noise} ({100*n_noise/len(cluster_labels):.1f}%)")

    # Cluster size distribution
    cluster_sizes = Counter(cluster_labels)
    if -1 in cluster_sizes:
        del cluster_sizes[-1]  # Remove noise from size stats

    if cluster_sizes:
        sizes = sorted(cluster_sizes.values(), reverse=True)
        print(f"  Cluster sizes: min={min(sizes)}, max={max(sizes)}, median={np.median(sizes):.0f}")

    # Silhouette score (excluding noise)
    if n_clusters > 1:
        mask = cluster_labels != -1
        if np.sum(mask) > 100:  # Only compute if enough non-noise points
            score = silhouette_score(embeddings_norm[mask], cluster_labels[mask], metric='euclidean', sample_size=1000)
            print(f"  Silhouette score: {score:.3f}")

    return cluster_labels


# ---------------------------------------------------------------------------
# UMAP dimensionality reduction
# ---------------------------------------------------------------------------

def run_umap(embeddings, n_neighbors, min_dist):
    """
    Reduce embeddings to 2D using UMAP.
    Returns: embedding_2d (np.array shape (N, 2))
    """
    print(f"\nRunning UMAP dimensionality reduction ...")
    print(f"  n_neighbors: {n_neighbors}")
    print(f"  min_dist: {min_dist}")

    reducer = UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric='cosine',
        random_state=42,
    )

    embedding_2d = reducer.fit_transform(embeddings)
    print(f"  UMAP embedding shape: {embedding_2d.shape}")

    return embedding_2d


# ---------------------------------------------------------------------------
# Gap score calculation
# ---------------------------------------------------------------------------

def compute_gap_scores(cluster_labels, metadata):
    """
    Compute medical-veterinary gap scores for each cluster.
    Returns: dict {cluster_id: gap_stats}
    """
    print(f"\nComputing gap scores ...")

    gap_scores = {}
    unique_clusters = sorted(set(cluster_labels))

    for cluster_id in unique_clusters:
        mask = cluster_labels == cluster_id
        cluster_metadata = [m for i, m in enumerate(metadata) if mask[i]]

        domain_counts = Counter(m["domain"] for m in cluster_metadata)
        medical_count = domain_counts.get("medical", 0)
        vet_count = domain_counts.get("veterinary", 0)
        both_count = domain_counts.get("both", 0)
        total_count = len(cluster_metadata)

        # Compute gap score
        if medical_count > 0 and vet_count > 0:
            gap_score = np.log2(medical_count / vet_count)
        elif medical_count > 0:
            gap_score = 10.0  # Medical-only
        elif vet_count > 0:
            gap_score = -10.0  # Vet-only
        else:
            gap_score = 0.0  # Both-only (rare)

        # Gap label
        if gap_score >= 10:
            gap_label = "medical-only"
        elif gap_score > 2:
            gap_label = "medical-dominated"
        elif gap_score > 1:
            gap_label = "medical-leaning"
        elif gap_score >= -1:
            gap_label = "balanced"
        elif gap_score >= -2:
            gap_label = "vet-leaning"
        elif gap_score > -10:
            gap_label = "vet-dominated"
        else:
            gap_label = "vet-only"

        gap_scores[cluster_id] = {
            "cluster_id": cluster_id,
            "medical_count": medical_count,
            "vet_count": vet_count,
            "both_count": both_count,
            "total_count": total_count,
            "gap_score": gap_score,
            "gap_label": gap_label,
        }

    # Summary
    label_counts = Counter(g["gap_label"] for g in gap_scores.values())
    print(f"  Gap label distribution:")
    for label in ["medical-only", "medical-dominated", "medical-leaning", "balanced",
                  "vet-leaning", "vet-dominated", "vet-only"]:
        if label in label_counts:
            print(f"    {label}: {label_counts[label]}")

    return gap_scores


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------

def save_results(cur, cluster_labels, embedding_2d, metadata, gap_scores):
    """
    Save clustering results to database.
    """
    print(f"\nSaving results to database ...")

    # Clear existing results
    cur.execute("DELETE FROM chunk_clusters")
    cur.execute("DELETE FROM cluster_gap_scores")
    cur.execute("DELETE FROM cluster_representatives")

    # Insert chunk_clusters
    rows = []
    for i, (cluster_id, meta) in enumerate(zip(cluster_labels, metadata)):
        rows.append((
            meta["chunk_id"],
            meta["chunk_type"],
            int(cluster_id),
            float(embedding_2d[i, 0]),
            float(embedding_2d[i, 1]),
        ))

    execute_values(cur, """
        INSERT INTO chunk_clusters (chunk_id, chunk_type, cluster_id, umap_x, umap_y)
        VALUES %s
    """, rows)
    print(f"  Inserted {len(rows)} rows into chunk_clusters")

    # Insert cluster_gap_scores
    rows = []
    for cluster_id, stats in gap_scores.items():
        if cluster_id == -1:  # Skip noise
            continue
        rows.append((
            int(stats["cluster_id"]),
            int(stats["medical_count"]),
            int(stats["vet_count"]),
            int(stats["both_count"]),
            int(stats["total_count"]),
            float(stats["gap_score"]),
            stats["gap_label"],
        ))

    if rows:
        execute_values(cur, """
            INSERT INTO cluster_gap_scores
                (cluster_id, medical_count, vet_count, both_count, total_count, gap_score, gap_label)
            VALUES %s
        """, rows)
        print(f"  Inserted {len(rows)} rows into cluster_gap_scores")


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def plot_clusters(embedding_2d, cluster_labels, metadata, gap_scores, output_dir):
    """
    Generate UMAP scatter plots.
    """
    print(f"\nGenerating visualizations ...")
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Extract domains
    domains = np.array([m["domain"] for m in metadata])

    # Plot 1: Color by domain
    plt.figure(figsize=(10, 8))
    for domain, color in [("medical", "blue"), ("veterinary", "green"), ("both", "orange")]:
        mask = domains == domain
        plt.scatter(embedding_2d[mask, 0], embedding_2d[mask, 1],
                   c=color, label=domain, alpha=0.5, s=10)
    plt.title("UMAP Projection - Colored by Domain", fontsize=14)
    plt.xlabel("UMAP 1")
    plt.ylabel("UMAP 2")
    plt.legend()
    plt.tight_layout()
    plot1_path = output_dir / "umap_by_domain.png"
    plt.savefig(plot1_path, dpi=150)
    print(f"  Saved: {plot1_path}")
    plt.close()

    # Plot 2: Color by cluster
    plt.figure(figsize=(12, 10))
    unique_clusters = np.unique(cluster_labels)
    colors = plt.cm.tab20(np.linspace(0, 1, len(unique_clusters)))

    for cluster_id, color in zip(unique_clusters, colors):
        mask = cluster_labels == cluster_id
        label = f"Cluster {cluster_id}" if cluster_id != -1 else "Noise"
        plt.scatter(embedding_2d[mask, 0], embedding_2d[mask, 1],
                   c=[color], label=label, alpha=0.6, s=15)

    plt.title("UMAP Projection - Colored by Cluster", fontsize=14)
    plt.xlabel("UMAP 1")
    plt.ylabel("UMAP 2")
    # Legend with limited entries
    handles, labels = plt.gca().get_legend_handles_labels()
    plt.legend(handles[:15], labels[:15], loc='upper right', fontsize=8)
    plt.tight_layout()
    plot2_path = output_dir / "umap_by_cluster.png"
    plt.savefig(plot2_path, dpi=150)
    print(f"  Saved: {plot2_path}")
    plt.close()

    # Plot 3: Color by gap score
    plt.figure(figsize=(10, 8))
    gap_values = np.array([gap_scores.get(cid, {"gap_score": 0})["gap_score"]
                           for cid in cluster_labels])

    # Clip extreme values for better visualization
    gap_clipped = np.clip(gap_values, -5, 5)

    scatter = plt.scatter(embedding_2d[:, 0], embedding_2d[:, 1],
                         c=gap_clipped, cmap='RdYlGn_r', alpha=0.6, s=15,
                         vmin=-5, vmax=5)
    plt.colorbar(scatter, label="Gap Score (red=medical, green=vet)")
    plt.title("UMAP Projection - Colored by Gap Score", fontsize=14)
    plt.xlabel("UMAP 1")
    plt.ylabel("UMAP 2")
    plt.tight_layout()
    plot3_path = output_dir / "umap_by_gap_score.png"
    plt.savefig(plot3_path, dpi=150)
    print(f"  Saved: {plot3_path}")
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
    parser.add_argument("--min-cluster-size", type=int, default=20,
                        help="HDBSCAN min_cluster_size (default: 20)")
    parser.add_argument("--min-samples", type=int, default=10,
                        help="HDBSCAN min_samples (default: 10)")
    parser.add_argument("--umap-neighbors", type=int, default=15,
                        help="UMAP n_neighbors (default: 15)")
    parser.add_argument("--umap-min-dist", type=float, default=0.1,
                        help="UMAP min_dist (default: 0.1)")
    parser.add_argument("--plot", action="store_true",
                        help="Generate UMAP visualizations")
    parser.add_argument("--plot-dir", default="cluster_plots",
                        help="Output directory for plots (default: cluster_plots)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show parameters without running")

    args = parser.parse_args()

    if args.dry_run:
        print("Dry-run mode: showing parameters\n")
        print(f"Database: {args.dbname}")
        print(f"HDBSCAN min_cluster_size: {args.min_cluster_size}")
        print(f"HDBSCAN min_samples: {args.min_samples}")
        print(f"UMAP n_neighbors: {args.umap_neighbors}")
        print(f"UMAP min_dist: {args.umap_min_dist}")
        print(f"Generate plots: {args.plot}")
        print(f"Plot directory: {args.plot_dir}")
        return

    # Connect to database
    print(f"Connecting to database '{args.dbname}' ...\n")
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        # Load embeddings
        embeddings, metadata = load_embeddings(cur)

        # Run clustering
        cluster_labels = run_clustering(embeddings, args.min_cluster_size, args.min_samples)

        # Run UMAP
        embedding_2d = run_umap(embeddings, args.umap_neighbors, args.umap_min_dist)

        # Compute gap scores
        gap_scores = compute_gap_scores(cluster_labels, metadata)

        # Save to database
        save_results(cur, cluster_labels, embedding_2d, metadata, gap_scores)
        conn.commit()

        # Generate plots
        if args.plot:
            plot_clusters(embedding_2d, cluster_labels, metadata, gap_scores, args.plot_dir)

        print("\nDone!")
        print(f"\nQuery cluster results:")
        print(f"  psql {args.dbname} -c 'SELECT * FROM cluster_gap_scores ORDER BY gap_score DESC;'")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
