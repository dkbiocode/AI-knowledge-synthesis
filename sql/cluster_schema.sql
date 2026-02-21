-- cluster_schema.sql
--
-- Add tables for storing clustering results and gap analysis
--
-- Usage:
--   psql mngs_kb < cluster_schema.sql

-- Store cluster assignment for each chunk
CREATE TABLE IF NOT EXISTS chunk_clusters (
    id SERIAL PRIMARY KEY,
    chunk_id TEXT NOT NULL,  -- 'review_123' or 'paper_456'
    chunk_type TEXT NOT NULL CHECK (chunk_type IN ('review', 'paper')),
    cluster_id INTEGER NOT NULL,  -- -1 for noise/outliers
    umap_x REAL,
    umap_y REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunk_clusters_chunk
    ON chunk_clusters(chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunk_clusters_cluster
    ON chunk_clusters(cluster_id);

-- Store gap score summary per cluster
CREATE TABLE IF NOT EXISTS cluster_gap_scores (
    cluster_id INTEGER PRIMARY KEY,
    medical_count INTEGER NOT NULL,
    vet_count INTEGER NOT NULL,
    both_count INTEGER DEFAULT 0,  -- domain='both'
    total_count INTEGER NOT NULL,
    gap_score REAL NOT NULL,
    gap_label TEXT NOT NULL,  -- 'medical-dominated', 'balanced', 'vet-specific', etc.
    top_terms TEXT[],  -- Representative keywords for this cluster
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Store cluster representative chunks (for manual review)
CREATE TABLE IF NOT EXISTS cluster_representatives (
    id SERIAL PRIMARY KEY,
    cluster_id INTEGER NOT NULL,
    chunk_id TEXT NOT NULL,
    chunk_type TEXT NOT NULL,
    heading TEXT,
    domain TEXT,
    distance_to_centroid REAL,  -- Lower = more representative
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cluster_reps_cluster
    ON cluster_representatives(cluster_id);

COMMENT ON TABLE chunk_clusters IS 'HDBSCAN cluster assignments for all embedded chunks';
COMMENT ON TABLE cluster_gap_scores IS 'Medical-veterinary gap scores per cluster';
COMMENT ON TABLE cluster_representatives IS 'Most representative chunks per cluster for interpretation';
