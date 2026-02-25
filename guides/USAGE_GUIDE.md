# NGS Knowledge Base — Usage Guide

## Quick Reference

Three scripts handle all data ingestion:

1. **`add_pmc_article.py`** - Add a single research article to the database
2. **`add_pmc_review_article.py`** - Add a review article with citation extraction
3. **`download_pmc_from_file.py`** - Bulk download articles from a citation list

All scripts include duplicate checking and can be safely re-run.

---

## Prerequisites

```bash
# Activate environment
conda activate openai

# Verify database is running
psql mngs_kb -c "SELECT COUNT(*) FROM papers;"

# Check OpenAI API key
echo $OPENAI_API_KEY
```

---

## Common Workflows

### Scenario 1: Add a Single Research Article

**From PMC ID (most common):**

```bash
# Medical article
python add_pmc_article.py --pmcid PMC2581791 --domain medical

# Veterinary article
python add_pmc_article.py --pmcid PMC7953082 --domain veterinary

# Cross-domain article
python add_pmc_article.py --pmcid PMC1234567 --domain both
```

**From existing HTML file:**

```bash
python add_pmc_article.py --html html/B5_PMC2581791.html --domain medical
```

**Options:**

```bash
# Skip embeddings (faster, can add later)
python add_pmc_article.py --pmcid PMC2581791 --domain medical --no-embed

# Keep downloaded HTML file
python add_pmc_article.py --pmcid PMC2581791 --domain medical --keep-html

# Force reload (replace existing)
python add_pmc_article.py --pmcid PMC2581791 --domain medical --force

# Skip admin filtering (include ethics, funding, etc.)
python add_pmc_article.py --pmcid PMC2581791 --domain medical --no-filter-admin
```

**What it does:**
1. ✅ Checks if article already exists (by PMC ID)
2. ⬇️ Downloads HTML from PMC (if PMCID provided)
3. 📄 Extracts chunks with admin filtering
4. 🧮 Generates embeddings via OpenAI API
5. 💾 Loads into `papers` and `paper_chunks` tables
6. 🗑️ Cleans up temp files

---

### Scenario 2: Add a Review Article with Citations

**Basic usage:**

```bash
python add_pmc_review_article.py \
  --pmcid PMC11171117 \
  --domain veterinary \
  --title "Diagnostic applications of next-generation sequencing in veterinary medicine" \
  --authors "Momoi Y, Matsuu A"
```

**From existing HTML:**

```bash
python add_pmc_review_article.py \
  --html review.html \
  --doc-key my-vet-review-2024 \
  --domain veterinary \
  --title "My Review Title"
```

**Custom citation export:**

```bash
python add_pmc_review_article.py \
  --pmcid PMC11171117 \
  --domain veterinary \
  --title "..." \
  --citations-output my_custom_refs.json \
  --pmc-only  # Export only citations with PMC IDs
```

**What it does:**
1. ✅ Checks if review already exists (by doc_key)
2. ⬇️ Downloads HTML from PMC
3. 📄 Extracts chunks AND citations
4. 🧮 Generates embeddings
5. 💾 Loads into `review_sources`, `review_chunks`, and `citations` tables
6. 📋 Exports citation list to JSON for bulk download
7. 💡 Suggests next step (download cited papers)

**Output files:**
- `<doc_key>_references.json` - All citations (or PMC-only if `--pmc-only`)
- Downloaded HTML (if `--keep-html`)

---

### Scenario 3: Download Cited Papers from a Review

**After adding a review:**

```bash
# Download all PMC articles cited in the review
python download_pmc_from_file.py \
  --input PMC11171117_references.json \
  --outdir html/vet
```

**Options:**

```bash
# Custom log file
python download_pmc_from_file.py \
  --input vet_refs.json \
  --outdir html/vet \
  --log vet_downloads.json

# Test with first 10 articles
python download_pmc_from_file.py \
  --input refs.json \
  --outdir html \
  --limit 10

# Slower rate (be polite to NCBI)
python download_pmc_from_file.py \
  --input refs.json \
  --outdir html \
  --delay 3.0

# Force re-download
python download_pmc_from_file.py \
  --input refs.json \
  --outdir html \
  --force
```

