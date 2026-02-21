#!/bin/bash
#
# process_papers_pipeline.sh
#
# Process PMC HTML files through the full pipeline: chunk → embed → load
#
# Usage:
#   bash process_papers_pipeline.sh html/vet pmc_chunks_vet veterinary PMC11171117
#
# Arguments:
#   $1 - HTML directory (e.g., html/vet)
#   $2 - Output chunks directory (e.g., pmc_chunks_vet)
#   $3 - Domain (medical | veterinary | both)
#   $4 - doc-key of parent review (e.g., PMC11171117)
#

set -e  # Exit on error

HTML_DIR="${1:-html/vet}"
CHUNKS_DIR="${2:-pmc_chunks_vet}"
DOMAIN="${3:-veterinary}"
DOC_KEY="${4:-PMC11171117}"

PYTHON="/Users/david/miniconda3/envs/openai/bin/python"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "PMC Paper Processing Pipeline"
echo "=========================================="
echo "HTML directory:    $HTML_DIR"
echo "Chunks directory:  $CHUNKS_DIR"
echo "Domain:            $DOMAIN"
echo "Parent doc-key:    $DOC_KEY"
echo "=========================================="
echo ""

# Create output directory
mkdir -p "$CHUNKS_DIR"

# Find all HTML files
HTML_FILES=("$HTML_DIR"/*.html)
TOTAL=${#HTML_FILES[@]}

if [ $TOTAL -eq 0 ]; then
    echo "ERROR: No HTML files found in $HTML_DIR"
    exit 1
fi

echo "Found $TOTAL HTML files to process"
echo ""

PROCESSED=0
FAILED=0

for HTML_FILE in "${HTML_FILES[@]}"; do
    BASENAME=$(basename "$HTML_FILE" .html)
    CHUNKS_FILE="$CHUNKS_DIR/${BASENAME}_chunks.json"
    EMBED_FILE="$CHUNKS_DIR/${BASENAME}_embeddings.json"

    PROCESSED=$((PROCESSED + 1))
    echo "[$PROCESSED/$TOTAL] Processing: $BASENAME"

    # Step 1: Chunk
    echo "  [1/3] Chunking..."
    if ! $PYTHON -c "
import json
from extractors import PMCExtractor

extractor = PMCExtractor('$HTML_FILE')
chunks = extractor.chunk()

with open('$CHUNKS_FILE', 'w', encoding='utf-8') as f:
    json.dump(chunks, f, indent=2, ensure_ascii=False)

print(f'    Extracted {len(chunks)} chunks')
"; then
        echo "  ERROR: Chunking failed for $BASENAME"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Step 2: Embed
    echo "  [2/3] Generating embeddings..."
    if ! $PYTHON "$SCRIPT_DIR/embed_chunks.py" \
        --input "$CHUNKS_FILE" \
        --output "$EMBED_FILE" \
        --yes \
        > /dev/null 2>&1; then
        echo "  ERROR: Embedding failed for $BASENAME"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Step 3: Load into database
    echo "  [3/3] Loading into database..."
    if ! $PYTHON "$SCRIPT_DIR/load_paper_chunks.py" \
        --file "$CHUNKS_FILE" \
        --embeddings "$EMBED_FILE" \
        --doc-key "$DOC_KEY" \
        --domain "$DOMAIN" \
        > /dev/null 2>&1; then
        echo "  ERROR: Database load failed for $BASENAME"
        FAILED=$((FAILED + 1))
        continue
    fi

    echo "  ✓ Complete"
    echo ""
done

echo "=========================================="
echo "Pipeline complete!"
echo "  Processed: $PROCESSED / $TOTAL"
echo "  Failed:    $FAILED"
echo "=========================================="

if [ $FAILED -eq 0 ]; then
    exit 0
else
    exit 1
fi
