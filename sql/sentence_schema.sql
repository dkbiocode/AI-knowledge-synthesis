-- Sentence-level granularity for improved search precision
-- Migration: Add sentence tables with embeddings
-- Date: 2026-02-22

-- Paper sentences (from paper_chunks)
CREATE TABLE IF NOT EXISTS paper_sentences (
    id SERIAL PRIMARY KEY,
    paper_chunk_id INTEGER NOT NULL REFERENCES paper_chunks(id) ON DELETE CASCADE,
    sentence_index INTEGER NOT NULL,  -- position within parent chunk (0-based)
    text TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT paper_sentences_unique UNIQUE (paper_chunk_id, sentence_index)
);

-- Review sentences (from review_chunks)
CREATE TABLE IF NOT EXISTS review_sentences (
    id SERIAL PRIMARY KEY,
    review_chunk_id INTEGER NOT NULL REFERENCES review_chunks(id) ON DELETE CASCADE,
    sentence_index INTEGER NOT NULL,  -- position within parent chunk (0-based)
    text TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT review_sentences_unique UNIQUE (review_chunk_id, sentence_index)
);

-- Indexes for efficient parent chunk lookups
CREATE INDEX IF NOT EXISTS idx_paper_sentences_chunk ON paper_sentences(paper_chunk_id);
CREATE INDEX IF NOT EXISTS idx_review_sentences_chunk ON review_sentences(review_chunk_id);

-- Vector similarity indexes (using ivfflat for cosine similarity)
-- Note: Adjust lists parameter based on final row count
-- Rule of thumb: lists = sqrt(total_rows), typically 10-100 for our dataset
CREATE INDEX IF NOT EXISTS idx_paper_sentences_embedding
    ON paper_sentences USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_review_sentences_embedding
    ON review_sentences USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- Comments for documentation
COMMENT ON TABLE paper_sentences IS
    'Sentence-level chunks from paper sections for fine-grained semantic search';
COMMENT ON TABLE review_sentences IS
    'Sentence-level chunks from review sections for fine-grained semantic search';

COMMENT ON COLUMN paper_sentences.sentence_index IS
    'Zero-based position of sentence within parent chunk (preserves reading order)';
COMMENT ON COLUMN review_sentences.sentence_index IS
    'Zero-based position of sentence within parent chunk (preserves reading order)';
