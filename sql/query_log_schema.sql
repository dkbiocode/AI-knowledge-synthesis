-- Query logging system for web app
-- Stores user queries with embeddings and tracks decomposed sub-queries
-- Date: 2026-02-22

CREATE TABLE IF NOT EXISTS query_log (
    id SERIAL PRIMARY KEY,

    -- Query content
    query_text TEXT NOT NULL,
    embedding vector(1536),

    -- Hierarchical relationship (self-referential)
    parent_id INTEGER REFERENCES query_log(id) ON DELETE CASCADE,

    -- Query classification
    is_complex BOOLEAN DEFAULT FALSE,
    category VARCHAR(50),  -- For sub-queries: methodology, target, sample, performance, workflow, etc.

    -- Metadata
    metadata JSONB,  -- Store keywords, reasoning, decomposition info, search results, etc.

    -- Tracking
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id VARCHAR(255),  -- Optional: for multi-user web apps
    session_id VARCHAR(255),  -- Optional: track user sessions

    -- Constraints
    CONSTRAINT parent_not_self CHECK (id != parent_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_query_log_parent ON query_log(parent_id);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_log_user ON query_log(user_id);
CREATE INDEX IF NOT EXISTS idx_query_log_session ON query_log(session_id);

-- Vector similarity index for finding similar past queries
CREATE INDEX IF NOT EXISTS idx_query_log_embedding
    ON query_log USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- Comments
COMMENT ON TABLE query_log IS
    'Stores user queries with embeddings and hierarchical decomposition for web app';

COMMENT ON COLUMN query_log.parent_id IS
    'NULL for parent queries, references parent query_id for decomposed sub-queries/aspects';

COMMENT ON COLUMN query_log.category IS
    'For sub-queries: methodology, target, sample, performance, workflow, comparison, clinical_context, validation';

COMMENT ON COLUMN query_log.metadata IS
    'JSONB storing keywords, reasoning, aspect details, search results, coverage metrics, etc.';

-- Example usage:
/*
-- Insert parent query
INSERT INTO query_log (query_text, embedding, is_complex, metadata)
VALUES (
    'What NGS methods detect arboviruses in CSF and what are their sensitivity and turnaround times?',
    <embedding_vector>,
    TRUE,
    '{"reasoning": "Query asks about multiple aspects...", "num_aspects": 5}'::jsonb
)
RETURNING id;  -- Returns parent_id

-- Insert sub-queries (aspects)
INSERT INTO query_log (query_text, embedding, parent_id, category, metadata)
VALUES
    ('What NGS methods are used for arbovirus detection?', <emb>, <parent_id>, 'methodology', '{"keywords": ["NGS", "methods", "arbovirus"]}'::jsonb),
    ('What is the diagnostic sensitivity?', <emb>, <parent_id>, 'performance', '{"keywords": ["sensitivity", "diagnostic"]}'::jsonb),
    ('What is the turnaround time?', <emb>, <parent_id>, 'workflow', '{"keywords": ["turnaround", "time", "TAT"]}'::jsonb);

-- Query to get parent with all sub-queries
SELECT
    parent.id,
    parent.query_text AS parent_query,
    parent.is_complex,
    json_agg(
        json_build_object(
            'id', child.id,
            'question', child.query_text,
            'category', child.category,
            'metadata', child.metadata
        ) ORDER BY child.id
    ) AS aspects
FROM query_log parent
LEFT JOIN query_log child ON child.parent_id = parent.id
WHERE parent.id = <query_id>
GROUP BY parent.id, parent.query_text, parent.is_complex;

-- Find similar past queries
SELECT
    id,
    query_text,
    created_at,
    1 - (embedding <=> <query_embedding>::vector) AS similarity
FROM query_log
WHERE parent_id IS NULL  -- Only search parent queries
  AND embedding IS NOT NULL
ORDER BY embedding <=> <query_embedding>::vector
LIMIT 10;
*/
