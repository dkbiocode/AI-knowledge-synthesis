-- migrate_v2.sql
-- Incremental migration from v1 to v2 schema.
--
-- Safe to run on a live database — uses IF NOT EXISTS / IF EXISTS guards
-- and ADD COLUMN IF NOT EXISTS throughout.
--
-- What this adds:
--   1. domain column on papers and review_sources
--        'medical' | 'veterinary' | 'both' | NULL (unknown)
--   2. protocols table
--        Canonical identity of an NGS diagnostic protocol.
--        Typed verbatim excerpt columns capture what the source actually says.
--        Phase-2 fields (provenance_type, external_url, is_stub) are included
--        now so the schema doesn't need another migration when resolution is built.
--   3. protocol_sources bridge table
--        Many-to-many between protocols and chunks (review or paper).
--        Exactly one of review_chunk_id / paper_chunk_id must be non-null.
--        Each row carries its own verbatim excerpt and excerpt_type so the
--        same protocol can be described differently across sources.
--
-- Usage:
--   psql mngs_kb -f migrate_v2.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. domain on existing tables
-- ---------------------------------------------------------------------------

ALTER TABLE papers
    ADD COLUMN IF NOT EXISTS domain TEXT
        CHECK (domain IN ('medical', 'veterinary', 'both'))
        DEFAULT 'medical';

COMMENT ON COLUMN papers.domain IS
    'Knowledge domain: medical | veterinary | both';

ALTER TABLE review_sources
    ADD COLUMN IF NOT EXISTS domain TEXT
        CHECK (domain IN ('medical', 'veterinary', 'both'))
        DEFAULT 'medical';

COMMENT ON COLUMN review_sources.domain IS
    'Knowledge domain: medical | veterinary | both';

-- Tag the existing review article as medical
UPDATE review_sources SET domain = 'medical' WHERE domain IS NULL;

-- Tag all papers loaded so far as medical
UPDATE papers SET domain = 'medical' WHERE domain IS NULL;

-- ---------------------------------------------------------------------------
-- 2. protocols
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
    -- Each field holds a direct quote from source text.
    -- Additional sources (with their own quotes) live in protocol_sources.
    excerpt_method          TEXT,   -- what the protocol does
    excerpt_performance     TEXT,   -- sensitivity/specificity/TAT as stated
    excerpt_limitations     TEXT,   -- stated limitations
    excerpt_biology         TEXT,   -- biological constraints on applicability
    excerpt_obstacles       TEXT,   -- logistical / regulatory obstacles
    excerpt_transferability TEXT,   -- any generalisability statement

    -- LLM-assessed veterinary transferability
    -- 0 = blocked, 1 = needs modification, 2 = likely feasible,
    -- 3 = directly applicable, NULL = not yet assessed
    vet_transferability_score   SMALLINT
        CHECK (vet_transferability_score BETWEEN 0 AND 3),
    vet_obstacle_summary        TEXT,   -- one-sentence synthesis for vet context

    -- Phase-2 protocol resolution fields (populated by resolve_protocols.py)
    -- Left NULL until phase 2 is built; included now to avoid a future migration.
    provenance_type         TEXT
        CHECK (provenance_type IN (
            'paper_internal', 'protocols_io', 'cdc_sop',
            'woah_manual', 'github', 'inferred_from_citation', 'other'
        )),
    external_url            TEXT,   -- protocols.io DOI, CDC page, etc.
    external_id             TEXT,   -- protocols.io GUID, CDC protocol number, etc.
    is_stub                 BOOLEAN NOT NULL DEFAULT FALSE,
        -- TRUE = we know this protocol exists but haven't fetched its full detail

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE protocols IS
    'Canonical identity records for NGS diagnostic protocols extracted from literature.';
COMMENT ON COLUMN protocols.is_stub IS
    'TRUE when the protocol was cited in a paper but its full definition has not yet been fetched (phase 2).';

-- ---------------------------------------------------------------------------
-- 3. protocol_sources  (bridge: protocol <-> chunk)
-- ---------------------------------------------------------------------------
-- Each row links one protocol to one chunk (either a review_chunk or a
-- paper_chunk) and carries the verbatim excerpt from that specific source.
-- Constraint: exactly one of review_chunk_id / paper_chunk_id must be set.