**What it does:**
1. 📖 Reads citation JSON file
2. 🔍 Filters for entries with PMC IDs
3. ✅ Checks download log (skips already-downloaded)
4. ⬇️ Downloads HTML files (rate-limited)
5. 📝 Updates log after each download
6. 💡 Suggests next step (add articles to DB)

**Output:**
- HTML files: `<ref_id>_<PMCID>.html` (e.g., `B5_PMC2581791.html`)
- Download log: `download_log.json` (in outdir)

---

### Scenario 4: Bulk Add Downloaded Papers

**After downloading cited papers, add them all:**

```bash
# Option 1: Simple bash loop
for file in html/vet/*.html; do
  python add_pmc_article.py --html "$file" --domain veterinary
done

# Option 2: Using find + xargs (parallel)
find html/vet -name "*.html" -print0 | \
  xargs -0 -n 1 -P 4 python add_pmc_article.py --html --domain veterinary

# Option 3: Skip embeddings first (faster), add later
for file in html/vet/*.html; do
  python add_pmc_article.py --html "$file" --domain veterinary --no-embed
done

# Then add embeddings in a second pass (if needed)
```

**Create a helper script** (`bulk_add_papers.sh`):

```bash
#!/bin/bash
# Usage: ./bulk_add_papers.sh html/vet veterinary

HTML_DIR=$1
DOMAIN=$2

if [ -z "$HTML_DIR" ] || [ -z "$DOMAIN" ]; then
  echo "Usage: $0 <html_dir> <domain>"
  exit 1
fi

count=0
for file in "$HTML_DIR"/*.html; do
  [ -f "$file" ] || continue
  echo "Processing $file..."
  python add_pmc_article.py --html "$file" --domain "$DOMAIN"
  ((count++))
done

echo "Processed $count files"
```

---

## Complete Workflow: Add a Review + All Cited Papers

**Full example with veterinary review:**

```bash
# Step 1: Add the review article
python add_pmc_review_article.py \
  --pmcid PMC11171117 \
  --domain veterinary \
  --title "Diagnostic applications of next-generation sequencing in veterinary medicine" \
  --authors "Momoi Y, Matsuu A" \
  --pmc-only

# Output: PMC11171117_references.json with 71 PMC citations

# Step 2: Download all cited papers
python download_pmc_from_file.py \
  --input PMC11171117_references.json \
  --outdir html/vet

# Output: html/vet/R1_PMC1234567.html, R2_PMC2345678.html, ...

# Step 3: Add all downloaded papers to database
for file in html/vet/*.html; do
  python add_pmc_article.py --html "$file" --domain veterinary
done

# Done! Review + 71 papers in database
```

**Verify:**

```bash
psql mngs_kb -c "
  SELECT domain, COUNT(*) as papers
  FROM papers
  GROUP BY domain;
"

psql mngs_kb -c "
  SELECT COUNT(*) as review_chunks
  FROM review_chunks rc
  JOIN review_sources rs ON rc.source_id = rs.id
  WHERE rs.pmc_id = 'PMC11171117';
"
```

---

## Duplicate Handling

All scripts check for duplicates before processing:

### `add_pmc_article.py`

- Checks: `papers.pmc_id`
- If exists: Prints message and exits (unless `--force`)
- With `--force`: Deletes existing chunks, re-processes

### `add_pmc_review_article.py`

- Checks: `review_sources.doc_key`
- If exists: Prints message and exits (unless `--force`)
- With `--force`: Deletes existing chunks and citations, re-processes

### `download_pmc_from_file.py`

- Checks: Download log
- If exists with `status=ok`: Skips download
- With `--force`: Re-downloads regardless of log

**Safe re-runs:**

```bash
# These are all safe to run multiple times
python add_pmc_article.py --pmcid PMC2581791 --domain medical
python download_pmc_from_file.py --input refs.json --outdir html

# Will skip if already processed
```

---

## Error Recovery

### Download failed

```bash
# Check the log
cat html/vet/download_log.json | grep "error"

# Re-run (will skip successful downloads)
python download_pmc_from_file.py \
  --input refs.json \
  --outdir html/vet
```

### Database error during load

```bash
# Transaction is rolled back automatically
# Fix the issue (e.g., database connection)
# Re-run with --force to reload
python add_pmc_article.py --pmcid PMC2581791 --domain medical --force
```

### Partial processing

```bash
# If a bulk loop was interrupted:
for file in html/vet/*.html; do
  python add_pmc_article.py --html "$file" --domain veterinary
done

# The script checks for duplicates, so already-processed files are skipped
```

