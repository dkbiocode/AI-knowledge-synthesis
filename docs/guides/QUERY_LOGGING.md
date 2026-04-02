# Query Logging System

The NGS Knowledge Base includes a comprehensive query logging system that tracks user queries, enables similarity search, and provides query history.

## Features

### 1. **Automatic Query Logging**
- All queries are logged with their embeddings
- Session tracking via unique session IDs
- Optional user_id support for multi-user systems
- Metadata storage for additional context

### 2. **Similar Query Detection**
- Finds past queries similar to the current query using vector similarity
- Configurable similarity threshold (default: 0.75)
- Helps users discover relevant past searches
- Reduces duplicate queries

### 3. **Query History**
- Per-session query history
- Chronological listing of recent queries
- Filterable by user_id or session_id
- Supports retrieval of complex queries with aspects

### 4. **Complex Query Support**
- Logs hierarchical query decompositions
- Parent-child relationships for aspect-based queries
- Category tagging (methodology, target, sample, performance, etc.)
- Metadata includes decomposition reasoning

## Database Schema

The `query_log` table stores all query information:

```sql
CREATE TABLE query_log (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    embedding VECTOR(1536),
    parent_id INTEGER REFERENCES query_log(id) ON DELETE CASCADE,
    is_complex BOOLEAN DEFAULT FALSE,
    category VARCHAR(50),                    -- For sub-queries
    metadata JSONB,                          -- Additional context
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id VARCHAR(255),
    session_id VARCHAR(255)
);
```

**Indexes:**
- `idx_query_log_embedding` - IVFFlat index for vector similarity search
- `idx_query_log_parent` - Parent-child relationships
- `idx_query_log_session` - Session-based queries
- `idx_query_log_user` - User-based queries
- `idx_query_log_created` - Chronological ordering

## Usage

### In Python Scripts

```python
from scripts.query.query_logger import (
    log_query,
    log_decomposed_query,
    find_similar_queries,
    get_recent_queries,
    get_query_with_aspects
)
from config.db_config import get_connection

# Connect to database
conn = get_connection('supabase')  # or 'local'
cursor = conn.cursor()

# Log a simple query
query_id = log_query(
    cursor,
    query_text="What NGS methods detect viruses?",
    embedding=query_embedding,
    is_complex=False,
    session_id="user_session_123"
)
conn.commit()

# Find similar past queries
similar_queries = find_similar_queries(
    cursor,
    query_embedding=current_embedding,
    limit=5,
    similarity_threshold=0.75
)

for query in similar_queries:
    print(f"{query['similarity']:.2f}: {query['query_text']}")

# Get recent queries for a session
recent = get_recent_queries(
    cursor,
    limit=10,
    session_id="user_session_123"
)

cursor.close()
conn.close()
```

### In Web App (Streamlit)

The web app (`scripts/query/web_query.py`) has built-in query logging:

**Sidebar Controls:**
- **"Log queries"** checkbox - Enable/disable query logging
- **"Show similar past queries"** checkbox - Display similar queries before results
- **"Query History"** section - Shows recent queries from current session

**Behavior:**
1. When a user submits a query, the app:
   - Embeds the query
   - Searches for similar past queries (if enabled)
   - Displays similar queries in an expander
   - Logs the current query (if enabled)
   - Performs the search

2. The sidebar shows:
   - Recent queries from the current session
   - Timestamps and query text previews
   - Session ID (hidden, auto-generated)

### Logging Complex Queries with Aspects

For queries that are decomposed into multiple aspects:

```python
from scripts.query.decompose_query import decompose_query
from openai import OpenAI

# Decompose complex query
decomposition = decompose_query(
    "What NGS methods detect arboviruses in CSF and what are their sensitivities?"
)

# Generate embeddings for parent and aspects
client = OpenAI()
texts = [query] + [aspect["question"] for aspect in decomposition["aspects"]]
response = client.embeddings.create(model="text-embedding-3-small", input=texts)

parent_embedding = response.data[0].embedding
aspect_embeddings = [item.embedding for item in response.data[1:]]

# Prepare aspects with embeddings
aspects = [
    {
        **aspect,
        "embedding": aspect_embeddings[i]
    }
    for i, aspect in enumerate(decomposition["aspects"])
]

# Log parent query and all aspects
parent_id = log_decomposed_query(
    cursor,
    parent_query=query,
    parent_embedding=parent_embedding,
    aspects=aspects,
    reasoning=decomposition["reasoning"],
    session_id="user_session_123"
)
conn.commit()

# Retrieve it back with all aspects
full_query = get_query_with_aspects(cursor, parent_id)
print(f"Parent: {full_query['query_text']}")
print(f"Aspects ({len(full_query['aspects'])}):")
for aspect in full_query['aspects']:
    print(f"  - [{aspect['category']}] {aspect['question']}")
```

## Configuration

### Similarity Thresholds

Adjust the similarity threshold to control how strict the matching is:

- `0.95+` - Nearly identical queries
- `0.85-0.95` - Very similar queries
- `0.75-0.85` - Similar queries (default)
- `0.65-0.75` - Somewhat similar queries
- `<0.65` - Loosely related queries