CREATE TABLE IF NOT EXISTS protocol_sources (
    id                  SERIAL PRIMARY KEY,
    protocol_id         INTEGER NOT NULL
                            REFERENCES protocols(id) ON DELETE CASCADE,

    -- Exactly one of these two must be non-null
    review_chunk_id     INTEGER
                            REFERENCES review_chunks(id) ON DELETE CASCADE,
    paper_chunk_id      INTEGER
                            REFERENCES paper_chunks(id) ON DELETE CASCADE,

    -- Denormalised for query convenience (avoids joining to both chunk tables)
    paper_id            INTEGER
                            REFERENCES papers(id) ON DELETE SET NULL,

    -- What role does this source play?
    mention_type        TEXT NOT NULL DEFAULT 'uses'
        CHECK (mention_type IN (
            'defines',          -- this source contains the full protocol definition
            'uses',             -- this source applies the protocol
            'validates',        -- this source reports validation data
            'critiques',        -- this source identifies limitations
            'adapts',           -- this source modifies the protocol for a new context
            'citation_only'     -- this source merely cites it without detail
        )),

    -- The verbatim text from THIS source supporting the protocol link
    verbatim_excerpt    TEXT,
    excerpt_type        TEXT
        CHECK (excerpt_type IN (
            'method', 'performance', 'limitation',
            'biology', 'obstacle', 'transferability', 'other'
        )),

    -- BM25 or embedding score from the extraction pass (for ranking/debugging)
    extraction_score    NUMERIC(6,4),

    created_at          TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent duplicate source rows for the same protocol+chunk combination
    UNIQUE (protocol_id, review_chunk_id),
    UNIQUE (protocol_id, paper_chunk_id),

    -- Enforce exactly-one-chunk constraint
    CONSTRAINT chk_exactly_one_chunk CHECK (
        (review_chunk_id IS NOT NULL)::int +
        (paper_chunk_id  IS NOT NULL)::int = 1
    )
);

COMMENT ON TABLE protocol_sources IS
    'Bridge table linking protocols to the chunks where they are mentioned. '
    'Each row carries a verbatim excerpt from that specific source. '
    'Exactly one of review_chunk_id / paper_chunk_id must be set.';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- protocol lookups by modality / domain join
CREATE INDEX IF NOT EXISTS idx_protocols_ngs_modality
    ON protocols (ngs_modality);

CREATE INDEX IF NOT EXISTS idx_protocols_pathogen_class
    ON protocols (pathogen_class);

CREATE INDEX IF NOT EXISTS idx_protocols_stub
    ON protocols (is_stub)
    WHERE is_stub = TRUE;   -- partial index — only unresolved stubs

-- protocol_sources join performance
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

-- domain lookups
CREATE INDEX IF NOT EXISTS idx_papers_domain
    ON papers (domain);

CREATE INDEX IF NOT EXISTS idx_review_sources_domain
    ON review_sources (domain);

-- ---------------------------------------------------------------------------
-- Trigger: keep protocols.updated_at current
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protocols_updated_at ON protocols;
CREATE TRIGGER trg_protocols_updated_at
    BEFORE UPDATE ON protocols
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    v_protocols      INTEGER;
    v_proto_sources  INTEGER;
    v_papers_domain  BOOLEAN;
    v_sources_domain BOOLEAN;
BEGIN
    SELECT COUNT(*) INTO v_protocols     FROM information_schema.tables
        WHERE table_name = 'protocols';
    SELECT COUNT(*) INTO v_proto_sources FROM information_schema.tables
        WHERE table_name = 'protocol_sources';
    SELECT COUNT(*) > 0 INTO v_papers_domain FROM information_schema.columns
        WHERE table_name = 'papers' AND column_name = 'domain';
    SELECT COUNT(*) > 0 INTO v_sources_domain FROM information_schema.columns
        WHERE table_name = 'review_sources' AND column_name = 'domain';

    RAISE NOTICE 'Migration v2 complete:';
    RAISE NOTICE '  protocols table       : %', CASE WHEN v_protocols > 0      THEN 'OK' ELSE 'MISSING' END;
    RAISE NOTICE '  protocol_sources table: %', CASE WHEN v_proto_sources > 0  THEN 'OK' ELSE 'MISSING' END;
    RAISE NOTICE '  papers.domain column  : %', CASE WHEN v_papers_domain      THEN 'OK' ELSE 'MISSING' END;
    RAISE NOTICE '  review_sources.domain : %', CASE WHEN v_sources_domain     THEN 'OK' ELSE 'MISSING' END;
END;
$$;
