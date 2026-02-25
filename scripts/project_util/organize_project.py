"""
Organize project directory structure.

This script creates a clean directory structure and moves files to appropriate locations.
Run with --dry-run to preview changes without making them.
"""

import os
import shutil
import argparse
import subprocess
from pathlib import Path


# Define the organization mapping
ORGANIZATION = {
    # Scripts - Data Ingestion
    'scripts/data_ingestion': [
        'add_pmc_article.py',
        'add_pmc_review_article.py',
        'download_pmc.py',
        'download_pmc_from_file.py',
        'bulk_add_papers.sh',
        'process_papers_pipeline.sh',
        'process_pmc_chunks_to_openai.sh',
        'enter_paper_embeddings_into_db.sh',
        'embed_chunks.py',
        'load_chunks.py',
        'load_paper_chunks.py',
        'chunk_article.py',
        'chunk_vet_review.py',
    ],

    # Scripts - Analysis
    'scripts/analysis': [
        'cluster_topics.py',
        'analyze_cluster_topics.py',
        'subcluster_cluster0.py',
        'plot_cluster0_umap.py',
        'extract_protocols.py',
        'filter_admin_sections.py',
    ],

    # Scripts - Query
    'scripts/query': [
        'query_kb.py',
        'search_protocols.py',
        'search_references.py',
        'web_query.py',
    ],

    # Scripts - Utilities
    'scripts/utilities': [
        'cleanup_duplicate_chunks.py',
        'debug_search.py',
        'export_citations.py',
        'parse_pdf_article.py',
        'parse_science_pdf.py',
        'setup_db.py',
        'mb.py',
    ],

    # Source code
    'src': [
        'query_analyzer.py',
        'admin_blacklist.py',
        'extractors',  # Move entire directory
    ],

    # SQL
    'sql': [
        'create_schema.sql',
        'migrate_v2.sql',
        'cluster_schema.sql',
    ],

    # Documentation
    'docs': [
        'gap_analysis_final.md',
        'gap_analysis_report.md',
        'cluster_ngs_summary.md',
        'PERSPECTIVE.md',
        'CLUSTERING_STRATEGY.md',
        'correction_to_PMC11171117.txt',
        'postgres.brew.installnotes.txt',
        'example-answer.txt',
    ],

    # Figures
    'figures': [
        'cluster0_domain.png',
        'cluster0_domain_ngs.png',
        'cluster0_pathogen.png',
        'cluster0_subclusters.png',
        'cluster0_subclusters_ngs.png',
        'cluster0_subclusters_pathogen.png',
    ],

    # Data - Raw HTML
    'data/raw/html_medical': [
        'article.html',
        'fcimb-14-1458316.html',
        'main-article-body.html',
    ],

    'data/raw/html_vet': [
        'PMC11171117.html',
    ],

    # Data - Processed
    'data/processed/chunks': [
        'chunks.json',
        'vet_chunks.json',
        'rechunk.json',
    ],

    'data/processed/embeddings': [
        'embeddings.json',
        'vet_embeddings.json',
    ],

    'data/processed/metadata': [
        'download_log.json',
        'vet_download_log.json',
        'reference_index.json',
        'references_extracted.tsv',
        'vet_pmc_refs.json',
        'vet_references.json',
        'gap_scores.tsv',
    ],

    # Directories to move
    'data/raw': [
        'html',
        'PDFs',
        'PMC11171117_files',
    ],

    'data/processed': [
        'pmc_chunks',
        'pmc_chunks_vet',
        'pmc_chunks_vet_test',
        'pmc_chunks_embedding',
    ],

    'figures': [
        'cluster_plots',
    ],
}


def create_directories(base_path, dry_run=False):
    """Create the new directory structure."""
    dirs_to_create = [
        'scripts/data_ingestion',
        'scripts/analysis',
        'scripts/query',
        'scripts/utilities',
        'src',
        'sql',
        'data/raw',
        'data/processed/chunks',
        'data/processed/embeddings',
        'data/processed/metadata',
        'figures',
        'docs',
    ]

    for dir_path in dirs_to_create:
        full_path = base_path / dir_path
        if not full_path.exists():
            if dry_run:
                print(f"[DRY RUN] Would create: {dir_path}/")
            else:
                full_path.mkdir(parents=True, exist_ok=True)
                print(f"✓ Created: {dir_path}/")


