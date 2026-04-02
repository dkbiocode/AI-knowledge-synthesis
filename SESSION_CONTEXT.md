# NGS Knowledge Base — Session Context & Handoff

**Project:** Cross-domain NGS diagnostic protocol knowledge base (medical ↔ veterinary knowledge sharing)
**Owner:** David
**Environment:** `/Users/david/work/informatics_ai_workflow`
**Database:** PostgreSQL `mngs_kb` (localhost, Homebrew install at `/opt/homebrew/opt/postgresql@16`)
**Python env:** `miniconda3` at `/Users/david/miniconda3/envs/openai`

---

## Project Overview

### Research Goal
Build a knowledge base to identify **topic overlap and knowledge sharing opportunities** between NGS diagnostic protocols in medical and veterinary practice.

**Key finding (updated 2026-02-19):** *Medical and veterinary NGS communities show **balanced knowledge convergence** (1.2:1 ratio), using similar technologies and methodologies. Value lies in bidirectional knowledge sharing rather than one-way transfer.*

**Phase 1:** ✅ COMPLETE - Extract and cluster medical + veterinary literature
**Phase 2 (current):** Comparative protocol analysis, sub-clustering by application
**Phase 3 (planned):** Protocol resolution (follow citation chains to external SOPs, protocols.io, CDC guidelines)

### Intellectual Framework

The **protocol** is the unit of analysis, not the paper. A protocol is:
- **Identity:** modality (mNGS, targeted NGS, WGS), pathogen class, specimen type, platform
- **Context:** typed verbatim excerpts (method, performance, limitations, biology, obstacles)
- **Transferability:** veterinary applicability score (0-3) + obstacle summary

Papers cite protocols; protocols accumulate evidence across sources. The `protocol_sources` bridge table tracks which chunks describe/use/critique each protocol.

---

## Current State (as of 2026-02-20 - Phase 2 In Progress)

### Database Summary

**Total content:** 3,248 chunks from 186 papers + 2 reviews
- **Medical:** 1,769 chunks (54.5%) - 114 papers + 1 review
- **Veterinary:** 1,479 chunks (45.5%) - 72 papers + 1 review (including Momoi & Matsuu 2020)
- **Embeddings:** 3,238/3,248 (99.7%)
- **Administrative content:** Filtered out (966 chunks removed)

**Clustering results:**
- **2 balanced clusters** (gap scores 0.23-0.31)
- **Cluster 0:** 2,019 chunks (99.9% NGS content) - 1,118 med / 901 vet
  - **Sub-clusters:** 2 coherent groups (607 + 22 chunks), 1,390 noise (68.8%)
  - **Pathogen distribution:** Unknown (57%), Bacteria (14%), Mixed (14%), Virus (11%)
- **Cluster 1:** 50 chunks (study design) - 27 med / 23 vet
- **Noise:** 1,203 chunks (36.8% - specialized protocols)

**Protocol extraction:** In progress
- **Protocols table:** 3 protocols (test extraction from paper_id=104)
- **Cluster 0 extraction:** Running 100 chunks (estimated 500-1,000 protocols total)
- **Schema:** 18-field structured extraction with vet transferability scoring

### What's Built

#### 1. Database Schema (v3 - with clustering)

**Core tables (v1):**
- `review_sources`, `review_chunks`, `papers`, `paper_chunks`, `citations`, `chunk_citations`

**Protocol tables (v2):**
- `protocols`, `protocol_sources`

**Clustering tables (v3):**
- `chunk_clusters`, `cluster_gap_scores`, `cluster_representatives`

**Domain tagging:**
- `papers.domain` and `review_sources.domain` (`'medical' | 'veterinary' | 'both'`)

**Key relationships:**
```
papers ← citations.paper_id
papers ← paper_chunks.paper_id
paper_chunks ← protocol_sources.paper_chunk_id → protocols
review_chunks ← protocol_sources.review_chunk_id → protocols
paper_chunks ← chunk_clusters.chunk_id → cluster_gap_scores
review_chunks ← chunk_clusters.chunk_id → cluster_gap_scores
```

#### 2. Data Loaded

**Medical corpus:**
- Review: fcimb-14-1458316 (22 chunks, 168 citations)
- Papers: 114 papers, 1,769 chunks (after admin filtering)
- Embeddings: 1,787/1,787 (100%)

**Veterinary corpus:**
- Review: PMC11171117 (20 chunks, 122 citations)
- Papers: 71 papers, 1,465 chunks (after admin filtering)
- Embeddings: 1,485/1,485 (100%)

**Protocols extracted:**
- 3 protocols from test run (paper_id=104)
- Full extraction pending on Cluster 0

**Clustering:**
- 3,272 chunks clustered into 2 main clusters + noise
- UMAP 2D projections stored in `chunk_clusters` table
- Gap scores computed and stored in `cluster_gap_scores`

#### 3. Extractors Package (`extractors/`)

Refactored chunking into source-agnostic interface:
- **`extractors/base.py`:** Abstract `BaseExtractor` class
- **`extractors/pmc.py`:** PMC HTML extractor (handles B-style and R-style ref IDs)
  - **New:** `filter_admin=True` parameter to skip administrative sections
- **`extractors/__init__.py`:** Package exports

**Admin filtering:**
- `admin_blacklist.py` - 20+ regex patterns for administrative sections
- Filters: ethics, consent, funding, conflicts, data availability, etc.
- **Impact:** Reduces chunk count by ~23%, improves clustering quality

#### 4. Pipeline Scripts

**Data ingestion:**
- `export_citations.py` - Export citations from DB to JSON for download
- `download_pmc.py` - Download PMC HTMLs (supports both ref_id formats)
- `embed_chunks.py` - Generate OpenAI embeddings
- `load_chunks.py` - Load review chunks (supports `--domain`)
- `load_paper_chunks.py` - Load paper chunks (supports `--domain`)
- `process_papers_pipeline.sh` - Automated chunk→embed→load workflow

**Clustering & analysis:**
- `cluster_topics.py` - HDBSCAN clustering + UMAP + gap scores
- `analyze_cluster_topics.py` - TF-IDF + NGS keyword analysis per cluster
- `filter_admin_sections.py` - Clean/analyze administrative content

**Protocol extraction:**
- `extract_protocols.py` - LLM extraction using OpenAI JSON schema mode
  - Model: `gpt-4o-mini`
  - 18-field protocol schema
  - NGS-only focus (excludes RT-PCR, serology, culture)

**Query system:**
- `query_kb.py` - RAG with BM25 sentence re-ranking
  - `--quote` flag for verbatim excerpts
  - Citation-aware context building

#### 5. Clustering Infrastructure

**Scripts:**
- `cluster_topics.py` - Full clustering pipeline
  - HDBSCAN (min_cluster_size=20, min_samples=10)
  - L2-normalized embeddings + euclidean metric (equivalent to cosine)
  - UMAP 2D projection
  - Gap score computation
  - Visualization generation

- `analyze_cluster_topics.py` - Topic identification
  - TF-IDF term extraction per cluster
  - NGS keyword counting (60+ keywords)
  - Representative chunk selection
  - NGS relevance scoring

**Database schema:**
- `cluster_schema.sql` - Clustering tables
  - `chunk_clusters`: cluster assignments + UMAP coordinates
  - `cluster_gap_scores`: medical/vet counts + gap scores
  - `cluster_representatives`: top chunks per cluster

**Gap score formula:**
```
gap_score = log2(medical_count / vet_count)

Interpretation:
  gap_score > 2   : Medical-dominated (4x+)
  gap_score 1-2   : Medical-leaning (2-4x)
  gap_score -1..1 : Balanced
  gap_score < -1  : Vet-leaning/dominated
```

#### 6. Consolidated Data Ingestion (NEW)

**Simplified workflow for adding papers to the knowledge base:**

**Scripts:**
- `add_pmc_article.py` - Single-command article ingestion
  - Download from PMCID or use existing HTML
  - Extract chunks with admin filtering
  - Generate embeddings (text-embedding-3-small)
  - Load into papers/paper_chunks tables
  - Duplicate checking by PMC ID
  - Usage: `python add_pmc_article.py --pmcid PMC2581791 --domain medical`