---

## Advanced Usage

### Add article without embeddings (fast)

```bash
# Process 100 papers without embeddings (very fast)
for file in html/vet/*.html; do
  python add_pmc_article.py --html "$file" --domain veterinary --no-embed
done

# Add embeddings later in a batch using existing scripts
python embed_chunks.py --input pmc_chunks_vet/combined.json --output embeddings.json
# (Requires custom aggregation script)
```

### Custom doc-key for reviews

```bash
# Use a memorable doc-key instead of PMC ID
python add_pmc_review_article.py \
  --pmcid PMC11171117 \
  --doc-key vet-ngs-review-momoi-2020 \
  --domain veterinary \
  --title "..."
```

### Export citations from existing review

```bash
# If you already loaded a review and want to export citations:
python export_citations.py \
  --source-id 3 \
  --pmc-only \
  --output vet_refs_export.json

# Then download
python download_pmc_from_file.py \
  --input vet_refs_export.json \
  --outdir html/vet
```

### Process only new articles

```bash
# Query database for existing PMC IDs
psql mngs_kb -c "COPY (SELECT pmc_id FROM papers) TO STDOUT" > existing_pmcs.txt

# Download only non-existing articles (requires custom filtering)
# (Could create a helper script for this)
```

---

## Database Schema Reference

### Papers (regular articles)

```
papers
├── id (primary key)
├── pmc_id (unique check)
├── doi
├── title
├── authors
├── domain (medical/veterinary/both)
└── ...

paper_chunks
├── id (primary key)
├── paper_id (foreign key → papers.id)
├── section_id
├── heading
├── full_text
├── embedding (vector)
└── ...
```

### Reviews

```
review_sources
├── id (primary key)
├── doc_key (unique)
├── pmc_id
├── domain (medical/veterinary/both)
└── ...

review_chunks
├── id (primary key)
├── source_id (foreign key → review_sources.id)
├── section_id
├── heading
├── full_text
├── embedding (vector)
└── ...

citations
├── id (primary key)
├── ref_id (e.g., "B5", "R12")
├── source_id (foreign key → review_sources.id)
├── pmc_id (nullable)
├── paper_id (foreign key → papers.id, set when paper is loaded)
└── ...
```

---

## Checking Status

### Papers count by domain

```bash
psql mngs_kb -c "
  SELECT domain, COUNT(*) as papers,
         COUNT(CASE WHEN EXISTS(
           SELECT 1 FROM paper_chunks pc WHERE pc.paper_id = p.id AND pc.embedding IS NOT NULL
         ) THEN 1 END) as with_embeddings
  FROM papers p
  GROUP BY domain;
"
```

### Reviews count

```bash
psql mngs_kb -c "
  SELECT doc_key, domain,
         (SELECT COUNT(*) FROM review_chunks rc WHERE rc.source_id = rs.id) as chunks,
         (SELECT COUNT(*) FROM citations c WHERE c.source_id = rs.id) as citations
  FROM review_sources rs;
"
```

### Citation coverage

```bash
# How many citations have been downloaded as full papers?
psql mngs_kb -c "
  SELECT rs.doc_key,
         COUNT(*) as total_citations,
         COUNT(c.paper_id) as papers_downloaded,
         ROUND(100.0 * COUNT(c.paper_id) / COUNT(*), 1) as percent_coverage
  FROM review_sources rs
  JOIN citations c ON c.source_id = rs.id
  WHERE c.pmc_id IS NOT NULL
  GROUP BY rs.doc_key;
"
```

---

## Troubleshooting

### "Paper already exists"

**Cause:** Article with this PMC ID is already in database

**Solution:**
```bash
# Skip it (already loaded)
# OR force reload:
python add_pmc_article.py --pmcid PMC2581791 --domain medical --force
```

### "Review already exists"

**Cause:** Review with this doc_key is already in database

**Solution:**
```bash
# Skip it (already loaded)
# OR force reload:
python add_pmc_review_article.py --pmcid PMC11171117 --domain vet --title "..." --force
```

### "OPENAI_API_KEY not set"

**Cause:** Environment variable missing

**Solution:**
```bash
export OPENAI_API_KEY="sk-..."
# OR skip embeddings:
python add_pmc_article.py --pmcid PMC2581791 --domain medical --no-embed
```

