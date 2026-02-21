#!/usr/bin/env python3
"""
plot_cluster0_umap.py

Flexible UMAP visualization tool for Cluster 0 with multiple coloring and labeling options.

Usage:
    # Color by domain (medical=blue, veterinary=red)
    python plot_cluster0_umap.py --color-by domain

    # Color by sub-cluster
    python plot_cluster0_umap.py --color-by subcluster

    # Color by pathogen type
    python plot_cluster0_umap.py --color-by pathogen

    # Add NGS term labels around clusters
    python plot_cluster0_umap.py --color-by domain --add-labels ngs

    # Add pathogen labels
    python plot_cluster0_umap.py --color-by subcluster --add-labels pathogen

    # Custom output file
    python plot_cluster0_umap.py --color-by domain --output cluster0_domain.png

    # Multiple plots at once
    python plot_cluster0_umap.py --all
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import numpy as np
import psycopg2
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from sklearn.feature_extraction.text import TfidfVectorizer


def get_conn(dbname: str):
    params = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", 5432)),
        "user": os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname": dbname,
    }
    return psycopg2.connect(**{k: v for k, v in params.items() if v != ""})


def load_cluster0_visualization_data(cur):
    """Load UMAP coordinates and metadata for Cluster 0."""
    print("Loading Cluster 0 data for visualization ...")

    query = """
        SELECT
            cc.chunk_id,
            cc.umap_x,
            cc.umap_y,
            COALESCE(rs.domain, p.domain) as domain,
            COALESCE(rc.heading, pc.heading) as heading,
            COALESCE(rc.text, pc.text) as text,
            sc.subcluster_id,
            sc.pathogen_type
        FROM chunk_clusters cc
        LEFT JOIN review_chunks rc ON cc.chunk_id = 'review_' || rc.id::text AND cc.chunk_type = 'review'
        LEFT JOIN review_sources rs ON rc.source_id = rs.id
        LEFT JOIN paper_chunks pc ON cc.chunk_id = 'paper_' || pc.id::text AND cc.chunk_type = 'paper'
        LEFT JOIN papers p ON pc.paper_id = p.id
        LEFT JOIN cluster0_subclusters sc ON cc.chunk_id = sc.chunk_id
        WHERE cc.cluster_id = 0
        ORDER BY cc.chunk_id
    """

    cur.execute(query)
    rows = cur.fetchall()

    print(f"  Loaded {len(rows)} chunks")

    data = {
        'chunk_ids': [row[0] for row in rows],
        'umap_x': np.array([row[1] for row in rows]),
        'umap_y': np.array([row[2] for row in rows]),
        'domain': [row[3] for row in rows],
        'heading': [row[4] for row in rows],
        'text': [row[5] for row in rows],
        'subcluster': [row[6] if row[6] is not None else -1 for row in rows],
        'pathogen': [row[7] if row[7] else 'unknown' for row in rows],
    }

    return data


def extract_ngs_keywords(texts, n_keywords=60):
    """
    Extract top NGS-related keywords using TF-IDF.
    Returns dict mapping keyword -> count
    """
    # NGS-specific keyword list (from your analysis)
    ngs_keywords = [
        'mngs', 'metagenomic', 'metagenomics',
        'wgs', 'whole genome', 'genome sequencing',
        'amplicon', '16s', 'rrna', 'its',
        'targeted', 'panel', 'enrichment',
        'illumina', 'miseq', 'nextseq', 'hiseq', 'novaseq',
        'nanopore', 'minion', 'oxford',
        'pacbio', 'smrt',
        'bacteria', 'bacterial', 'virus', 'viral',
        'fungus', 'fungi', 'fungal', 'parasite', 'parasitic',
        'csf', 'cerebrospinal', 'meningitis', 'encephalitis',
        'sepsis', 'bacteremia', 'bloodstream',
        'respiratory', 'pneumonia', 'balf',
        'pathogen', 'detection', 'identification',
        'sensitivity', 'specificity', 'diagnostic',
        'sequencing', 'ngs', 'reads', 'coverage',
    ]

    # Count keyword occurrences
    keyword_counts = Counter()
    for text in texts:
        if not text:
            continue
        text_lower = text.lower()
        for kw in ngs_keywords:
            keyword_counts[kw] += text_lower.count(kw)

    return keyword_counts


def compute_cluster_centroids(data, cluster_field='subcluster'):
    """Compute centroid coordinates for each cluster."""
    centroids = {}
    cluster_ids = set(data[cluster_field])

    for cluster_id in cluster_ids:
        if cluster_id == -1:  # Skip noise
            continue

        mask = np.array(data[cluster_field]) == cluster_id
        x_coords = data['umap_x'][mask]
        y_coords = data['umap_y'][mask]

        centroids[cluster_id] = {
            'x': np.mean(x_coords),
            'y': np.mean(y_coords),
            'count': len(x_coords)
        }

    return centroids


def get_cluster_keywords(data, cluster_field='subcluster', top_n=3):
    """Get top NGS keywords for each cluster."""
    cluster_keywords = {}
    cluster_ids = set(data[cluster_field])

    for cluster_id in cluster_ids:
        if cluster_id == -1:
            continue

        mask = [data[cluster_field][i] == cluster_id for i in range(len(data[cluster_field]))]
        cluster_texts = [data['text'][i] for i in range(len(data['text'])) if mask[i]]

        keyword_counts = extract_ngs_keywords(cluster_texts)
        top_keywords = [kw for kw, _ in keyword_counts.most_common(top_n)]

        cluster_keywords[cluster_id] = top_keywords

    return cluster_keywords


def plot_by_domain(data, output_path='cluster0_domain.png'):
    """Plot UMAP colored by domain (medical=blue, veterinary=red)."""
    print(f"\nGenerating domain plot -> {output_path}")

    fig, ax = plt.subplots(figsize=(12, 10))

    # Separate by domain
    medical_mask = np.array(data['domain']) == 'medical'
    vet_mask = np.array(data['domain']) == 'veterinary'

    # Plot
    ax.scatter(
        data['umap_x'][medical_mask],
        data['umap_y'][medical_mask],
        c='blue', alpha=0.4, s=10, label='Medical'
    )
    ax.scatter(
        data['umap_x'][vet_mask],
        data['umap_y'][vet_mask],
        c='red', alpha=0.4, s=10, label='Veterinary'
    )

    ax.set_xlabel('UMAP 1', fontsize=12)
    ax.set_ylabel('UMAP 2', fontsize=12)
    ax.set_title('Cluster 0: Medical vs Veterinary NGS Literature', fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=11)
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved to {output_path}")


def plot_by_subcluster(data, add_labels=None, output_path='cluster0_subclusters.png'):
    """Plot UMAP colored by sub-cluster."""
    print(f"\nGenerating sub-cluster plot -> {output_path}")

    fig, ax = plt.subplots(figsize=(14, 10))

    # Get unique subclusters
    unique_clusters = sorted(set(data['subcluster']))
    n_clusters = len([c for c in unique_clusters if c != -1])

    # Color map
    cmap = plt.colormaps.get_cmap('tab20').resampled(n_clusters)
    colors = {}
    color_idx = 0
    for cluster_id in unique_clusters:
        if cluster_id == -1:
            colors[cluster_id] = 'lightgray'
        else:
            colors[cluster_id] = cmap(color_idx)
            color_idx += 1

    # Plot each cluster
    for cluster_id in unique_clusters:
        mask = np.array(data['subcluster']) == cluster_id
        label = f'Sub-cluster {cluster_id}' if cluster_id != -1 else 'Noise'

        ax.scatter(
            data['umap_x'][mask],
            data['umap_y'][mask],
            c=[colors[cluster_id]],
            alpha=0.5 if cluster_id != -1 else 0.2,
            s=15 if cluster_id != -1 else 5,
            label=label
        )

    # Add labels if requested
    if add_labels == 'pathogen':
        centroids = compute_cluster_centroids(data, 'subcluster')
        for cluster_id, centroid in centroids.items():
            # Find dominant pathogen type for this cluster
            mask = np.array(data['subcluster']) == cluster_id
            pathogen_types = [data['pathogen'][i] for i in range(len(data['pathogen'])) if mask[i]]
            dominant_pathogen = Counter(pathogen_types).most_common(1)[0][0]

            ax.annotate(
                dominant_pathogen.upper(),
                xy=(centroid['x'], centroid['y']),
                fontsize=10, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='black', alpha=0.7)
            )

    elif add_labels == 'ngs':
        centroids = compute_cluster_centroids(data, 'subcluster')
        cluster_keywords = get_cluster_keywords(data, 'subcluster', top_n=2)

        for cluster_id, centroid in centroids.items():
            keywords = cluster_keywords.get(cluster_id, [])
            label_text = ', '.join(keywords[:2]) if keywords else f'C{cluster_id}'

            ax.annotate(
                label_text,
                xy=(centroid['x'], centroid['y']),
                fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', edgecolor='black', alpha=0.7)
            )

    ax.set_xlabel('UMAP 1', fontsize=12)
    ax.set_ylabel('UMAP 2', fontsize=12)
    ax.set_title('Cluster 0: Sub-clusters (Pathogen-Centric)', fontsize=14, fontweight='bold')
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved to {output_path}")


def plot_by_pathogen(data, output_path='cluster0_pathogen.png'):
    """Plot UMAP colored by pathogen type."""
    print(f"\nGenerating pathogen plot -> {output_path}")

    fig, ax = plt.subplots(figsize=(12, 10))

    # Color map for pathogen types
    pathogen_colors = {
        'bacteria': '#1f77b4',  # blue
        'virus': '#ff7f0e',     # orange
        'fungus': '#2ca02c',    # green
        'parasite': '#d62728',  # red
        'mixed': '#9467bd',     # purple
        'unknown': '#7f7f7f'    # gray
    }

    # Plot each pathogen type
    for pathogen_type in pathogen_colors.keys():
        mask = np.array(data['pathogen']) == pathogen_type
        if not mask.any():
            continue

        ax.scatter(
            data['umap_x'][mask],
            data['umap_y'][mask],
            c=pathogen_colors[pathogen_type],
            alpha=0.5,
            s=12,
            label=pathogen_type.capitalize()
        )

    ax.set_xlabel('UMAP 1', fontsize=12)
    ax.set_ylabel('UMAP 2', fontsize=12)
    ax.set_title('Cluster 0: Pathogen Type Distribution', fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=11)
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved to {output_path}")


def plot_domain_with_ngs_labels(data, output_path='cluster0_domain_ngs.png'):
    """Plot domain colors with NGS term labels."""
    print(f"\nGenerating domain plot with NGS labels -> {output_path}")

    fig, ax = plt.subplots(figsize=(14, 10))

    # Plot by domain
    medical_mask = np.array(data['domain']) == 'medical'
    vet_mask = np.array(data['domain']) == 'veterinary'

    ax.scatter(
        data['umap_x'][medical_mask],
        data['umap_y'][medical_mask],
        c='blue', alpha=0.3, s=10, label='Medical'
    )
    ax.scatter(
        data['umap_x'][vet_mask],
        data['umap_y'][vet_mask],
        c='red', alpha=0.3, s=10, label='Veterinary'
    )

    # Add NGS term labels at sub-cluster centroids
    if 'subcluster' in data and any(x != -1 for x in data['subcluster']):
        centroids = compute_cluster_centroids(data, 'subcluster')
        cluster_keywords = get_cluster_keywords(data, 'subcluster', top_n=2)

        for cluster_id, centroid in centroids.items():
            keywords = cluster_keywords.get(cluster_id, [])
            if not keywords:
                continue

            label_text = '\n'.join(keywords[:2])

            ax.annotate(
                label_text,
                xy=(centroid['x'], centroid['y']),
                fontsize=8, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='lightyellow', edgecolor='black', alpha=0.8),
                ha='center'
            )

    ax.set_xlabel('UMAP 1', fontsize=12)
    ax.set_ylabel('UMAP 2', fontsize=12)
    ax.set_title('Cluster 0: Medical (Blue) vs Veterinary (Red) with NGS Terms', fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=11)
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
    parser.add_argument("--color-by", choices=['domain', 'subcluster', 'pathogen'],
                        help="Coloring scheme for the plot")
    parser.add_argument("--add-labels", choices=['ngs', 'pathogen'],
                        help="Add labels to the plot (NGS terms or pathogen types)")
    parser.add_argument("--output", default=None,
                        help="Output file path (default: auto-generated)")
    parser.add_argument("--all", action="store_true",
                        help="Generate all standard plots")

    args = parser.parse_args()

    # Connect to database
    conn = get_conn(args.dbname)
    cur = conn.cursor()

    try:
        # Load data
        data = load_cluster0_visualization_data(cur)

        if args.all:
            # Generate all standard plots
            print("\nGenerating all standard plots ...")
            plot_by_domain(data, 'cluster0_domain.png')
            plot_by_pathogen(data, 'cluster0_pathogen.png')
            plot_domain_with_ngs_labels(data, 'cluster0_domain_ngs.png')

            if any(x != -1 for x in data['subcluster']):
                plot_by_subcluster(data, add_labels=None, output_path='cluster0_subclusters.png')
                plot_by_subcluster(data, add_labels='pathogen', output_path='cluster0_subclusters_pathogen.png')
                plot_by_subcluster(data, add_labels='ngs', output_path='cluster0_subclusters_ngs.png')
            else:
                print("  (No sub-cluster data available - run subcluster_cluster0.py first)")

        elif args.color_by:
            # Generate specific plot
            if args.output:
                output_path = args.output
            else:
                output_path = f"cluster0_{args.color_by}.png"

            if args.color_by == 'domain':
                if args.add_labels == 'ngs':
                    plot_domain_with_ngs_labels(data, output_path)
                else:
                    plot_by_domain(data, output_path)

            elif args.color_by == 'subcluster':
                if all(x == -1 for x in data['subcluster']):
                    print("ERROR: No sub-cluster data available. Run subcluster_cluster0.py first.")
                    sys.exit(1)
                plot_by_subcluster(data, add_labels=args.add_labels, output_path=output_path)

            elif args.color_by == 'pathogen':
                plot_by_pathogen(data, output_path)

        else:
            print("ERROR: Must specify --color-by or --all")
            parser.print_help()
            sys.exit(1)

        print("\n✓ Plotting complete!")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