- `add_pmc_review_article.py` - Review article processing
  - Process as review article (review_sources/review_chunks tables)
  - Extract citations from References section
  - Export citation list to JSON for bulk download
  - Duplicate checking by doc_key
  - Usage: `python add_pmc_review_article.py --pmcid PMC11171117 --domain veterinary --export-refs vet_refs.json`

- `download_pmc_from_file.py` - Bulk download from citation lists
  - Reads reference_index.json format
  - Maintains download log for safe re-runs
  - Rate limiting (default 1.5s between requests)
  - B-number sorting for ordered downloads
  - Usage: `python download_pmc_from_file.py --refs vet_refs.json --outdir html/vet --log vet_log.json`

- `bulk_add_papers.sh` - Batch processing helper
  - Loops through HTML directory
  - Calls add_pmc_article.py for each file
  - Reports success/skip/failure counts
  - Usage: `./bulk_add_papers.sh html/vet veterinary`

**Documentation:**
- `docs/guides/USAGE_GUIDE.md` - Comprehensive guide for data ingestion workflows

**Key features:**
- All scripts support `--force` to override duplicate checking
- Safe re-run capability (duplicate detection)
- Transactional database updates with rollback on errors
- Admin content filtering enabled by default
- OpenAI embedding generation integrated

#### 7. PDF Processing (NEW) - Complete Workflow

**Full pipeline for non-PMC articles (when HTML format unavailable):**

**Enhanced PDF parser (`parse_pdf_article.py`):**
- **Improved section detection** - Canonical section recognition (Abstract, Methods, Results, etc.)
  - Filters sentence fragments and false positives (title text, headers, etc.)
  - Detects parent sections and subsections (hierarchical structure)
  - Skips content before first canonical section (title region exclusion)
  - Handles sentence-case subsection headings (common in scientific papers)
- **Automatic metadata extraction:**
  - Full author list from first page (removes affiliation numbers)
  - Journal name from subject field
  - DOI extraction from metadata
  - Year, title, creator, page count
- **Output format:**
  - JSON with `{"sections": [...], "metadata": {...}}` structure
  - Compatible with `embed_chunks.py` and `load_chunks.py`
  - No manual --title, --authors, --journal needed!
- **Usage:** `python parse_pdf_article.py --pdf article.pdf --output sections.json`
- **Example output:**
  ```json
  {
    "metadata": {
      "title": "Metagenomic surveillance for bacterial tick-borne pathogens...",
      "authors": "Evan J. Kipp Laramie L. Lindsey... & Peter A. Larsen",
      "journal": "Scientific Reports",
      "doi": "10.1038/s41598-023-37134-9"
    },
    "sections": [
      {"heading": "Results", "level": 1, "text": "", "parent_heading": null},
      {"heading": "Tick sampling and sequencing strategies.", "level": 2,
       "text": "...", "parent_heading": "Results"}
    ]
  }
  ```

**Enhanced embedding tool (`embed_chunks.py`):**
- **Format compatibility:**
  - Handles both PMC format (list with `full_text`) and PDF format (dict with `sections` and `text`)
  - Auto-detects input format
  - Empty parent sections handled (uses heading text for embedding)
- **Relative path support:** Paths resolved from current working directory
- **Usage:** `python embed_chunks.py --input sections.json --output embeddings.json`

**Enhanced database loader (`load_chunks.py`):**
- **Metadata auto-loading:**
  - Reads title, authors, journal, DOI from JSON metadata
  - Falls back to command-line args if needed
  - Only --doc-key and --domain required for PDFs
- **Format compatibility:**
  - Auto-detects PMC (section_id-based) vs PDF (index-based) embeddings
  - References optional (--refs not required for PDFs without citations)
- **Usage:** `python load_chunks.py --chunks sections.json --embeddings embeddings.json --doc-key my_article --domain veterinary`

**Complete PDF workflow (3 steps):**
```bash
# Step 1: Parse PDF into sections (extracts metadata automatically)
python scripts/utilities/parse_pdf_article.py \
  --pdf data/raw/PDFs/article.pdf \
  --output data/raw/PDFs/article_sections.json

# Step 2: Generate embeddings
python scripts/data_ingestion/embed_chunks.py \
  --input data/raw/PDFs/article_sections.json \
  --output data/raw/PDFs/article_embeddings.json

# Step 3: Load to database (metadata read from JSON!)
python scripts/data_ingestion/load_chunks.py \
  --chunks data/raw/PDFs/article_sections.json \
  --embeddings data/raw/PDFs/article_embeddings.json \
  --doc-key my_article_key \
  --domain veterinary
```

**Specialized Science journal parser:**
- `parse_science_pdf.py` - Handles Science journal PDFs (paragraph-based sections)
  - DOI extraction, multi-article handling, header/footer cleaning
  - Usage: `python parse_science_pdf.py PDFs/science.1181498.pdf --output-format json`

**Key improvements (2026-02-21):**
- ✅ Automatic author/journal/DOI extraction (no manual metadata entry)
- ✅ Canonical section detection (prevents title/header fragments)
- ✅ Full PMC/PDF format compatibility across all tools
- ✅ Relative path support (works from any directory)
- ✅ Index-based embedding lookup for PDF sections (no section_id required)
- ✅ Empty parent section handling (embeds heading text)

**Tested on:** `sci_reports_ont_tickborne.pdf` (13 sections loaded successfully)

---

## File Inventory

### Core Scripts
| File | Purpose | Status |
|------|---------|--------|
| `setup_db.py` | Create PostgreSQL database + schema | Working |
| `create_schema.sql` | Full v3 schema (fresh install) | ✅ v3 with clustering |
| `cluster_schema.sql` | Clustering tables (add-on) | ✅ Applied |
| `migrate_v2.sql` | v1→v2 migration | ✅ Applied (legacy) |
| `download_pmc.py` | Download PMC HTMLs (legacy - use download_pmc_from_file.py) | ✅ Supports both ref_id formats |
| `export_citations.py` | Export citations from DB to JSON | ✅ Working |
| `embed_chunks.py` | Generate OpenAI embeddings (legacy - use add_pmc_*.py) | Working |
| `load_chunks.py` | Load review chunks → DB (legacy - use add_pmc_review_article.py) | ✅ Supports `--domain` |
| `load_paper_chunks.py` | Load paper chunks → DB (legacy - use add_pmc_article.py) | ✅ Supports `--domain` |
| `process_papers_pipeline.sh` | Automated chunk→embed→load (legacy - use bulk_add_papers.sh) | ✅ Working |
| `extract_protocols.py` | LLM extraction of protocols | ✅ Supports `--cluster-id` |
| `query_kb.py` | RAG query with domain separation + author citations | ✅ Enhanced Phase 2 |
| `cluster_topics.py` | HDBSCAN clustering + UMAP | ✅ Working |
| `analyze_cluster_topics.py` | NGS topic analysis | ✅ Working |
| `filter_admin_sections.py` | Clean administrative content | ✅ Working |
| `search_references.py` | Search papers by title/author/PMC/ref-id | ✅ Working |
| `search_protocols.py` | Search protocols by modality/pathogen/specimen | ✅ Working |
| `subcluster_cluster0.py` | Pathogen-centric sub-clustering | ✅ Working |
| `plot_cluster0_umap.py` | Flexible UMAP visualization (domain/pathogen/NGS) | ✅ Working |

### Consolidated Data Ingestion Scripts (PREFERRED)
| File | Purpose | Status |
|------|---------|--------|
| `add_pmc_article.py` | Single-command article ingestion (download/chunk/embed/load) | ✅ NEW - Use this instead of manual workflow |
| `add_pmc_review_article.py` | Review article processing + citation extraction | ✅ NEW - Use this for review articles |
| `download_pmc_from_file.py` | Bulk download from citation JSON with resume capability | ✅ NEW - Use this instead of download_pmc.py |
| `bulk_add_papers.sh` | Batch processing helper for downloaded HTMLs | ✅ NEW |
| `docs/guides/USAGE_GUIDE.md` | Comprehensive documentation for data ingestion | ✅ NEW |

