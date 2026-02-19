# NGS Knowledge Base — Session Context & Handoff

**Project:** Cross-domain NGS diagnostic protocol knowledge base (medical → veterinary translation)
**Owner:** David
**Environment:** `/Users/david/work/informatics_ai_workflow`
**Database:** PostgreSQL `mngs_kb` (localhost, Homebrew install at `/opt/homebrew/opt/postgresql@16`)
**Python env:** `miniconda3` at `/Users/david/miniconda3/envs/openai`

---

## Project Overview

### Research Goal
Build a knowledge base to identify **gaps and transferability** of NGS diagnostic protocols from medical to veterinary practice.

**Key question:** *"What NGS protocols are used in the medical community, and how do they inform what can be done in the veterinary field?"*

**Phase 1 (current):** Extract structured protocol records from medical literature
**Phase 2 (planned):** Ingest veterinary literature, cluster by topic, compute medical-vet gap scores
**Phase 3 (planned):** Protocol resolution (follow citation chains to external SOPs, protocols.io, CDC guidelines)

### Intellectual Framework

The **protocol** is the unit of transferability, not the paper. A protocol is:
- **Identity:** modality (mNGS, targeted NGS, WGS), pathogen class, specimen type, platform
- **Context:** typed verbatim excerpts (method, performance, limitations, biology, obstacles)
- **Transferability:** veterinary applicability score (0-3) + obstacle summary

Papers cite protocols; protocols accumulate evidence across sources. The `protocol_sources` bridge table tracks which chunks describe/use/critique each protocol.

---

## Current State (as of 2026-02-19)

### What's Built

#### 1. Database Schema (v2)
- **Core tables (v1):** `review_sources`, `review_chunks`, `papers`, `paper_chunks`, `citations`, `chunk_citations`
- **New tables (v2):** `protocols`, `protocol_sources`
- **Migration:** `migrate_v2.sql` applied to live DB; `create_schema.sql` updated for fresh installs
- **Schema file:** `/Users/david/work/informatics_ai_workflow/create_schema.sql`

**Key relationships:**
```
papers ← citations.paper_id
papers ← paper_chunks.paper_id
paper_chunks ← protocol_sources.paper_chunk_id → protocols
review_chunks ← protocol_sources.review_chunk_id → protocols
```

**Domain tagging:** `papers.domain` and `review_sources.domain` added (`'medical' | 'veterinary' | 'both'`)

#### 2. Data Loaded
- **Review article:** 1 source (fcimb-14-1458316), 22 chunks, 168 citations (medical NGS review)
- **Cited papers:** 114 papers, 2,309 chunks (downloaded PMC HTMLs, chunked, embedded, loaded)
- **Embeddings:** OpenAI `text-embedding-3-small` 1536-dim vectors on all chunks
- **Protocols extracted:** 3 NGS protocols from 10 test chunks (paper_id=104, OROV paper)

#### 3. Extractors Package (`extractors/`)
Refactored chunking into source-agnostic interface:
- **`extractors/base.py`:** Abstract `BaseExtractor` class (defines `chunk()`, `extract_refs()`, `html_fragment()`)
- **`extractors/pmc.py`:** PMC HTML extractor (handles both `B`-style and `R`-style ref IDs)
- **`extractors/__init__.py`:** Package exports

**Tested on:**
- Main review: 22 chunks, 168 refs
- B80 (PMC12520762): 14 chunks, 23 refs

#### 4. Protocol Extraction (`extract_protocols.py`)
LLM-powered structured extraction using OpenAI's JSON schema mode:
- **Model:** `gpt-4o-mini` (default)
- **Schema:** 18-field protocol schema with typed verbatim excerpts
- **NGS focus:** Prompt explicitly excludes RT-PCR, serology, culture (NGS-only extraction)
- **Output:** Populates `protocols` + `protocol_sources` tables
- **Deduplication:** Finds existing protocols by identity match (modality + pathogen + specimen + platform)

