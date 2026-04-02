# Query Decomposition & Aspect-Based Search Guide

## Overview

The knowledge base now supports **aspect-based hierarchical search** with automatic query decomposition for complex questions. This provides users with transparent coverage reporting: "Which parts of my question were answered?"

## System Architecture

### Three-Level Search Hierarchy

1. **Query Decomposition** (LLM-based)
   - Analyzes query complexity
   - Breaks complex queries into discrete aspects
   - Categories: methodology, target, sample, performance, workflow, comparison, clinical_context, validation

2. **Section-Level Search** (Full query embedding)
   - Searches for broadly relevant sections
   - Captures conceptual context
   - Uses complete query embedding

3. **Sentence-Level Search** (Aspect-specific embeddings)
   - Searches within top sections using aspect embeddings
   - Precise fact matching
   - Reports which aspects were answered

### Example Query Flow

**Input**: "What NGS methods detect arboviruses in CSF and what are their sensitivity and turnaround times?"

**Step 1: Decomposition** →
- Aspect 1: [methodology] "What NGS methods?"
- Aspect 2: [target] "What arboviruses?"
- Aspect 3: [sample] "CSF specimen type?"
- Aspect 4: [performance] "What sensitivity?"
- Aspect 5: [workflow] "What turnaround time?"

**Step 2: Generate Embeddings** →
- Full query embedding (for sections)
- 5 aspect embeddings (for sentences)

**Step 3: Search** →
- Find top 3 sections with full query
- Within each section, search sentences with each aspect embedding

**Step 4: Report Coverage** →
- "✅ MOSTLY ANSWERED (4/5 aspects, 80%)"
- Show which aspects found vs. not found

## Database Schema

### Query Logging Table

```sql
CREATE TABLE query_log (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    embedding vector(1536),
    parent_id INTEGER REFERENCES query_log(id),  -- NULL for parent queries
    is_complex BOOLEAN DEFAULT FALSE,
    category VARCHAR(50),  -- For sub-queries: methodology, target, etc.
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id VARCHAR(255),
    session_id VARCHAR(255)
);
```

### Hierarchical Structure

```
query_log (id=1, parent_id=NULL)  ← Parent query
    ├── query_log (id=2, parent_id=1, category='methodology')
    ├── query_log (id=3, parent_id=1, category='target')
    ├── query_log (id=4, parent_id=1, category='performance')
    └── query_log (id=5, parent_id=1, category='workflow')
```

## Scripts & Tools

### 1. Query Decomposition (`decompose_query.py`)

```bash
python scripts/query/decompose_query.py "What NGS methods detect arboviruses in CSF?"
```

**Output**:
```json
{
  "is_complex": true,
  "reasoning": "Query asks about method, pathogen, and specimen",
  "aspects": [
    {
      "name": "method",
      "question": "What NGS methods?",
      "category": "methodology",
      "keywords": ["NGS", "methods", "sequencing"]
    },
    ...
  ]
}
```

**Features**:
- Uses gpt-4o-mini for fast, cheap decomposition
- Identifies 8 aspect categories
- Avoids over-decomposition (2-6 aspects max)
- Includes keywords for each aspect

### 2. Aspect-Based Search (`aspect_search.py`)

```bash
python scripts/query/aspect_search.py "What NGS methods detect arboviruses in CSF and what are their sensitivity and turnaround times?" --limit 3
```

**Output**:
```
RESULT 1: Wilson et al. 2014
────────────────────────────────
Section Relevance: 0.86
Coverage: 4/5 aspects (80%)

Result Quality: ✅ MOSTLY ANSWERED

┌─ Aspect Coverage ─────────────────┐
│ ✓ [methodology] ANSWERED (0.89)  │
│   Q: What NGS methods?            │
│   A: Metagenomic sequencing...    │
│                                   │
│ ✓ [target] ANSWERED (0.87)        │
│   Q: What arboviruses?            │
│   A: West Nile, dengue, Zika...   │
│                                   │
│ ✓ [performance] ANSWERED (0.88)   │
│   Q: What sensitivity?            │
│   A: Sensitivity was 80%...       │
│                                   │
│ ✗ [workflow] NOT FOUND            │
│   Q: What turnaround time?        │
└───────────────────────────────────┘
```

**Features**:
- Automatic decomposition
- Batch embedding generation (efficient)
- Coverage calculation
- Quality classification
- Domain filtering (--domain medical/veterinary)

### 3. Query Logger (`query_logger.py`)

Python module for web app integration:

```python
from scripts.query.query_logger import log_decomposed_query

# Log a complex query with aspects
parent_id = log_decomposed_query(
    cursor,
    parent_query="What NGS methods detect arboviruses...",
    parent_embedding=embedding,
    aspects=[
        {
            "question": "What NGS methods?",
            "embedding": aspect_embedding,
            "category": "methodology",
            "keywords": ["NGS", "methods"]
        },
        ...
    ],
    reasoning="Query asks about method, pathogen, performance",
    session_id="user_session_123"
)
```

**Functions**:
- `log_query()` - Log single query
- `log_decomposed_query()` - Log parent + aspects
- `find_similar_queries()` - Find past similar queries
- `get_query_with_aspects()` - Retrieve query with all aspects
- `get_recent_queries()` - Get recent query history

## Aspect Categories

| Category | Description | Examples |
|----------|-------------|----------|
| **methodology** | NGS method/platform | mNGS, targeted NGS, Illumina, MinION |
| **target** | Pathogen type | Bacteria, virus, arbovirus, specific species |
| **sample** | Specimen type | CSF, blood, tissue, respiratory |
| **performance** | Diagnostic metrics | Sensitivity, specificity, PPV, NPV |
| **workflow** | Operational metrics | Turnaround time, cost, sample volume |
| **comparison** | Method comparisons | vs culture, vs PCR, vs serology |
| **clinical_context** | Clinical setting | Pre-antibiotic, pediatric, immunocompromised |
| **validation** | Study design | Retrospective, prospective, sample size |