### PDF Processing Scripts
| File | Purpose | Status |
|------|---------|--------|
| `parse_pdf_article.py` | General PDF parser with font-based section detection | ✅ NEW - For Nature, Cell, etc. |
| `parse_science_pdf.py` | Specialized Science journal PDF parser (paragraph sections) | ✅ NEW - For Science journal only |

### Extractors Package
| File | Purpose |
|------|---------|
| `extractors/__init__.py` | Package exports |
| `extractors/base.py` | Abstract base class |
| `extractors/pmc.py` | PMC HTML extractor (with admin filtering) |
| `admin_blacklist.py` | Administrative section patterns (20+ regexes) |

### Analysis Reports
| File | Content |
|------|---------|
| `gap_analysis_final.md` | Complete clustering analysis & findings |
| `gap_analysis_report.md` | Initial analysis (before cleanup) |
| `cluster_ngs_summary.md` | Quick reference - NGS topics per cluster |
| `gap_scores.tsv` | Cluster gap scores (TSV export) |
| `CLUSTERING_STRATEGY.md` | Design doc (not created, see gap_analysis_final.md) |

### Data Files
| Path | Content |
|------|---------|
| `html/` | 116 PMC HTMLs (medical papers, B1-B168 with gaps) |
| `html/vet/` | 71 PMC HTMLs (veterinary papers) |
| `pmc_chunks/` | 115 JSON files (medical paper chunks) |
| `pmc_chunks_vet/` | 71 JSON files (veterinary paper chunks) |
| `pmc_chunks_vet_test/` | 3 JSON files (test chunks) |
| `chunks.json` | Medical review chunks |
| `embeddings.json` | Medical review embeddings |
| `vet_chunks.json` | Veterinary review chunks |
| `vet_embeddings.json` | Veterinary review embeddings |
| `vet_pmc_refs.json` | Veterinary citations (71 PMC IDs) |
| `reference_index.json` | Medical review references |
| `vet_references.json` | Veterinary review references |
| `download_log.json` | Medical PMC download log |
| `vet_download_log.json` | Veterinary PMC download log |
| `cluster_plots/` | UMAP visualizations (3 PNG files) |

---

## Connection Info

### PostgreSQL
```bash
# psql path
/opt/homebrew/opt/postgresql@16/bin/psql

# Connect to DB
psql mngs_kb

# Environment variables (optional, defaults to localhost peer auth)
PGHOST=localhost
PGPORT=5432
PGUSER=david
PGDATABASE=mngs_kb
```

### Python Environment
```bash
# Activate
conda activate openai

# Python path
/Users/david/miniconda3/envs/openai/bin/python

# Key packages
openai, psycopg2, beautifulsoup4, rank_bm25
scikit-learn, hdbscan, umap-learn, matplotlib, numpy  # NEW: clustering
```

### OpenAI API
```bash
# Key stored in environment (check with)
echo $OPENAI_API_KEY
```

---

## Common Tasks

### Clustering & Gap Analysis

```bash
# Run full clustering pipeline (HDBSCAN + UMAP + gap scores)
python cluster_topics.py --plot

# Analyze NGS topics in clusters
python analyze_cluster_topics.py --summary-only

# Detailed analysis of specific cluster
python analyze_cluster_topics.py --cluster 0

# Clean administrative sections from database
python filter_admin_sections.py --clean
```

### Data Ingestion - SIMPLIFIED WORKFLOW (PREFERRED)

**Add a single article:**
```bash
# From PMCID (auto-downloads)
python add_pmc_article.py --pmcid PMC2581791 --domain medical

# From existing HTML file
python add_pmc_article.py --html html/PMC2581791.html --domain medical

# Force re-add (override duplicate check)
python add_pmc_article.py --pmcid PMC2581791 --domain medical --force
```

**Add a review article with citation extraction:**
```bash
# Process review and export citations
python add_pmc_review_article.py \
  --pmcid PMC11171117 \
  --domain veterinary \
  --export-refs vet_citations.json

# Download all cited papers
python download_pmc_from_file.py \
  --refs vet_citations.json \
  --outdir html/vet \
  --log vet_download_log.json

# Bulk add all downloaded papers
./bulk_add_papers.sh html/vet veterinary
```

**Skip embedding generation (for testing):**
```bash
python add_pmc_article.py --pmcid PMC2581791 --domain medical --no-embed
```

### Data Ingestion - LEGACY WORKFLOW (Still works)

```bash
# Export citations from review
python export_citations.py --source-id 3 --pmc-only --output vet_refs.json

# Download PMC papers
python download_pmc.py --refs vet_refs.json --outdir html/vet --log vet_log.json

# Process papers through full pipeline (chunk→embed→load with filtering)
bash process_papers_pipeline.sh html/vet pmc_chunks_vet veterinary PMC11171117
```

### PDF Processing

```bash
# Parse general PDF article (Nature, Cell, etc.)
python parse_pdf_article.py PDFs/nature_methods.pdf --output-format json > output.json
python parse_pdf_article.py PDFs/nature_methods.pdf --show-tree  # Preview structure

# Parse Science journal PDF
python parse_science_pdf.py PDFs/science.1181498.pdf --output-format json > output.json
python parse_science_pdf.py PDFs/science.1181498.pdf --show-tree  # Preview structure
python parse_science_pdf.py PDFs/science.1181498.pdf --no-paragraphs  # Single section mode

# Output formats: json, sections, tree, full
```

### Protocol Extraction

```bash
# Extract from specific cluster
python extract_protocols.py --source papers --cluster-id 0

# Extract from specific paper
python extract_protocols.py --source papers --paper-id 104

# Dry-run (test without DB writes)
python extract_protocols.py --dry-run --limit 5
```

### Query the Knowledge Base

```bash
# Basic query
python query_kb.py -q "what NGS methods detect arboviruses in CSF"

# With verbatim quotes
python query_kb.py -q "..." --quote

# Show retrieved chunks
python query_kb.py -q "..." --show-chunks
```

### Check DB State

```bash
# Overall counts
psql mngs_kb -c "
SELECT
  'review' as source, rs.domain, COUNT(rc.id) as chunks
FROM review_sources rs
LEFT JOIN review_chunks rc ON rs.id = rc.source_id
GROUP BY rs.domain
UNION ALL
SELECT
  'paper', p.domain, COUNT(pc.id)
FROM papers p
LEFT JOIN paper_chunks pc ON p.id = pc.paper_id
GROUP BY p.domain;
"

# Cluster summary
psql mngs_kb -c "SELECT * FROM cluster_gap_scores ORDER BY gap_score DESC;"

# Protocol counts
psql mngs_kb -c "SELECT ngs_modality, COUNT(*) FROM protocols GROUP BY ngs_modality;"
```

---

## Key Findings (Phase 1)

### Initial Hypothesis (REVISED)
~~Medical NGS protocols need to be transferred to veterinary practice~~

### Actual Finding
**Medical and veterinary NGS communities show balanced knowledge convergence**

### Evidence
- **1.2:1 medical:vet ratio** (55% med, 45% vet) after filtering admin content
- **2 balanced clusters** (gap scores 0.23-0.31) vs initial 8 medical-dominated clusters
- **Same technologies:** mNGS, Illumina, MinION, PacBio, metagenomic sequencing
- **Same applications:** CSF diagnostics, blood pathogen detection, coverage analysis
- **99.9% NGS content in Cluster 0** (2,019 chunks) with 1.24:1 med:vet ratio

### Lessons Learned

1. **Administrative content skews analysis** - 23% of initial dataset was non-technical boilerplate
   - Medical journals have more standardized admin sections → artificial gaps
   - **Solution:** Filter at ingestion using `PMCExtractor(path, filter_admin=True)`

2. **Dataset balance matters** - Initial 4.6:1 ratio created false gaps
   - Balanced 1.2:1 ratio revealed true topic overlap
   - **Recommendation:** Maintain ~1:1 domain ratio for comparative analysis

3. **Veterinary NGS more advanced than expected** - Parallel development, not lagging
   - Same platforms, same applications, similar validation approaches
   - **Implication:** Bidirectional knowledge sharing, not one-way transfer

4. **Noise is valuable** - 36.8% unclustered chunks may contain novel/specialized protocols
   - Domain-specific applications, emerging methods, micro-topics
   - **Action:** Mine noise for high-value outliers

---