**Extraction fields:**
- Identity: `ngs_modality`, `pathogen_class`, `clinical_context`, `specimen_type`, `platform`, `bioinformatics_pipeline`
- Performance: `sensitivity`, `specificity`, `turnaround_hours`
- Typed excerpts: `excerpt_method`, `excerpt_performance`, `excerpt_limitations`, `excerpt_biology`, `excerpt_obstacles`, `excerpt_transferability`
- Vet assessment: `vet_transferability_score` (0-3), `vet_obstacle_summary`
- Mention type: `defines | uses | validates | critiques | adapts | citation_only`

**Current extraction quality:**
- ~2 out of 3 accurate (occasional RT-PCR misclassification as `targeted_NGS`)
- Edge cases acceptable per user preference

#### 5. Query System (`query_kb.py`)
RAG pipeline with BM25 sentence re-ranking:
- **Step 1:** Embed query with OpenAI
- **Step 2:** pgvector cosine search across `review_chunks` + `paper_chunks`
- **Step 3:** Build context with ref_id citations
- **Step 4:** GPT-4o-mini generates cited answer
- **Step 5 (optional --quote):** BM25 re-rank sentences within chunks, display verbatim quotes

**Features:**
- `--quote` flag: Extract top-N BM25-ranked sentences per chunk (no extra API calls)
- `--show-chunks`: Print retrieved chunks before answer
- Inline citation cleaning (strips `1 , 17 – 21` artifacts)
- Abbreviation-aware sentence splitting (`Fig.`, `et al.`, `e.g.` don't trigger splits)

---

## File Inventory

### Core Scripts
| File | Purpose | Status |
|------|---------|--------|
| `setup_db.py` | Create PostgreSQL database + schema | Working |
| `create_schema.sql` | Full v2 schema (fresh install) | ✅ v2 |
| `migrate_v2.sql` | v1→v2 migration (live DB) | ✅ Applied |
| `chunk_article.py` | Original PMC chunker (now superseded by extractors) | Legacy |
| `download_pmc.py` | Download PMC HTMLs from reference list | Working |
| `embed_chunks.py` | Generate OpenAI embeddings for chunks | Working |
| `load_chunks.py` | Load review article chunks → DB | Working |
| `load_paper_chunks.py` | Load cited paper chunks → DB | Working |
| `extract_protocols.py` | LLM extraction of protocols from chunks | ✅ Phase 1 |
| `query_kb.py` | RAG query with BM25 quote extraction | ✅ Phase 1 |

### Extractors Package
| File | Purpose |
|------|---------|
| `extractors/__init__.py` | Package exports |
| `extractors/base.py` | Abstract base class |
| `extractors/pmc.py` | PMC HTML extractor |

### Data Files
| Path | Content |
|------|---------|
| `html/` | 116 PMC HTMLs (B1-B168 with gaps, downloaded) |
| `pmc_chunks/` | 115 JSON files (chunked papers without embeddings) |
| `chunks.json` | Review article chunks |
| `embeddings.json` | Review article embeddings |
| `reference_index.json` | Review article reference metadata |
| `download_log.json` | PMC download tracking |

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
```

### OpenAI API
```bash
# Key stored in environment (check with)
echo $OPENAI_API_KEY
```

---

## Common Tasks

### Run Protocol Extraction
```bash
cd /Users/david/work/informatics_ai_workflow
conda activate openai

# Dry-run (test extraction without DB writes)
python extract_protocols.py --dry-run --limit 5

# Extract from specific paper
python extract_protocols.py --source papers --paper-id 104

# Full extraction (all chunks)
python extract_protocols.py
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
psql mngs_kb -c "SELECT COUNT(*) FROM papers;"
psql mngs_kb -c "SELECT COUNT(*) FROM paper_chunks WHERE embedding IS NOT NULL;"
psql mngs_kb -c "SELECT COUNT(*) FROM protocols;"
psql mngs_kb -c "SELECT ngs_modality, COUNT(*) FROM protocols GROUP BY ngs_modality;"
```

### View Extracted Protocols
```sql
-- List all protocols
SELECT id, ngs_modality, pathogen_class, specimen_type,
       vet_transferability_score,
       LEFT(excerpt_method, 100)
FROM protocols;

-- Protocol with sources
SELECT p.id, p.ngs_modality, pc.heading, pap.pmc_id
FROM protocols p
JOIN protocol_sources ps ON ps.protocol_id = p.id
JOIN paper_chunks pc ON pc.id = ps.paper_chunk_id
JOIN papers pap ON pap.id = ps.paper_id;
```

---

## Next Steps (Planned)

### Immediate (Phase 1 completion)
1. **Run full extraction** on all 2,309 paper chunks (~$5-10 in API costs, ~2-3 hours)
2. **Validate extraction quality** — review sample of 20-30 protocols for accuracy
3. **Extract from review article** chunks (22 chunks, should yield high-quality NGS protocols)

### Phase 2: Veterinary Corpus & Gap Analysis
1. **Identify veterinary NGS literature** (PubMed search or in-house sources)
2. **Ingest veterinary papers** (same pipeline: download → chunk → embed → load, tag `domain='veterinary'`)
3. **Cluster all chunks** (HDBSCAN on embeddings) to find topic groups
4. **Compute gap scores** per cluster (medical:veterinary ratio)
5. **Update `query_kb.py`** to report gap context in answers

### Phase 3: Protocol Resolution (Optional)
1. **Implement `resolve_protocols.py`** (follow citation chains to external protocol sources)
2. **Add downloaders:** `protocols_io.py`, `cdc.py`, `woah.py`, `github.py`
3. **Populate `protocol_citations` table** (tracking when papers cite external SOPs)

---

## Known Issues & Edge Cases

### Protocol Extraction
- **RT-PCR misclassification:** Occasional false positives (e.g. protocol #6 in test run)
  - Severity: Low (user accepts ~33% edge case rate)
  - Mitigation: Manual review, or strengthen prompt with explicit examples
- **String "null" vs JSON null:** LLM sometimes returns `"null"` string instead of `null`
  - Status: Addressed in system prompt ("Use JSON null, not string 'null'")

### Query System
- **Citation number artifacts:** Inline citations like `1 , 17 – 21` appear in chunks
  - Status: Partially cleaned by `_clean_sentence()` in `query_kb.py`
  - Could be cleaned upstream in extractors if needed

### Schema
- **protocol_sources constraint:** Exactly one of `review_chunk_id` / `paper_chunk_id` must be set
  - Status: Working correctly (separate INSERT branches in `link_protocol_to_chunk`)

---

## Important Context for New Sessions

### Design Decisions Made

1. **Protocols are canonical, sources accumulate**
   - Same protocol (mNGS + virus + CSF) gets one `protocols` row
   - Multiple papers describing it create multiple `protocol_sources` rows
   - Deduplication by identity match, not text similarity

2. **Typed excerpts, not free text**
   - Each excerpt type (`method`, `performance`, `limitations`, etc.) has its own field
   - Enables structured queries like "show all limitations for mNGS protocols"

3. **Veterinary transferability is LLM-assessed, not rule-based**
   - Score 0-3 based on specimen feasibility, cost, infrastructure
   - May need recalibration after veterinary corpus ingestion

4. **NGS-only scope (as of latest refinement)**
   - Excludes conventional PCR, serology, culture
   - Edge cases like amplicon-NGS are included
   - Non-NGS methods mentioned for context are NOT extracted

5. **Phase 2 (vet corpus) is future work**
   - User may have in-house veterinary protocol sources
   - Clustering and gap analysis planned but not yet implemented

### Questions to Ask User in New Session

- How many protocols should be extracted before moving to Phase 2?
- Is the current ~67% accuracy (2/3 NGS-only) acceptable or should prompt be strengthened?
- Ready to ingest veterinary corpus, or finish medical extraction first?
- Should we implement a web frontend now, or wait until gap analysis is done?

---

## Quick Start for New Session

```bash
# 1. Check environment
cd /Users/david/work/informatics_ai_workflow
conda activate openai
psql mngs_kb -c "SELECT COUNT(*) FROM protocols;"

# 2. Read this file
cat SESSION_CONTEXT.md

# 3. Check recent work
git log --oneline -10  # (if using git)

# 4. Ask user: "Where would you like to continue?"
```

---

**Last updated:** 2026-02-19
**Session token usage:** ~130k / 200k
**Database state:** 3 protocols extracted (test run, paper_id=104)
**Ready for:** Full extraction run OR Phase 2 planning