def is_git_tracked(file_path):
    """Check if a file is tracked by git."""
    try:
        result = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', str(file_path)],
            cwd=file_path.parent if file_path.is_file() else file_path,
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def move_files(base_path, dry_run=False):
    """Move files to their new locations using git mv for tracked files."""
    moved_count = 0
    missing_count = 0
    git_moved_count = 0

    for dest_dir, files in ORGANIZATION.items():
        for filename in files:
            src = base_path / filename
            dest = base_path / dest_dir / filename

            if src.exists():
                is_tracked = is_git_tracked(src)

                if dry_run:
                    move_type = "[GIT MV]" if is_tracked else "[MOVE]"
                    print(f"[DRY RUN] {move_type} {filename} → {dest_dir}/")
                else:
                    # Create destination directory if it doesn't exist
                    dest.parent.mkdir(parents=True, exist_ok=True)

                    # Use git mv for tracked files, regular move for untracked
                    if is_tracked:
                        try:
                            subprocess.run(
                                ['git', 'mv', str(src), str(dest)],
                                check=True,
                                capture_output=True,
                                text=True
                            )
                            print(f"✓ [GIT] Moved: {filename} → {dest_dir}/")
                            git_moved_count += 1
                        except subprocess.CalledProcessError as e:
                            print(f"⚠ Git mv failed for {filename}: {e.stderr}")
                            # Fallback to regular move
                            shutil.move(str(src), str(dest))
                            print(f"✓ [FALLBACK] Moved: {filename} → {dest_dir}/")
                    else:
                        shutil.move(str(src), str(dest))
                        print(f"✓ Moved: {filename} → {dest_dir}/")

                moved_count += 1
            else:
                if not dry_run:
                    print(f"⚠ Not found: {filename}")
                missing_count += 1

    if not dry_run and git_moved_count > 0:
        print(f"\n📝 Git-tracked files moved: {git_moved_count}")
        print("   Remember to commit these changes!")

    return moved_count, missing_count


def create_init_files(base_path, dry_run=False):
    """Create __init__.py files in source directories."""
    init_files = [
        'src/__init__.py',
        # Note: src/extractors/__init__.py will be moved with the extractors directory
    ]

    for init_file in init_files:
        full_path = base_path / init_file
        if not full_path.exists():
            if dry_run:
                print(f"[DRY RUN] Would create: {init_file}")
            else:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text("# Package initialization\n")
                print(f"✓ Created: {init_file}")


def main():
    parser = argparse.ArgumentParser(description="Organize project directory structure")
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview changes without making them')
    args = parser.parse_args()

    base_path = Path.cwd()

    print("=" * 70)
    print("NGS Knowledge Base - Project Organization")
    print("=" * 70)
    print()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No changes will be made\n")

    # Step 1: Create directories
    print("Step 1: Creating directory structure...")
    create_directories(base_path, dry_run=args.dry_run)
    print()

    # Step 2: Move files
    print("Step 2: Moving files...")
    moved, missing = move_files(base_path, dry_run=args.dry_run)
    print()

    # Step 3: Create __init__ files
    print("Step 3: Creating __init__.py files...")
    create_init_files(base_path, dry_run=args.dry_run)
    print()

    # Summary
    print("=" * 70)
    print("Summary:")
    print(f"  Files moved: {moved}")
    print(f"  Files not found: {missing}")

    if args.dry_run:
        print("\n✓ Dry run complete. Run without --dry-run to apply changes.")
    else:
        print("\n✓ Organization complete!")
        print("\nNext steps:")
        print("  1. Update imports in scripts (run update_imports.py)")
        print("  2. Update .gitignore")
        print("  3. Test that scripts still work")
    print("=" * 70)


if __name__ == "__main__":
    main()