## Next Steps (Phase 2)

### Immediate
1. **Extract protocols from Cluster 0** (2,019 NGS-rich chunks)
   ```bash
   python extract_protocols.py --cluster-id 0 --source papers
   ```

2. **Sub-cluster Cluster 0** for application-specific groups
   - CSF/CNS infections vs blood diagnostics vs respiratory vs parasitology
   - Use tighter parameters or K-means with K=10-20

3. **Query system enhancement** - Add cluster context to RAG answers
   ```python
   # "This protocol appears in a balanced medical-vet cluster (gap=0.31),
   #  indicating widespread adoption across domains."
   ```

### Short-term
1. **Comparative protocol analysis** - How do medical and vet validate the *same* methods?
   - Sensitivity/specificity comparisons
   - Specimen type differences
   - Cost/infrastructure requirements

2. **Citation network analysis** - Which medical papers are cited in vet literature?
   - Identify influential cross-domain studies
   - Map knowledge flow patterns

3. **Topic modeling** - Apply LDA or BERTopic to Cluster 0 for finer granularity

### Long-term (Phase 3)
1. **Protocol resolution** - Follow citation chains to external SOPs
   - Implement `resolve_protocols.py`
   - Add downloaders: `protocols_io.py`, `cdc.py`, `woah.py`

2. **Comparative dashboard** - Visualize medical-vet protocol equivalencies

3. **Expand corpus** - Add wildlife, aquatic, or livestock NGS literature

---

## Known Issues & Considerations

### Clustering
- **High noise (36.8%)** - Expected for heterogeneous scientific literature, contains valuable outliers
- **Silhouette score (0.114)** - Low but appropriate for broad topic clusters
- **Two-cluster result** - May need sub-clustering for application-specific analysis
- **Parameter sensitivity** - min_cluster_size=20 works well after admin filtering

### Protocol Extraction
- **RT-PCR misclassification** - Occasional false positives (e.g., amplicon NGS vs PCR)
- **String "null" vs JSON null** - LLM sometimes returns string instead of null
- **Edge cases** - ~33% accuracy acceptable per user preference
- **Extraction incomplete** - Only 3 protocols extracted so far (test run)

### Data Quality
- **Administrative sections removed** - 966 chunks filtered (ethics, funding, etc.)
- **Citation extraction** - Review chunks show 0 inline citations (potential extractor bug)
- **Domain tagging** - Manual for reviews, automatic for papers (based on source)

---

## Important Context for New Sessions

### Design Decisions

1. **Protocols are canonical, sources accumulate** - Same protocol gets one `protocols` row, multiple `protocol_sources` rows

2. **Typed excerpts** - Each excerpt type has its own field (enables structured queries)

3. **Veterinary transferability is LLM-assessed** - May need recalibration based on balanced clustering results

4. **NGS-only scope** - Excludes conventional PCR, serology, culture (amplicon-NGS included)

5. **Administrative filtering at ingestion** - Prevents clustering on non-technical content

6. **Balanced dataset required** - ~1:1 medical:vet ratio for accurate gap analysis

---

## Session 2026-02-20: Phase 2 Progress

### Accomplishments

#### 1. **Consolidated Data Ingestion Tools** ⭐ NEW
- **Created `add_pmc_article.py`**: Single-command article ingestion
  - Replaces 5+ step manual workflow (download→chunk→embed→load)
  - Duplicate checking by PMC ID (safe to re-run)
  - Supports `--pmcid` or `--html` input
  - Admin filtering enabled by default
  - Usage: `python add_pmc_article.py --pmcid PMC2581791 --domain medical`

- **Created `add_pmc_review_article.py`**: Review article processing
  - Processes as review article (review_sources/review_chunks tables)
  - Extracts citations from References section
  - Exports citation list to JSON for bulk download
  - Usage: `python add_pmc_review_article.py --pmcid PMC11171117 --domain veterinary --export-refs refs.json`

- **Created `download_pmc_from_file.py`**: Bulk download with resume capability
  - Reads citation JSON from add_pmc_review_article.py
  - Maintains download log for safe re-runs
  - Rate limiting (default 1.5s between requests)
  - B-number sorting for ordered downloads

- **Created `bulk_add_papers.sh`**: Batch processing helper
  - Loops through HTML directory calling add_pmc_article.py
  - Reports success/skip/failure counts
  - Usage: `./bulk_add_papers.sh html/vet veterinary`

- **Created `docs/guides/USAGE_GUIDE.md`**: Comprehensive documentation
  - Quick reference for all three scripts
  - Common workflow examples
  - Error recovery procedures
  - Cost estimation for embeddings

#### 2. **PDF Processing Tools** ⭐ NEW
- **Created `parse_pdf_article.py`**: General PDF parser for structured scientific articles
  - Font-based section detection (analyzes font size/style)
  - Hierarchical section structure (levels 1-3)
  - Blacklist filtering for headers/footers
  - Article boundary detection (title to references)
  - Multiple output formats: json, sections, tree, full
  - Tested on Nature Methods article: 55 sections extracted
  - Usage: `python parse_pdf_article.py PDFs/nature_methods.pdf --output-format json`

- **Created `parse_science_pdf.py`**: Specialized Science journal PDF parser
  - Handles Science journal's unique format (no section headings, multi-article PDFs)
  - DOI extraction from filename, metadata, or PDF text
  - Multi-article handling with previous article skip
  - **Paragraph-based section splitting** (default behavior)
    - Smart heading generation from first sentence
    - Sentence boundary splitting for large paragraphs (max 3,000 chars)
  - Header/footer cleaning
  - Tested on science.1181498.pdf: 9 paragraph sections (576-2,991 chars each)
  - Usage: `python parse_science_pdf.py PDFs/science.1181498.pdf --output-format json`

#### 3. **RAG System Enhancements**
- **Domain-separated answers**: Medical and Veterinary sections + Cross-Domain Synthesis
- **Author-list citations**: Converted ref_ids (B83) to author-year format (Momoi & Matsuu 2020)
- **Improved prompt**: Clearer excerpt type definitions to prevent misclassification
- **Fixed protocol 5**: Corrected method vs limitation field confusion

#### 4. **New Search Tools**
- **`search_references.py`**: Find papers by title, author, PMC ID, ref-id (partial matching)
- **`search_protocols.py`**: Query protocols by modality, pathogen, specimen, vet score
  - Displays identity, performance metrics, excerpts (first 200 chars)
  - Shows source details with `--show-sources` flag

#### 5. **Protocol Extraction Progress**
- **Schema finalized**: 18-field structured extraction with vet transferability
- **Test extraction**: 3 protocols from paper_id=104 (mNGS for viral CSF diagnostics)
- **Cluster support**: Added `--cluster-id` parameter to `extract_protocols.py`
- **Running**: 100 chunks from Cluster 0 (in separate window)
- **Estimated output**: 500-1,000 protocols from full Cluster 0 extraction

#### 6. **Cluster 0 Sub-Clustering (Pathogen-Centric)**
- **Created `subcluster_cluster0.py`**: Pathogen classification + HDBSCAN sub-clustering
- **Pathogen distribution**: Unknown (57%), Bacteria (14%), Mixed (14%), Virus (11%), Parasite (3%), Fungus (1%)
- **Sub-clustering results** (min_cluster_size=20):
  - **Sub-cluster 0**: 607 chunks (mixed pathogens, 84% medical for mixed, 66% vet for unknown)
  - **Sub-cluster 1**: 22 chunks (100% medical, bacteria/mixed focus)
  - **Noise**: 1,390 chunks (68.8%) - high heterogeneity in Cluster 0
- **New table**: `cluster0_subclusters` with pathogen_type metadata

#### 7. **Flexible UMAP Visualization (`plot_cluster0_umap.py`)**
- **Multiple color schemes**:
  - `--color-by domain`: Medical (blue) vs Veterinary (red)
  - `--color-by subcluster`: Each sub-cluster unique color
  - `--color-by pathogen`: Bacteria, virus, fungus, parasite color-coded
- **Label options**:
  - `--add-labels ngs`: Top NGS keywords at cluster centroids
  - `--add-labels pathogen`: Dominant pathogen type labels
