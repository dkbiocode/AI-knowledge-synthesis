-- create_schema.sql
-- Knowledge base schema for mNGS review article + cited literature.
--
-- Tables:
--   review_sources      : one row per source document (the review itself, later cited papers)
--   review_chunks       : sections of the review, with embeddings
--   citations           : references cited in the review, with metadata
--   chunk_citations     : join table linking chunks to the citations they contain
--   papers              : full-text records of cited papers added to the KB later
--   paper_chunks        : sections of cited papers, with embeddings
--   protocols           : canonical NGS diagnostic protocol records (v2)
--   protocol_sources    : bridge — protocols <-> chunks, many-to-many (v2)
--
-- Usage:
--   psql <dbname> -f create_schema.sql
--
-- To migrate an existing v1 database:
--   psql <dbname> -f migrate_v2.sql

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- for text search on titles etc.

-- ---------------------------------------------------------------------------
-- review_sources
-- One row per top-level document ingested into the KB.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_sources (
    id              SERIAL PRIMARY KEY,
    doc_key         TEXT NOT NULL UNIQUE,  -- e.g. 'fcimb-14-1458316'
    title           TEXT,
    authors         TEXT,
    journal         TEXT,
    year            INTEGER,
    doi             TEXT,
    pubmed_id       TEXT,
    pmc_id          TEXT,
    open_access     BOOLEAN DEFAULT FALSE,
    source_type     TEXT NOT NULL DEFAULT 'review',  -- 'review' | 'cited_paper'
    domain          TEXT DEFAULT 'medical'
                        CHECK (domain IN ('medical', 'veterinary', 'both')),
    html_path       TEXT,                -- local path to source HTML if available
    pdf_path        TEXT,                -- local path to source PDF if available
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- review_chunks
-- Sections of a review_source document, each with an embedding.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_chunks (
    id              SERIAL PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES review_sources(id) ON DELETE CASCADE,
    section_id      TEXT,                -- e.g. 's4_2'
    heading         TEXT,
    parent_heading  TEXT,
    level           INTEGER,             -- 1 = h2, 2 = h3
    text            TEXT,                -- clean body text
    full_text       TEXT,                -- heading + text (what was embedded)
    char_count      INTEGER,
    token_estimate  INTEGER,
    embedding       vector(1536),        -- text-embedding-3-large at 1536 dims
    embedding_model TEXT,
    tokens_used     INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- papers
-- Full records for cited papers that have been added to the KB.
-- Linked back to citations via citations.paper_id.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS papers (
    id              SERIAL PRIMARY KEY,
    doi             TEXT UNIQUE,
    pubmed_id       TEXT,
    pmc_id          TEXT,
    title           TEXT,
    authors         TEXT,
    journal         TEXT,
    year            INTEGER,
    abstract        TEXT,
    full_text       TEXT,                -- full paper text if available
    open_access     BOOLEAN DEFAULT FALSE,
    domain          TEXT DEFAULT 'medical'
                        CHECK (domain IN ('medical', 'veterinary', 'both')),
    html_path       TEXT,
    pdf_path        TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- citations
-- One row per unique reference in the review's reference list.
-- This is the canonical record for each cited paper.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS citations (
    id              SERIAL PRIMARY KEY,
    ref_id          TEXT NOT NULL,       -- e.g. 'B45' (HTML anchor id)
    source_id       INTEGER NOT NULL REFERENCES review_sources(id) ON DELETE CASCADE,
    cite_text       TEXT,                -- full citation text from <cite> tag
    doi             TEXT,
    pubmed_id       TEXT,
    pmc_id          TEXT,
    title           TEXT,
    authors         TEXT,
    year            INTEGER,
    journal         TEXT,
    open_access     BOOLEAN DEFAULT FALSE,
    -- linked to a papers record once that paper is added to the KB
    paper_id        INTEGER REFERENCES papers(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ref_id, source_id)
);

-- ---------------------------------------------------------------------------
-- chunk_citations
-- Join table: which citations appear in which chunk.
-- Preserves order of citation appearance within the chunk.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chunk_citations (
    chunk_id        INTEGER NOT NULL REFERENCES review_chunks(id) ON DELETE CASCADE,
    citation_id     INTEGER NOT NULL REFERENCES citations(id) ON DELETE CASCADE,
    position        INTEGER,             -- order of first appearance in chunk
    PRIMARY KEY (chunk_id, citation_id)
);

-- ---------------------------------------------------------------------------
-- paper_chunks
-- Sections/chunks of cited papers, each with an embedding.
-- Mirrors the structure of review_chunks.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS paper_chunks (
    id              SERIAL PRIMARY KEY,
    paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    section_id      TEXT,
    heading         TEXT,
    parent_heading  TEXT,
    level           INTEGER,
    text            TEXT,
    full_text       TEXT,
    char_count      INTEGER,
    token_estimate  INTEGER,
    embedding       vector(1536),
    embedding_model TEXT,
    tokens_used     INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- protocols (v2)
-- Canonical identity records for NGS diagnostic protocols.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS protocols (
    id                      SERIAL PRIMARY KEY,

    -- Identity — what kind of protocol is this?
    ngs_modality            TEXT,   -- mNGS | targeted | WGS | amplicon | other
    pathogen_class          TEXT,   -- arbovirus | bacteria | fungus | parasite |
                                    --   pan-pathogen | virus | other
    clinical_context        TEXT,   -- sepsis | CNS | respiratory | zoonosis |
                                    --   surveillance | other
    specimen_type           TEXT,   -- CSF | serum | BALF | tissue | swab | other
    platform                TEXT,   -- Illumina | Nanopore | Ion Torrent | BGI | other
    bioinformatics_pipeline TEXT,   -- BWA | Kraken2 | CZID | custom | etc.

    -- Performance (nullable — only when reported)
    sensitivity             NUMERIC(5,2),   -- percent
    specificity             NUMERIC(5,2),   -- percent
    turnaround_hours        NUMERIC(7,1),

    -- Typed verbatim excerpts from the canonical/primary source
    excerpt_method          TEXT,   -- what the protocol does
    excerpt_performance     TEXT,   -- sensitivity/specificity/TAT as stated
    excerpt_limitations     TEXT,   -- stated limitations
    excerpt_biology         TEXT,   -- biological constraints on applicability
    excerpt_obstacles       TEXT,   -- logistical / regulatory obstacles
    excerpt_transferability TEXT,   -- any generalisability statement

    -- LLM-assessed veterinary transferability
    vet_transferability_score   SMALLINT
        CHECK (vet_transferability_score BETWEEN 0 AND 3),
    vet_obstacle_summary        TEXT,

    -- Phase-2 protocol resolution fields (included now to avoid future migration)
    provenance_type         TEXT
        CHECK (provenance_type IN (
            'paper_internal', 'protocols_io', 'cdc_sop',
            'woah_manual', 'github', 'inferred_from_citation', 'other'
        )),
    external_url            TEXT,
    external_id             TEXT,
    is_stub                 BOOLEAN NOT NULL DEFAULT FALSE,

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- protocol_sources (v2)
-- Bridge table linking protocols to chunks (many-to-many).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS protocol_sources (
    id                  SERIAL PRIMARY KEY,
    protocol_id         INTEGER NOT NULL
                            REFERENCES protocols(id) ON DELETE CASCADE,

    -- Exactly one of these two must be non-null
    review_chunk_id     INTEGER
                            REFERENCES review_chunks(id) ON DELETE CASCADE,
    paper_chunk_id      INTEGER
                            REFERENCES paper_chunks(id) ON DELETE CASCADE,

    -- Denormalised for query convenience
    paper_id            INTEGER
                            REFERENCES papers(id) ON DELETE SET NULL,

    mention_type        TEXT NOT NULL DEFAULT 'uses'
        CHECK (mention_type IN (
            'defines', 'uses', 'validates', 'critiques', 'adapts', 'citation_only'
        )),

    verbatim_excerpt    TEXT,
    excerpt_type        TEXT
        CHECK (excerpt_type IN (
            'method', 'performance', 'limitation',
            'biology', 'obstacle', 'transferability', 'other'
        )),

    extraction_score    NUMERIC(6,4),
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (protocol_id, review_chunk_id),
    UNIQUE (protocol_id, paper_chunk_id),

    CONSTRAINT chk_exactly_one_chunk CHECK (
        (review_chunk_id IS NOT NULL)::int +
        (paper_chunk_id  IS NOT NULL)::int = 1
    )
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Vector similarity indexes (HNSW — fast approximate nearest neighbour)
CREATE INDEX IF NOT EXISTS idx_review_chunks_embedding
    ON review_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_embedding
    ON paper_chunks USING hnsw (embedding vector_cosine_ops);

-- Text search
CREATE INDEX IF NOT EXISTS idx_citations_title_trgm
    ON citations USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_papers_title_trgm
    ON papers USING gin (title gin_trgm_ops);

-- Foreign key / join performance
CREATE INDEX IF NOT EXISTS idx_review_chunks_source
    ON review_chunks (source_id);

CREATE INDEX IF NOT EXISTS idx_chunk_citations_chunk
    ON chunk_citations (chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunk_citations_citation
    ON chunk_citations (citation_id);

CREATE INDEX IF NOT EXISTS idx_citations_doi
    ON citations (doi);

CREATE INDEX IF NOT EXISTS idx_papers_doi
    ON papers (doi);

CREATE INDEX IF NOT EXISTS idx_citations_paper_id
    ON citations (paper_id);

-- v2 indexes
CREATE INDEX IF NOT EXISTS idx_papers_domain
    ON papers (domain);

CREATE INDEX IF NOT EXISTS idx_review_sources_domain
    ON review_sources (domain);

CREATE INDEX IF NOT EXISTS idx_protocols_ngs_modality
    ON protocols (ngs_modality);

CREATE INDEX IF NOT EXISTS idx_protocols_pathogen_class
    ON protocols (pathogen_class);

CREATE INDEX IF NOT EXISTS idx_protocols_stub
    ON protocols (is_stub)
    WHERE is_stub = TRUE;

CREATE INDEX IF NOT EXISTS idx_protocol_sources_protocol
    ON protocol_sources (protocol_id);

CREATE INDEX IF NOT EXISTS idx_protocol_sources_paper_chunk
    ON protocol_sources (paper_chunk_id)
    WHERE paper_chunk_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_protocol_sources_review_chunk
    ON protocol_sources (review_chunk_id)
    WHERE review_chunk_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_protocol_sources_paper
    ON protocol_sources (paper_id)
    WHERE paper_id IS NOT NULL;