### Session Management

Sessions are automatically generated using UUID4:

```python
import uuid
session_id = str(uuid.uuid4())
```

For persistent sessions across page reloads, use Streamlit's session state:

```python
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
```

### User Identification

Add user authentication by passing `user_id`:

```python
log_query(
    cursor,
    query_text="...",
    embedding=[...],
    user_id="user@example.com",  # or user ID
    session_id=session_id
)
```

## Query History Analysis

### Most Common Queries

```sql
SELECT query_text, COUNT(*) as frequency
FROM query_log
WHERE parent_id IS NULL
GROUP BY query_text
ORDER BY frequency DESC
LIMIT 10;
```

### Most Active Sessions

```sql
SELECT session_id, COUNT(*) as query_count
FROM query_log
WHERE parent_id IS NULL
GROUP BY session_id
ORDER BY query_count DESC
LIMIT 10;
```

### Query Categories Distribution

```sql
SELECT category, COUNT(*) as count
FROM query_log
WHERE category IS NOT NULL
GROUP BY category
ORDER BY count DESC;
```

### Temporal Patterns

```sql
SELECT
    DATE(created_at) as date,
    COUNT(*) as queries
FROM query_log
WHERE parent_id IS NULL
GROUP BY DATE(created_at)
ORDER BY date DESC
LIMIT 30;
```

## Performance Considerations

### Vector Index

The `idx_query_log_embedding` index uses IVFFlat for fast similarity search:

```sql
CREATE INDEX idx_query_log_embedding
ON query_log
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 50);
```

- **Lists parameter**: Controls index granularity
  - Higher = more accurate, slower indexing
  - Lower = faster indexing, less accurate
  - Rule of thumb: `rows / 1000` for < 1M rows

### Cleanup Strategy

To prevent unbounded growth, periodically clean old logs:

```sql
-- Delete queries older than 90 days
DELETE FROM query_log
WHERE created_at < NOW() - INTERVAL '90 days';

-- Or keep only N most recent queries per session
DELETE FROM query_log
WHERE id NOT IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY session_id
            ORDER BY created_at DESC
        ) as rn
        FROM query_log
    ) sub
    WHERE rn <= 100
);
```

## Privacy & Security

### Data Retention

- Default: Queries stored indefinitely
- Recommended: Implement retention policy (30-90 days)
- Compliance: Check GDPR, CCPA requirements

### Anonymization

For anonymous usage tracking, use hashed user IDs:

```python
import hashlib

user_email = "user@example.com"
user_id_hash = hashlib.sha256(user_email.encode()).hexdigest()

log_query(cursor, ..., user_id=user_id_hash, ...)
```

### PII Handling

- Query text may contain sensitive information
- Consider filtering or redacting PII before logging
- Implement access controls for query logs
- Encrypt sensitive metadata fields

## Testing

Run the query logger test script:

```bash
# Test basic logging
python scripts/query/query_logger.py

# Manual testing
python -c "
from scripts.query.query_logger import *
from config.db_config import get_connection

conn = get_connection('supabase')
cursor = conn.cursor()

# Your test code here
"
```

## Troubleshooting

### "relation query_log does not exist"

The table needs to be created. Run the schema file:

```bash
psql -d mngs_kb -f sql/query_log_schema.sql
```

### Slow similarity searches

1. Check if vector index exists:
   ```sql
   \d query_log
   ```

2. Rebuild index if needed:
   ```sql
   DROP INDEX IF EXISTS idx_query_log_embedding;
   CREATE INDEX idx_query_log_embedding
   ON query_log USING ivfflat (embedding vector_cosine_ops)
   WITH (lists = 100);
   ```

3. Analyze table:
   ```sql
   ANALYZE query_log;
   ```

### Memory issues with large history

- Limit results with `LIMIT` clauses
- Implement pagination for history views
- Archive old queries to separate table
- Use materialized views for common queries

## Future Enhancements

### Potential Improvements

1. **Query Suggestions** - Autocomplete based on popular queries
2. **Query Analytics Dashboard** - Visualize query patterns
3. **A/B Testing** - Compare different decomposition strategies
4. **Query Optimization** - Suggest better query formulations
5. **Federated Search** - Search across multiple sessions/users
6. **Export Functionality** - Download query history as CSV/JSON
7. **Query Sharing** - Share interesting queries with other users
8. **Smart Caching** - Cache results for frequently repeated queries

### Integration Points

- **Monitoring**: Track query volume, latency, error rates
- **Analytics**: User behavior analysis, feature usage
- **Recommendations**: "Users who searched X also searched Y"
- **Quality Metrics**: Track answer relevance, user satisfaction

## References

- **Schema Definition**: `query_log_schema.sql`
- **Logger Module**: `scripts/query/query_logger.py`
- **Web Integration**: `scripts/query/web_query.py`
- **Config System**: `config/db_config.py`

---

**Last Updated:** 2026-02-25
**Version:** 1.0