- **Generated 6 plots**: domain, pathogen, domain+NGS, subclusters, subclusters+pathogen, subclusters+NGS

#### 8. **Data Additions**
- **Added B83** (Momoi & Matsuu 2020): SFTSV detection in cats via mNGS
  - Initially uploaded as "B100" but already in DB as B83
  - 4 chunks, veterinary domain, PMC7953082

### Critical Finding: Domain Separation in Embedding Space

**Observation:** UMAP visualizations show medical and veterinary literature do NOT cluster together spatially, despite shared NGS methodologies and pathogen targets.

**Implication:** The OpenAI embeddings capture overall semantic content (writing style, journal conventions, domain-specific terminology, clinical context) which dominates over NGS methodological commonalities.

**Why this matters:**
- Embeddings reflect "paper similarity" not "protocol similarity"
- Medical and vet papers discussing the *same* NGS method (e.g., mNGS for CSF diagnostics) appear distant in embedding space
- Current clustering finds domain-segregated topic groups, not cross-domain methodological connections

**What we need:** A projection or metric that emphasizes NGS commonalities while being invariant to domain-specific language.

---

## Next Steps: Cross-Domain Connection Discovery

### The Challenge
How to identify medical-veterinary protocol equivalencies when:
1. Full embeddings emphasize domain differences over methodological similarities
2. Papers using identical NGS workflows may cluster separately by domain
3. Cross-domain knowledge transfer requires finding commonalities despite overall dissimilarity

### Proposed Approaches (Priority Order)

#### **Approach 1: Protocol-Based Alignment** ⭐ (RECOMMENDED - Start Here)
**Concept:** Use extracted protocols as structured anchors to link medical/vet literature

**Implementation:**
1. **Extract all protocols from Cluster 0** (currently running 100 chunks)
2. **Define protocol equivalence criteria**:
   ```python
   same_protocol = (
       modality == modality AND
       pathogen_class == pathogen_class AND
       specimen_type == specimen_type AND
       platform == platform
   )
   ```
3. **Build protocol-paper graph**:
   - Nodes: protocols (deduplicated by identity fields)
   - Edges: protocol_sources linking to papers
   - Colors: medical (blue) vs veterinary (red) papers
4. **Query for cross-domain protocols**:
   ```sql
   SELECT protocol_id, ngs_modality, pathogen_class, specimen_type,
          COUNT(DISTINCT CASE WHEN domain='medical' THEN paper_id END) as med_papers,
          COUNT(DISTINCT CASE WHEN domain='veterinary' THEN paper_id END) as vet_papers
   FROM protocol_sources ps
   JOIN papers p ON ps.paper_id = p.id
   GROUP BY protocol_id, ngs_modality, pathogen_class, specimen_type
   HAVING COUNT(DISTINCT domain) = 2;  -- Both domains
   ```
5. **Output**: List of shared protocols with medical + vet evidence

**Advantages:**
- Uses structured data already being extracted
- Natural for practitioners (think in terms of protocols, not embeddings)
- Can compare performance metrics, limitations across domains
- Immediate actionability

**Next script to write:** `analyze_shared_protocols.py`

---

#### **Approach 2: NGS Feature Space (Lighter-weight Alternative)**
**Concept:** Project onto NGS-specific features instead of full embeddings

**Implementation:**
1. **Define NGS vocabulary** (60-100 keywords):
   ```python
   ngs_keywords = ['mngs', 'metagenomic', 'illumina', 'nanopore',
                   'csf', 'bacteria', 'viral', 'sensitivity', ...]
   ```
2. **Create NGS-specific TF-IDF vectors** from chunk text
3. **Cluster on NGS features only** (ignoring other semantic content)
4. **Expect**: Medical and vet papers discussing "mNGS for bacterial sepsis" cluster together

**Advantages:**
- Simple to implement (scikit-learn TfidfVectorizer)
- Interpretable (can see which keywords drive clustering)
- Fast re-clustering without LLM calls

**Disadvantages:**
- Keyword-based (may miss paraphrases, synonyms)
- Loses semantic depth of embeddings

**Implementation difficulty:** LOW (2-3 hours)

---

#### **Approach 3: Canonical Correlation Analysis (CCA)**
**Concept:** Find linear projections of medical and vet embeddings that maximize correlation

**Implementation:**
1. **Separate embeddings** into medical and veterinary subsets
2. **Run CCA** to find directions of maximum correlation:
   ```python
   from sklearn.cross_decomposition import CCA
   cca = CCA(n_components=10)
   X_medical_cca, X_vet_cca = cca.fit_transform(X_medical, X_vet)
   ```
3. **Cluster in CCA space** (where domains are aligned)
4. **Visualize** with UMAP on CCA-transformed embeddings

**Advantages:**
- Statistically principled
- Maximizes cross-domain correlation
- Preserves some semantic structure

**Disadvantages:**
- Requires equal sample sizes (may need downsampling)
- Linear method (may miss nonlinear relationships)
- Harder to interpret what CCA directions represent

**Implementation difficulty:** MEDIUM (1 day)

---

#### **Approach 4: Contrastive Learning / Domain Adaptation**
**Concept:** Train a model to create domain-invariant embeddings

**Implementation:**
1. **Collect triplets**: (anchor_med, positive_vet, negative_vet)
   - Anchor: Medical chunk mentioning "mNGS for CSF"
   - Positive: Veterinary chunk with same protocol (from protocol_sources)
   - Negative: Veterinary chunk with different protocol
2. **Fine-tune embedding model** (e.g., sentence-transformers) with triplet loss
3. **Re-embed all chunks** with fine-tuned model
4. **Cluster** in new embedding space

**Advantages:**
- Learned representation optimized for cross-domain similarity
- Can handle complex, nonlinear relationships
- State-of-the-art approach

**Disadvantages:**
- Requires training data (protocol_sources provides positive pairs)
- Computationally expensive
- Need enough protocol diversity for training

**Implementation difficulty:** HIGH (3-5 days)

---

#### **Approach 5: Multi-View Clustering**
**Concept:** Cluster using both semantic embeddings AND protocol features simultaneously

**Implementation:**
1. **Create two feature matrices**:
   - View 1: OpenAI embeddings (1536-d)
   - View 2: Protocol features (one-hot encoded modality, pathogen, specimen)
2. **Use multi-view clustering algorithm** (e.g., Multi-View K-Means or Co-Training)
3. **Weight views**: Emphasize protocol features for cross-domain similarity

**Advantages:**
- Leverages both semantic and structured information
- Can control emphasis on protocol vs domain similarity

**Disadvantages:**
- Requires protocol extraction to be complete
- More complex implementation

**Implementation difficulty:** MEDIUM-HIGH (2-3 days)

---

#### **Approach 6: Graph-Based Linking**
**Concept:** Build a knowledge graph and query for paths between medical and vet nodes

**Implementation:**
1. **Create graph**:
   - Nodes: chunks, protocols, pathogens, specimens, platforms
   - Edges: chunk→protocol (uses/defines), protocol→pathogen, protocol→specimen
2. **Query for bridges**:
   ```cypher
   MATCH (med_chunk:Chunk {domain:'medical'})-[:USES]->(p:Protocol),
         (vet_chunk:Chunk {domain:'veterinary'})-[:USES]->(p)
   RETURN p, med_chunk, vet_chunk
   ```
3. **Visualize** bipartite network (medical papers | protocols | vet papers)

**Advantages:**
- Explicit relationship modeling
- Can traverse multiple hops (chunk→protocol→pathogen→specimen)
- Natural for knowledge graphs

**Disadvantages:**
- Requires graph database (Neo4j) or NetworkX
- Complex setup

**Implementation difficulty:** MEDIUM-HIGH (2-4 days)

---

### Recommended Path Forward

**Phase 2A: Protocol-Based Alignment (Immediate - This Week)**
1. ✅ Complete Cluster 0 protocol extraction (100→2,019 chunks)
2. Create `analyze_shared_protocols.py` to find cross-domain protocol matches
3. Generate report: "Top 20 NGS Protocols Used in Both Medical and Veterinary Diagnostics"

**Phase 2B: NGS Feature Space (Next Week)**
1. Implement TF-IDF on NGS vocabulary
2. Re-cluster Cluster 0 on NGS features only
3. Compare results to full embedding clustering