### "extractors package not found"

**Cause:** Running from wrong directory or extractors/ not in path

**Solution:**
```bash
cd /Users/david/work/informatics_ai_workflow
python add_pmc_article.py ...
```

### "Cannot extract PMC ID from filename"

**Cause:** HTML filename doesn't contain PMC ID

**Solution:**
```bash
# Rename file to include PMC ID:
mv article.html PMC2581791.html
# OR use --pmcid instead:
python add_pmc_article.py --pmcid PMC2581791 --domain medical
```

### Download fails with HTTP 404

**Cause:** Article not available in PMC or incorrect PMC ID

**Solution:**
- Verify PMC ID is correct
- Check if article is available at https://pmc.ncbi.nlm.nih.gov/articles/PMC2581791/
- Some citations may not have full text available

---

## Cost Estimation

### Embeddings cost (OpenAI text-embedding-3-small)

- **Rate:** $0.02 per 1M tokens
- **Average paper:** ~15 chunks × 500 tokens = ~7,500 tokens
- **Cost per paper:** ~$0.00015 (0.015 cents)
- **100 papers:** ~$0.015 (1.5 cents)

### Example:

```bash
# Adding 71 veterinary papers with embeddings:
# 71 papers × 7,500 tokens = 532,500 tokens
# Cost: $0.0106 (~1 cent)
```

**Tip:** Use `--no-embed` for initial testing, add embeddings later in batch.

---

## Best Practices

### 1. Organize HTML files by domain

```bash
html/
├── medical/
│   ├── B1_PMC123.html
│   └── B2_PMC456.html
└── veterinary/
    ├── R1_PMC789.html
    └── R2_PMC012.html
```

### 2. Keep download logs

```bash
# Use descriptive log names
python download_pmc_from_file.py \
  --input vet_refs.json \
  --outdir html/vet \
  --log logs/vet_download_2024.json
```

### 3. Test with --limit first

```bash
# Test workflow with 5 articles
python download_pmc_from_file.py --input refs.json --outdir html/test --limit 5
python add_pmc_article.py --pmcid PMC2581791 --domain medical --no-embed

# Then run full batch
```

### 4. Use version control for citation files

```bash
git add PMC11171117_references.json
git commit -m "Add vet review citations (71 PMC IDs)"
```

### 5. Document your reviews

Create a `REVIEWS.md`:

```markdown
# Reviews in Database

## Medical
- **fcimb-14-1458316** - Application of mNGS in diagnosis of infectious diseases (Zhao et al. 2024)
  - 168 citations, 114 with PMC IDs

## Veterinary
- **PMC11171117** - Diagnostic applications of NGS in veterinary medicine (Momoi & Matsuu 2020)
  - 122 citations, 71 with PMC IDs
```

---

## Next Steps

After adding articles, you can:

1. **Run clustering analysis**
   ```bash
   python cluster_topics.py --plot
   ```

2. **Extract protocols**
   ```bash
   python extract_protocols.py --cluster-id 0
   ```

3. **Query the knowledge base**
   ```bash
   python query_kb.py -q "mNGS for CSF diagnostics" --quote
   ```

4. **Search for specific articles**
   ```bash
   python search_references.py --title "metagenomic"
   python search_references.py --author "Momoi"
   ```

5. **Analyze shared protocols**
   ```bash
   python analyze_shared_protocols.py  # (to be created)
   ```

---

## Summary of Script Responsibilities

| Script | Purpose | Input | Output | DB Tables |
|--------|---------|-------|--------|-----------|
| `add_pmc_article.py` | Add research article | PMCID or HTML | - | `papers`, `paper_chunks` |
| `add_pmc_review_article.py` | Add review + citations | PMCID or HTML | Citations JSON | `review_sources`, `review_chunks`, `citations` |
| `download_pmc_from_file.py` | Bulk download | Citations JSON | HTML files | - |

**Data flow:**

```
Review Article → add_pmc_review_article.py → citations.json
                                           ↓
citations.json → download_pmc_from_file.py → html/*.html
                                           ↓
html/*.html → add_pmc_article.py (loop) → Database
```

---

## See Also

- `SESSION_CONTEXT.md` - Project overview and findings
- `gap_analysis_final.md` - Clustering analysis results
- Legacy scripts in root directory (now superseded by these three scripts)