## Result Quality Labels

Based on combined section score, aspect scores, and coverage:

| Label | Criteria |
|-------|----------|
| 🎯 **COMPLETE ANSWER** | Coverage ≥80%, best aspect ≥0.75 |
| ✅ **MOSTLY ANSWERED** | Coverage ≥60%, section ≥0.75 |
| 📌 **PARTIAL ANSWER** | Coverage ≥40% |
| 📖 **TOPIC DISCUSSED** | Section ≥0.75, low aspect scores |
| ❓ **WEAK MATCH** | All scores low |

## Usage Patterns

### Pattern 1: Simple Web App Integration

```python
from scripts.query import query_logger, aspect_search
import psycopg2

conn = psycopg2.connect("dbname=mngs_kb")
cursor = conn.cursor()

# User submits query
user_query = "What NGS methods detect bacteria in blood?"

# Run aspect-based search (handles decomposition automatically)
results = aspect_search.search(user_query)

# Log query and aspects to database
query_logger.log_decomposed_query(
    cursor,
    parent_query=user_query,
    parent_embedding=results["query_embedding"],
    aspects=results["aspects"],
    reasoning=results["reasoning"],
    session_id=user_session_id
)

conn.commit()

# Return results to user
return {
    "sections": results["sections"],
    "coverage": results["coverage"],
    "quality": results["quality_label"]
}
```

### Pattern 2: Finding Similar Past Queries

```python
# Before running expensive search, check if similar query exists
similar = query_logger.find_similar_queries(
    cursor,
    query_embedding,
    limit=5,
    similarity_threshold=0.85
)

if similar and similar[0]["similarity"] > 0.90:
    # Very similar query found - maybe show cached results
    print(f"Similar query from {similar[0]['created_at']}: {similar[0]['query_text']}")
    # Optionally retrieve and show previous results
```

### Pattern 3: User Query History

```python
# Show user their recent queries
recent = query_logger.get_recent_queries(
    cursor,
    limit=10,
    user_id=current_user_id
)

for query in recent:
    print(f"{query['created_at']}: {query['query_text']}")
    if query['is_complex']:
        # Retrieve aspects
        full_query = query_logger.get_query_with_aspects(cursor, query['query_id'])
        print(f"  {len(full_query['aspects'])} aspects")
```

## Performance Considerations

### Costs
- **Decomposition**: ~$0.0001 per query (gpt-4o-mini)
- **Embeddings**: ~$0.000013 per query (text-embedding-3-small, ~5 aspects × 10 tokens)
- **Total per complex query**: ~$0.0001

### Latency
- Decomposition: ~500ms
- Embedding generation (batch): ~200ms
- Database search: ~100ms
- **Total**: ~800ms for complex query

### Optimization
- Batch embedding generation (1 API call instead of 6)
- Early stopping (skip sentence search if section score < 0.60)
- Caching (check for similar past queries first)

## Integration with Existing System

### Relationship to Section/Sentence Search

```
Existing:
  query → [section search] → [sentence search in top sections]

New (Aspect-Based):
  query → [decompose] → aspects
       ↓
  [section search with full query]
       ↓
  [sentence search with aspect-specific embeddings]
       ↓
  [coverage calculation] → "4/5 aspects answered"
```

### Backward Compatibility

Simple queries still work without decomposition:
- Detected as `is_complex: false`
- Single aspect created
- No coverage calculation needed
- Results identical to original system

## Future Enhancements

1. **Cross-section aggregation** - Build complete answers from multiple sections
2. **Aspect prioritization** - Weight some aspects higher (e.g., performance metrics)
3. **Interactive refinement** - "We couldn't find turnaround time. Refine search?"
4. **Answer synthesis** - LLM generates combined answer from aspect results
5. **Smart caching** - Reuse aspect embeddings across similar queries

## Files Created (2026-02-22)

| File | Purpose |
|------|---------|
| `scripts/query/decompose_query.py` | LLM-based query decomposition |
| `scripts/query/aspect_search.py` | Aspect-based hierarchical search |
| `scripts/query/query_logger.py` | Query logging utilities |
| `query_log_schema.sql` | Database schema for query logging |
| `QUERY_DECOMPOSITION_GUIDE.md` | This documentation |

## Example Session

```bash
# 1. Test decomposition
python scripts/query/decompose_query.py "What NGS methods detect arboviruses in CSF and what are their sensitivity?"

# 2. Run aspect-based search
python scripts/query/aspect_search.py "What NGS methods detect arboviruses in CSF and what are their sensitivity?" --limit 3

# 3. Check logged queries
psql mngs_kb -c "SELECT parent.query_text, child.category, child.query_text
FROM query_log parent
LEFT JOIN query_log child ON child.parent_id = parent.id
WHERE parent.id = 1;"
```

## Key Insight: Why This Works

**The Problem**: Single embedding for complex queries doesn't capture all aspects
- "What NGS methods detect arboviruses in CSF and what is their sensitivity?"
- Sentence: "Sensitivity was 87%" matches poorly (no mention of method/pathogen/specimen)

**The Solution**: Separate embeddings for each aspect
- Aspect embedding: "What is the sensitivity?"
- Sentence: "Sensitivity was 87%" matches strongly (0.88)

**Result**: User sees "4/5 aspects answered" instead of vague "relevant sections found"