**Phase 2C: Advanced Methods (Optional - If Needed)**
1. Try CCA if protocol-based approach shows promise
2. Evaluate multi-view clustering if we need finer granularity

---

### Questions for Next Session

- Complete Cluster 0 protocol extraction (2,019 chunks)?
- Implement `analyze_shared_protocols.py` to find cross-domain equivalencies?
- Try NGS-vocabulary TF-IDF clustering as lightweight alternative?
- Visualize protocol-paper bipartite graph (medical papers | protocols | vet papers)?
- Build citation network to map knowledge flow?
- Expand to other veterinary domains (wildlife, aquatic, livestock)?

---

## Quick Start for New Session

```bash
# 1. Check environment
cd /Users/david/work/informatics_ai_workflow
conda activate openai
psql mngs_kb -c "SELECT COUNT(*) FROM chunk_clusters;"

# 2. Read this file
cat SESSION_CONTEXT.md

# 3. Check recent clustering results
psql mngs_kb -c "SELECT * FROM cluster_gap_scores;"
python analyze_cluster_topics.py --summary-only

# 4. Review gap analysis
cat gap_analysis_final.md

# 5. Ask user: "Where would you like to continue?"
```

---

## Project Reorganization (2026-02-25)

**Directory structure simplified from 20+ items to 9 top-level directories:**

```
informatics_ai_workflow/
├── config/             # Database configurations (local, supabase)
├── data/               # Data files (raw/, processed/, backups/)
├── docs/               # All documentation (guides/, analysis/, reference/, sessions/)
├── logs/               # Log files
├── scripts/            # All Python scripts (data_ingestion/, query/, analysis/, utilities/)
├── sql/                # Database schemas
├── src/                # Shared modules (extractors/, admin_blacklist.py, query_analyzer.py)
├── tests/              # Test scripts (formerly various_testing/)
└── .supabase/          # Supabase configuration (hidden)
```

**Key changes:**
- Consolidated all guides into `docs/guides/` (7 guide files)
- Organized docs into subdirectories: `analysis/`, `reference/`, `sessions/`
- Moved data files to appropriate subdirectories
- Renamed `various_testing/` → `tests/`
- Hidden Supabase config as `.supabase/`
- All tracked files preserve git history via `git mv`

**All functionality verified working:**
- ✅ Web app (streamlit) loads correctly
- ✅ Query scripts work with new structure
- ✅ Import statements unchanged
- ✅ Database config system functional
- ✅ Documentation paths updated

---

## Session 2026-02-25: Infrastructure & Planning

### Major Accomplishments

#### 1. **Supabase Local Setup** ⭐
- Initialized Supabase in project directory
- Dumped and restored `mngs_kb` database (656MB, 3,272 chunks)
- Verified all data: 185 papers, 103 protocols, 3,272 clustered chunks
- **Access:** http://127.0.0.1:54323 (Supabase Studio)

#### 2. **Database Configuration System** ⭐⭐
- Created centralized config system in `config/` directory
- **Files created:**
  - `config/db_config.py` - Connection utility module
  - `config/db_local.json` - Homebrew PostgreSQL config
  - `config/db_supabase.json` - Supabase local config
  - `config/README.md` - Complete documentation
- **Benefits:**
  - Single config change switches entire system
  - Environment variable support (`DB_CONFIG`)
  - All scripts now support `--db-config` parameter
  - Works with local PostgreSQL and Supabase seamlessly

#### 3. **Query Logging Integration** ⭐
- Updated `query_logger.py` to use config system
- Integrated into `web_query.py` (Streamlit app)
- **Features:**
  - Automatic query logging with embeddings
  - Similar past query detection (vector similarity)
  - Session-based query history
  - Toggle controls in web app sidebar
- **Documentation:** `docs/guides/QUERY_LOGGING.md`
- **Verified working:** Tested log, search, and retrieval functions

#### 4. **Project Reorganization** ⭐⭐
- **Simplified structure:** 20+ items → 9 top-level directories
- **Key changes:**
  - Consolidated `guides/` → `docs/guides/`
  - Organized docs into subdirectories (analysis, reference, sessions, schemas)
  - Moved data files to `data/processed/` and `data/backups/`
  - Renamed `various_testing/` → `tests/`
  - Hidden Supabase config as `.supabase/`
- **Preserved git history:** Used `git mv` for all tracked files (13 renames)
- **Created tool:** `reorganize_project.sh` with smart file detection
- **Verified:** All imports, scripts, and web app still functional

#### 5. **SQL Schema Organization**
- Moved `sentence_schema.sql` → `sql/`
- Moved `query_log_schema.sql` → `sql/`
- Created `sql/README.md` with comprehensive schema documentation
- **All schemas now in version control and documented**

#### 6. **LangChain Migration Analysis** 📊
- Analyzed current OpenAI API usage (14 files, 4 patterns)
- Documented LangChain equivalents for all patterns
- Created migration strategies (3 options)
- **Key insight:** LangChain essential for LM Studio support
- **Recommendation:** Incremental migration (4-5 days over 1 month)
- **Documentation:** `docs/LANGCHAIN_MIGRATION.md`

#### 7. **LM Studio Integration Planning** 🚀
- Analyzed cost/performance tradeoffs
- **Cost savings:** 18-67% reduction with local models
- **Task-based routing strategy:**
  - Embeddings: OpenAI (quality matters)
  - Decomposition: LM Studio (simple task, free)
  - Protocols: OpenAI (complex structured output)
  - Answers: OpenAI (user-facing quality)
- **Documentation:** `docs/LM_STUDIO_INTEGRATION.md`

#### 8. **Agent Concepts Documentation** 📚
- Clarified difference between chains and agents
- **Chain (current system):** Fixed workflow, you control steps
- **Agent (future option):** Dynamic workflow, LLM decides steps
- **Conclusion:** Current approach is sophisticated chain (not agent), works well
- **Documentation:** `docs/AGENTS_EXPLAINED.md`

### Files Created/Modified

**New files:**
- `config/db_config.py` - Database connection utility
- `config/db_local.json` - Local PostgreSQL config
- `config/db_supabase.json` - Supabase config
- `config/README.md` - Config system documentation
- `sql/README.md` - SQL schema documentation
- `docs/LANGCHAIN_MIGRATION.md` - Migration analysis
- `docs/LM_STUDIO_INTEGRATION.md` - LM Studio planning
- `docs/AGENTS_EXPLAINED.md` - Agent concepts
- `reorganize_project.sh` - Smart reorganization tool

**Modified files:**
- `scripts/query/query_kb.py` - Added `--db-config` parameter
- `scripts/query/aspect_search.py` - Added `--db-config` parameter
- `scripts/query/web_aspect_search.py` - Uses config system
- `scripts/query/web_query.py` - Query logging + config system
- `scripts/query/query_logger.py` - Uses config system
- `SESSION_CONTEXT.md` - Updated with reorganization and new features
- `.gitignore` - Updated for new structure

### Technical Decisions

**Database Configuration:**
- JSON-based configs for easy editing
- Environment variable override support
- Example files for version control
- Passwords in gitignored configs

**Query Logging:**
- Session-based tracking via UUID
- 75% similarity threshold for similar queries
- Optional user_id support for future
- IVFFlat index for fast similarity search

**Project Structure:**
- Grouped by type (code, data, docs, config)
- Hidden configs follow Unix conventions (`.supabase/`)
- Tests directory for clarity
- All docs consolidated under `docs/`

**LangChain Strategy:**
- Incremental migration (low risk)
- Start with embeddings (easy win)
- Abstraction layer for provider switching
- Keep current code working during migration

### Key Learnings

1. **`!` in .gitignore** = Negate (create exceptions to ignore patterns)
2. **`git mv` vs `mv`** = Use git mv for tracked files to preserve history
3. **Git tracks files, not directories** = Can't `git mv` empty directories
4. **LangChain value** = Critical for multi-provider support (OpenAI, LM Studio, etc.)
5. **Chains vs Agents** = Chains have fixed workflows (your system), agents self-direct
6. **Supabase local** = Creates new DB instance, not connection to existing
7. **Cost optimization** = Local models (LM Studio) can save 67% on LLM costs

