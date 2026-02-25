"""
Update imports after reorganization.

This script fixes import statements in all Python files after the directory reorganization.
"""

import re
from pathlib import Path


# Import mappings: old_import -> new_import
IMPORT_MAPPINGS = {
    # Modules moved to src/
    'from query_analyzer import': 'from src.query_analyzer import',
    'import query_analyzer': 'import src.query_analyzer',
    'from admin_blacklist import': 'from src.admin_blacklist import',
    'import admin_blacklist': 'import src.admin_blacklist',

    # Extractors moved to src/extractors
    'from extractors.': 'from src.extractors.',
    'from extractors import': 'from src.extractors import',
    'import extractors': 'import src.extractors',

    # Modules that were in root, now in scripts/query/
    'from query_kb import': 'from scripts.query.query_kb import',
    'import query_kb': 'import scripts.query.query_kb',
}

# Files that need their imports fixed
FILES_TO_UPDATE = [
    'scripts/query/web_query.py',
    'scripts/utilities/debug_search.py',
    'scripts/utilities/cleanup_duplicate_chunks.py',
    'scripts/analysis/filter_admin_sections.py',
    'scripts/data_ingestion/load_chunks.py',
    'scripts/data_ingestion/load_paper_chunks.py',
    'scripts/data_ingestion/add_pmc_article.py',
    'scripts/data_ingestion/add_pmc_review_article.py',
    'scripts/data_ingestion/chunk_article.py',
    'scripts/data_ingestion/chunk_vet_review.py',
    'scripts/data_ingestion/embed_chunks.py',
    'scripts/data_ingestion/download_pmc.py',
    'scripts/analysis/extract_protocols.py',
]


def update_file_imports(file_path: Path):
    """Update imports in a single file."""
    if not file_path.exists():
        print(f"⚠ File not found: {file_path}")
        return False

    content = file_path.read_text()
    original_content = content

    # Apply import mappings
    for old_import, new_import in IMPORT_MAPPINGS.items():
        if old_import in content:
            content = content.replace(old_import, new_import)
            print(f"  Updated: {old_import} → {new_import}")

    # Write back if changed
    if content != original_content:
        file_path.write_text(content)
        print(f"✓ Updated: {file_path}")
        return True
    else:
        print(f"  No changes needed: {file_path}")
        return False


def main():
    base_path = Path.cwd()

    print("=" * 70)
    print("Updating imports after reorganization")
    print("=" * 70)
    print()

    updated_count = 0

    for file_rel_path in FILES_TO_UPDATE:
        file_path = base_path / file_rel_path
        print(f"\nProcessing: {file_rel_path}")

        if update_file_imports(file_path):
            updated_count += 1

    print()
    print("=" * 70)
    print(f"Summary: Updated {updated_count} files")
    print("=" * 70)


if __name__ == "__main__":
    main()
