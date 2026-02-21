#!/bin/bash
# bulk_add_papers.sh
#
# Bulk add PMC articles from a directory to the database.
#
# Usage:
#   ./bulk_add_papers.sh html/vet veterinary
#   ./bulk_add_papers.sh html/medical medical [--no-embed]

HTML_DIR=$1
DOMAIN=$2
shift 2
EXTRA_ARGS="$@"

if [ -z "$HTML_DIR" ] || [ -z "$DOMAIN" ]; then
  echo "Usage: $0 <html_dir> <domain> [extra_args]"
  echo ""
  echo "Examples:"
  echo "  $0 html/vet veterinary"
  echo "  $0 html/medical medical --no-embed"
  echo "  $0 html/vet veterinary --force"
  exit 1
fi

if [ ! -d "$HTML_DIR" ]; then
  echo "Error: Directory not found: $HTML_DIR"
  exit 1
fi

count=0
success=0
skipped=0

for file in "$HTML_DIR"/*.html; do
  [ -f "$file" ] || continue

  echo ""
  echo "[$((count+1))] Processing $(basename "$file")..."

  if python add_pmc_article.py --html "$file" --domain "$DOMAIN" $EXTRA_ARGS; then
    ((success++))
  else
    if [ $? -eq 0 ]; then
      ((skipped++))
    fi
  fi

  ((count++))
done

echo ""
echo "========================================="
echo "Bulk add complete"
echo "========================================="
echo "  Files processed: $count"
echo "  Successful:      $success"
echo "  Skipped:         $skipped"
echo "========================================="