### Next Steps

**Immediate priorities:**
1. Commit today's changes (reorganization + config system + query logging)
2. Test Supabase Studio for database exploration
3. Document any findings from visual database browsing

**Short-term (next session):**
1. **If proceeding with LangChain:**
   - Create `config/llm_config.py` abstraction layer
   - Migrate one pilot file (e.g., `decompose_query.py`)
   - Test with OpenAI (verify no behavior change)
2. **If adding LM Studio:**
   - Download and setup LM Studio
   - Test local models (Mistral-7B, Llama3-8B)
   - Compare quality vs OpenAI for various tasks
3. **Otherwise:**
   - Continue protocol extraction from Cluster 0
   - Build protocol-based alignment tool
   - Implement cross-domain protocol matching

**Long-term:**
- Complete protocol extraction (2,019 chunks)
- Implement `analyze_shared_protocols.py`
- Consider NGS-vocabulary TF-IDF clustering
- Evaluate multi-view clustering approaches

---

## Session 2026-03-03: R-based PCA Analysis & Graph Clustering

### Major Accomplishments

#### 1. **R Analysis Toolkit for Embeddings** ⭐⭐
- **Created `scripts/r_analysis/` directory** with complete R workflow for PCA analysis
- **Files created:**
  - `embedding_utils.R` - Core functions for loading embeddings and running PCA
  - `pca_visualization.R` - Plotting functions (scree plots, PC scatter plots, loadings)
  - `example_pca_analysis.Rmd` - Complete RMarkdown notebook template
  - `README.md` - Comprehensive documentation with use cases

#### 2. **Database Integration**
- R functions connect directly to Supabase using `config/db_supabase.json`
- Handles pgvector format (parses "[0.1, 0.2, ...]" strings to numeric vectors)
- Fixed type casting issue: `chunk_clusters.chunk_id` is text, joins require `::text` cast
- Meaningful row names: `paper_42_1234` format (source_type + ref_id + chunk_id)

#### 3. **PCA Analysis Results**
- **Low variance per PC** (expected for 1536D embeddings):
  - PC1: 7.2%, PC2: 6.2%, PC3: 3.4%
  - First 10 PCs: ~32% variance
  - Similar to scRNA-seq data structure
- **Insight**: OpenAI embeddings distribute information across many dimensions

#### 4. **Graph-Based Clustering (Seurat-style)** ⭐⭐⭐
- **Implemented Louvain clustering on k-NN graph in PCA space**
- **Workflow:**
  1. Select n PCs (typically 30-50)
  2. Build k-nearest neighbor graph in PC space (k=20)
  3. Run Louvain community detection at multiple resolutions (0.4, 0.8, 1.2)
  4. Run UMAP on PC space (not original 1536D embeddings)
  5. Visualize clusters on PC-derived UMAP

- **Rationale**:
  - Clusters in higher-dimensional space (30D vs 2D UMAP)
  - Reduces compression artifacts from UMAP visualization
  - Follows single-cell RNA-seq best practices (Seurat workflow)
  - May reveal finer-grained protocol clusters

#### 5. **Key Insights from Analysis**

**Why Seurat-style approach for embeddings?**
- High noise in original HDBSCAN clustering (36.8% unclustered)
- Need to find NGS-specific axes independent of domain language
- OpenAI embeddings capture overall semantic content (writing style, domain conventions)
- PCA may separate "NGS methodology" from "domain-specific language"

**Potential use case:**
- If PC1 separates medical vs veterinary (domain axis)
- And PC2-10 separate by pathogen/specimen/platform (protocol axes)
- Then cluster on PC2-10 only → domain-invariant protocol groups

**Analogy to scRNA-seq:**
- Both have high-dimensional data with distributed information
- Both need dimensionality reduction for clustering
- Both benefit from graph-based clustering in reduced space
- Both show low variance per component (no dominant axes)

### Technical Decisions

**R Function Design:**
- `get_embeddings()` returns data frame (not RDS) for RMarkdown compatibility
- Embedding dimensions as columns (`emb_1` through `emb_1536`)
- Metadata preserved (domain, cluster_id, umap_x, umap_y)
- Flexible filtering (by domain, cluster, source_type)

**Graph Construction:**
- k-NN graph (k=20 neighbors typical)
- Louvain algorithm for community detection
- Multiple resolutions tested (0.4, 0.8, 1.2)
- Note: Simplified SNN (not full Jaccard weighting, but sufficient)

**UMAP on PCs:**
- Run UMAP on 30D PC space (not original 1536D)
- Coordinates stored as `umap_pc_x`, `umap_pc_y`
- Distinguishes from original UMAP (`umap_x`, `umap_y`)

### Files Created

**R Analysis Tools:**
- `scripts/r_analysis/embedding_utils.R` - Database loading, PCA, filtering
- `scripts/r_analysis/pca_visualization.R` - Plotting functions
- `scripts/r_analysis/example_pca_analysis.Rmd` - Example notebook
- `scripts/r_analysis/README.md` - Complete documentation

### Terminology Clarifications

**Correct terms:**
- "Graph-based clustering on k-NN graph in PCA space"
- "Louvain clustering" (algorithm name)
- "SNN-graph clustering" (Seurat terminology, with caveats)

