# SQL Schema Files

This directory contains all database schema definitions for the NGS Knowledge Base.

## Schema Files

### Core Schema

| File | Purpose | Status |
|------|---------|--------|
| `create_schema.sql` | **Main schema** - Complete v3 database schema with all tables (papers, chunks, protocols, clustering) | ✅ Production |
| `migrate_v2.sql` | Migration script from v1 to v2 (adds protocol tables) | 🏛️ Legacy |

### Feature Extensions

| File | Purpose | Tables Created | Required By |
|------|---------|---------------|-------------|
| `cluster_schema.sql` | Clustering infrastructure | `chunk_clusters`, `cluster_gap_scores`, `cluster_representatives` | Clustering analysis |
| `sentence_schema.sql` | Sentence-level search | `paper_sentences`, `sentence_embeddings` | Aspect-based search |
| `query_log_schema.sql` | Query logging and history | `query_log` | Web app query logging |

## Usage

### Fresh Database Setup

For a new database, run the main schema:

```bash
# Create database
createdb mngs_kb

# Apply main schema (includes all core tables)
psql -d mngs_kb -f sql/create_schema.sql

# Apply feature extensions as needed
psql -d mngs_kb -f sql/cluster_schema.sql
psql -d mngs_kb -f sql/sentence_schema.sql
psql -d mngs_kb -f sql/query_log_schema.sql
```

### Checking Applied Schemas

```bash
# List all tables
psql -d mngs_kb -c "\dt"

# Check specific table
psql -d mngs_kb -c "\d query_log"
```

### Supabase Setup

For Supabase local development:

```bash
# Start Supabase
supabase start

# Apply schemas to Supabase (port 54322)
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -d postgres -f sql/create_schema.sql
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -d postgres -f sql/cluster_schema.sql
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -d postgres -f sql/sentence_schema.sql
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -d postgres -f sql/query_log_schema.sql
```

Or restore from a dump:

```bash
pg_dump mngs_kb -f mngs_kb_dump.sql
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -d postgres -f mngs_kb_dump.sql
```

## Schema Details

### create_schema.sql

**Core tables:**
- `review_sources` - Review articles
- `review_chunks` - Review article sections
- `papers` - Cited papers
- `paper_chunks` - Paper sections
- `citations` - Citation mappings
- `chunk_citations` - Inline citation references

**Protocol tables:**
- `protocols` - Extracted NGS protocols
- `protocol_sources` - Protocol-to-chunk mappings

**Vector extensions:**
- Enables pgvector extension
- Creates vector indexes for embeddings

### cluster_schema.sql

**Purpose:** HDBSCAN clustering for topic analysis and medical-veterinary gap identification

**Tables:**
- `chunk_clusters` - Cluster assignments with UMAP coordinates
- `cluster_gap_scores` - Medical/vet distribution per cluster
- `cluster_representatives` - Top representative chunks per cluster

**Features:**
- IVFFlat vector indexes for fast similarity search
- Gap score calculation (medical:veterinary ratio)

### sentence_schema.sql

**Purpose:** Sentence-level granular search for precise excerpt retrieval

**Tables:**
- `paper_sentences` - Individual sentences from papers
- `sentence_embeddings` - Sentence-level embeddings

**Features:**
- Foreign keys to `paper_chunks`
- Position tracking within chunks
- Vector indexes for sentence similarity

**Use case:** Aspect-based search where each query aspect searches sentences independently

### query_log_schema.sql

**Purpose:** Track user queries, enable query history, and find similar past queries

**Tables:**
- `query_log` - All queries with embeddings and metadata

**Features:**
- Parent-child relationships for complex decomposed queries
- Session and user tracking
- IVFFlat index for similarity search
- JSONB metadata storage

**Use case:** Web app query logging, analytics, duplicate detection

## Version History

- **v1** - Initial schema (review_sources, papers, chunks)
- **v2** - Added protocol tables (protocols, protocol_sources)
- **v3** - Added clustering support (chunk_clusters, gap_scores) + domain tagging

**Current version:** v3 (as of 2026-02-20)

## Dependencies

All schema files require:
- PostgreSQL 14+
- pgvector extension (vector similarity search)

Install pgvector:

```bash
# macOS with Homebrew
brew install pgvector

# Or build from source
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
make install
```

Then enable in database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Maintenance

### Backing Up Schemas

```bash
# Dump schema only (no data)
pg_dump -s mngs_kb -f mngs_kb_schema.sql

# Dump specific table schema
pg_dump -s -t query_log mngs_kb -f query_log_schema_backup.sql
```

### Recreating Indexes

If indexes need rebuilding:

```bash
psql -d mngs_kb -c "REINDEX TABLE paper_chunks;"
psql -d mngs_kb -c "REINDEX INDEX paper_chunks_embedding_idx;"
```

### Analyzing Performance

```bash
# Show index usage
psql -d mngs_kb -c "
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
"

# Show table sizes
psql -d mngs_kb -c "
SELECT tablename,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"
```

## Contributing

When adding new schema files:

1. **Create the file** in `sql/` directory
2. **Name convention**: `feature_schema.sql` or `feature_name_schema.sql`
3. **Add idempotency**: Use `CREATE TABLE IF NOT EXISTS`
4. **Document here**: Update this README with table descriptions
5. **Update SESSION_CONTEXT.md**: Add to file inventory

---

**Last Updated:** 2026-02-25