**NOT correct:**
- "Scaled nearest neighbors" (doesn't exist - refers to data preprocessing)
- "k-NN clustering" (ambiguous)
- "PCA clustering" (PCA is dimensionality reduction, not clustering)

**What "scaled" means in Seurat:**
- Z-score normalization of input data (mean=0, sd=1 per feature)
- Done BEFORE PCA to give equal weight to all genes
- Not needed for OpenAI embeddings (already L2-normalized)

### Next Steps

#### Immediate (Next Session)
1. **Run Louvain clustering on full dataset or Cluster 0**
   - Test multiple resolutions (0.4, 0.8, 1.2)
   - Compare to original HDBSCAN results
   - Calculate gap scores for new clusters

2. **Map cluster assignments back to chunks**
   - Export cluster_chunk_mapping.csv
   - Prepare for LLM-based cluster summarization
   - Identify protocol-rich clusters

3. **Analyze PC structure**
   - Test if PC1 separates domains (t-test)
   - Identify which PCs capture NGS methodology vs domain language
   - Consider clustering on subset of PCs (exclude domain-driven PCs)

#### Short-term
1. **Cluster summarization**
   - Use existing LLM infrastructure to summarize each cluster
   - Identify dominant NGS themes per cluster
   - Compare to original HDBSCAN cluster themes

2. **Protocol-based alignment** (original Phase 2 goal)
   - Cross-reference Louvain clusters with extracted protocols
   - Find medical-vet protocol equivalencies
   - Build protocol-paper bipartite graph

3. **Optimize clustering parameters**
   - Test different n_pcs (20, 30, 50, 100)
   - Test different k values (10, 20, 30)
   - Evaluate cluster quality (silhouette scores, gap statistics)

### Questions for Next Session

- Which resolution gives most meaningful clusters (0.4, 0.8, 1.2)?
- Do new clusters reduce noise (vs 36.8% in HDBSCAN)?
- Does PC1 separate medical vs veterinary domains?
- Can we find domain-invariant protocol clusters by excluding certain PCs?
- Should we run this on full dataset (3,272 chunks) or Cluster 0 only (2,019 chunks)?

### Key Learnings

1. **PCA variance structure**: Low per-PC variance expected for semantic embeddings
2. **Graph clustering benefits**: Works in higher dimensions, reduces UMAP compression artifacts
3. **Seurat workflow applies**: Single-cell RNA-seq methods transfer to embedding analysis
4. **pgvector format**: Returns embeddings as text strings "[...]", need parsing in R
5. **Type casting matters**: PostgreSQL text vs integer columns require explicit casts in joins

---

**Last updated:** 2026-03-10
**Phase:** Phase 2 - Database schema consolidation and monitoring tools
**Database state:** 3,272 chunks, 3 clusters, 188 papers (185 papers + 3 reviews), 103 protocols, 458 citations
**Database access:** Supabase local (127.0.0.1:54322/54323)
**Key accomplishment:** Unified schema - merged review_sources/review_chunks into papers/paper_chunks
**Next priority:** Update data ingestion scripts for unified schema, consider journal metadata enrichment

**Recent additions:**
- **2026-03-10:** Schema migration (merged review tables into papers), database summary views, citation extraction from review 220
- **2026-03-03:** R-based PCA analysis toolkit, graph-based clustering (Louvain), Seurat-style workflow
- **2026-02-25:** Supabase setup, database config system, query logging, project reorganization, LangChain/LM Studio planning
- **2026-02-20:** Consolidated data ingestion scripts, PDF processing tools
- **2026-02-19:** Clustering analysis, admin filtering, domain tagging

---

## Session 2026-03-10: Schema Consolidation & Monitoring Tools

### Major Accomplishments

#### 1. **Database Schema Migration: Unified Papers Table** ⭐⭐⭐
- **Merged review_sources and review_chunks into papers and paper_chunks**
- Added `doc_type` column to distinguish reviews from research papers
- Migrated all data, foreign keys, and references
- **Impact:** Simpler schema, unified queries, eliminated redundancy

**Data migrated:**
- 3 review sources → papers
- 82 review chunks → paper_chunks
- 782 review sentences → paper_sentences
- 290 citations updated to reference papers
- 52 protocol_sources updated
- 38 chunk_clusters updated
- 324 chunk_citations updated and FK relinked

**Tables dropped:**
- `review_sources`, `review_chunks`, `review_sentences`
- Columns removed: `citations.source_id`, `protocol_sources.review_chunk_id`

**Files created:**
- `sql/migrate_merge_sources.sql` - Main migration
- `sql/fix_chunk_clusters.sql` - Handle "review_23" ID format
- `sql/migrate_review_sentences.sql` - Sentence migration
- `sql/cleanup_old_tables.sql` - Drop old tables + add unique constraint
- `docs/sessions/migration_2026-03-09_merge_sources.md` - Full documentation
- Backup: `data/backups/supabase_pre_merge_20260309_174458.sql`

#### 2. **Database Summary Views** ⭐⭐
- **Created `database_summary` view** - Single-row overview with 35+ metrics
- **Created `database_summary_detailed` view** - Category breakdown
- Provides instant health check and monitoring
- Auto-updating, no manual refresh needed
- Documentation: `docs/guides/DATABASE_SUMMARY_VIEWS.md`

**Key metrics tracked:**
- Paper counts (by type, domain)
- Chunk statistics (counts, embeddings, coverage)
- Citations (total, linked, PMC IDs)
- Protocols (counts, modalities, pathogens)
- Clusters (assignments, UMAP coordinates)
- Sentences (counts, embeddings)
- Database sizes (storage metrics)

**Usage:**
```sql
SELECT * FROM database_summary;  -- All stats in one row
SELECT * FROM database_summary_detailed WHERE category = 'Papers by Type';
```

#### 3. **Citation Extraction for Review 220** ⭐
- **Discovered** review 220 (tick-borne pathogens) had no citations extracted
- **Created** `scripts/data_ingestion/extract_citations_from_paper.py`
- **Extracted** 168 citations from review 220
  - 114 with PMC IDs (available for download)
  - 167 with DOIs
- **Exported** citations to `data/processed/wildlife_citations.json`
- **Fixed** missing UNIQUE constraint on citations table

**All 3 reviews now have citations:**
1. Paper 218 (medical): 168 citations
2. Paper 219 (veterinary - companion animals): 122 citations
3. Paper 220 (veterinary - wildlife/ticks): 168 citations
- **Total:** 458 citations across 3 reviews

#### 4. **Schema Fixes**
- Added `UNIQUE (ref_id, paper_id)` constraint to citations table
- Constraint was lost during migration when `source_id` was dropped
- Added to cleanup script for future migrations

### Technical Decisions

**Why merge review_sources and papers?**
- 95% schema overlap - only difference was doc_key vs doi
- "Review" vs "paper" is document type, not structural difference
- Simpler queries, unified codebase
- Future flexibility for other document types (guidelines, SOPs)

**Why not add a "corpus" field?**
- `domain` field already serves this purpose (medical/veterinary/both)
- Finer granularity (companion vs wildlife vs livestock) could be added later
- Journal metadata might be better indicator of publishing communities

**Chunk_clusters ID format issue:**
- IDs stored as "review_23" not just "23" 
- Required special handling during migration
- Fixed with string prefix matching

### Files Created/Modified

**New scripts:**
- `scripts/data_ingestion/extract_citations_from_paper.py` - Extract citations from existing papers
- `sql/create_database_summary_view.sql` - Summary view definitions
- `sql/migrate_merge_sources.sql` - Main migration script
- `sql/fix_chunk_clusters.sql` - Cluster ID format fix
- `sql/migrate_review_sentences.sql` - Sentence migration
- `sql/cleanup_old_tables.sql` - Table cleanup + constraint fix

**Documentation:**
- `docs/sessions/migration_2026-03-09_merge_sources.md` - Complete migration log
- `docs/guides/DATABASE_SUMMARY_VIEWS.md` - View usage guide

**Modified:**
- `SESSION_CONTEXT.md` - Updated with today's changes
- Database schema - Simplified from dual to unified structure

### Current Database State

**Final counts (via `database_summary` view):**
- **Papers:** 188 total (185 research papers, 3 reviews)
  - Medical: 115 papers
  - Veterinary: 73 papers
- **Chunks:** 2,924 (2,842 papers + 82 reviews)
  - 99% embedded
  - Average 2,020 chars/chunk
- **Citations:** 458 total from 3 reviews
  - 299 unique PMC IDs available
- **Protocols:** 103 protocols from 13 papers
- **Clusters:** 3,272 chunks in 3 clusters
- **Sentences:** 31,805 total (100% embedded)
- **Database size:** 579 MB

### Domain Representation (Updated)

With review 220 citations extracted, corpus balance improved:
- **Medical:** 1 review + 114 papers
- **Veterinary (companion):** 1 review + ~71 papers
- **Veterinary (wildlife/ticks):** 1 review + potential new papers from citations

**Note on wildlife corpus:** User identified that publishing communities are often siloed (companion animal vs wildlife journals). Future enhancement could track journal subject scope via external services (e.g., NLM Catalog, Scopus subject areas).

### Known Issues & Considerations

**Scripts needing updates for new schema:**
1. `add_pmc_review_article.py` - Still references review_sources/review_chunks (deprecated)
2. `chunk_vet_review.py` - May reference old tables
3. Any code filtering by `review_sources` table - now use `papers WHERE doc_type='review'`

**Recommendation:** Audit all scripts in `scripts/data_ingestion/` for references to dropped tables.

### Next Steps

**Immediate:**
1. Update `add_pmc_review_article.py` to use papers table with doc_type='review'
2. Audit data ingestion scripts for review_sources references
3. Test modified scripts with new schema

**Short-term:**
1. **Journal metadata enrichment** - Consider adding journal subject scope
   - Could use NLM Catalog API, Crossref, or Scopus
   - Would help identify publishing community silos
   - Could add `journal_subjects` array field to papers
2. **Download wildlife citations** - 114 PMC IDs from review 220
3. **Corpus labeling** - If needed, add `corpus` or `category` field within veterinary domain

**Long-term:**
1. Continue protocol extraction and cross-domain analysis
2. Update documentation to reflect unified schema
3. Consider materialized views for database_summary if performance becomes issue

### Key Learnings

1. **PostgreSQL Views are powerful** - Auto-updating, no maintenance, great for monitoring
2. **Chunk ID formats vary** - "review_23" vs "23" required special handling
3. **Unique constraints matter** - Lost constraint during migration caused insertion failures
4. **Domain vs Corpus** - Domain = broad category (medical/vet), corpus = publishing community
5. **Citation extraction workflow** - PMCExtractor.extract_refs() returns dict, not list
6. **Backup before migration** - Supabase CLI: `supabase db dump --local`

---

**Session duration:** ~3 hours
**Lines of code written:** ~800 (migration scripts + extraction script + views)
**Database changes:** 6 tables dropped, 1 column added, 1 constraint added, 2 views created
**Data migrated:** 3,248 chunks + 782 sentences + 290 citations + numerous FK updates
**Success rate:** 100% - all data migrated without loss

