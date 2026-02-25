# Database Schema Diagrams

Visual representations of the `mngs_kb` database schema using Mermaid.

---

## Full Schema Overview

```mermaid
erDiagram
    review_sources ||--o{ review_chunks : "contains"
    review_sources ||--o{ citations : "cited_in"
    papers ||--o{ paper_chunks : "contains"
    papers ||--o{ citations : "linked_via"
    review_chunks ||--o{ chunk_citations : "cites"
    citations ||--o{ chunk_citations : "cited_by"
    review_chunks ||--o{ protocol_sources : "describes"
    paper_chunks ||--o{ protocol_sources : "describes"
    protocols ||--o{ protocol_sources : "mentioned_in"
    papers ||--o{ protocol_sources : "paper_context"

    review_sources {
        int id PK
        text doc_key UK
        text title
        text authors
        text journal
        int year
        text doi
        text pubmed_id
        text pmc_id
        boolean open_access
        text source_type
        text domain
        text html_path
        text pdf_path
        timestamptz created_at
    }

    review_chunks {
        int id PK
        int source_id FK
        text section_id
        text heading
        text parent_heading
        int level
        text text
        text full_text
        int char_count
        int token_estimate
        vector_1536 embedding
        text embedding_model
        int tokens_used
        timestamptz created_at
    }

    papers {
        int id PK
        text doi UK
        text pubmed_id
        text pmc_id
        text title
        text authors
        text journal
        int year
        text abstract
        text full_text
        boolean open_access
        text domain
        text html_path
        text pdf_path
        timestamptz created_at
    }

    paper_chunks {
        int id PK
        int paper_id FK
        text section_id
        text heading
        text parent_heading
        int level
        text text
        text full_text
        int char_count
        int token_estimate
        vector_1536 embedding
        text embedding_model
        int tokens_used
        timestamptz created_at
    }

    citations {
        int id PK
        text ref_id
        int source_id FK
        text cite_text
        text doi
        text pubmed_id
        text pmc_id
        text title
        text authors
        int year
        text journal
        boolean open_access
        int paper_id FK
        timestamptz created_at
    }

    chunk_citations {
        int chunk_id FK
        int citation_id FK
        int position
    }

    protocols {
        int id PK
        text ngs_modality
        text pathogen_class
        text clinical_context
        text specimen_type
        text platform
        text bioinformatics_pipeline
        numeric sensitivity
        numeric specificity
        numeric turnaround_hours
        text excerpt_method
        text excerpt_performance
        text excerpt_limitations
        text excerpt_biology
        text excerpt_obstacles
        text excerpt_transferability
        smallint vet_transferability_score
        text vet_obstacle_summary
        text provenance_type
        text external_url
        text external_id
        boolean is_stub
        timestamptz created_at
        timestamptz updated_at
    }

    protocol_sources {
        int id PK
        int protocol_id FK
        int review_chunk_id FK
        int paper_chunk_id FK
        int paper_id FK
        text mention_type
        text verbatim_excerpt
        text excerpt_type
        numeric extraction_score
        timestamptz created_at
    }
```

---

## Core Literature Tables (v1)

Focus on the original review article + cited papers structure:

```mermaid
erDiagram
    review_sources ||--o{ review_chunks : "1:N"
    review_sources ||--o{ citations : "1:N"
    papers ||--o{ paper_chunks : "1:N"
    papers ||--o{ citations : "0:N via paper_id"
    review_chunks ||--o{ chunk_citations : "M:N"
    citations ||--o{ chunk_citations : "M:N"

    review_sources {
        int id PK "Main review article"
        text doc_key UK "fcimb-14-1458316"
        text domain "medical|veterinary|both"
    }

    review_chunks {
        int id PK
        int source_id FK
        text heading "Section heading"
        vector_1536 embedding "OpenAI embeddings"
    }

    citations {
        int id PK
        text ref_id "B1, B2, ... or R1, R2, ..."
        int source_id FK "From which review"
        int paper_id FK "Link to full paper if loaded"
    }

    papers {
        int id PK
        text pmc_id "PMC12520762"
        text domain "medical|veterinary|both"
    }

    paper_chunks {
        int id PK
        int paper_id FK
        text heading "Section heading"
        vector_1536 embedding "OpenAI embeddings"
    }

    chunk_citations {
        int chunk_id FK "Which chunk"
        int citation_id FK "Cites which ref"
        int position "Order in chunk"
    }
```

---

## Protocol Extraction Tables (v2)

Focus on the new protocol knowledge synthesis layer:

```mermaid
erDiagram
    protocols ||--o{ protocol_sources : "1:N"
    protocol_sources }o--|| review_chunks : "N:1 (XOR)"
    protocol_sources }o--|| paper_chunks : "N:1 (XOR)"
    protocol_sources }o--o| papers : "N:1 (denormalized)"

    protocols {
        int id PK "Canonical protocol"
        text ngs_modality "mNGS|targeted_NGS|WGS|amplicon_NGS"
        text pathogen_class "virus|bacteria|fungus|parasite"
        text specimen_type "CSF|serum|blood|tissue"
        text platform "Illumina|Nanopore|BGI"
        numeric sensitivity "0-100%"
        numeric specificity "0-100%"
        text excerpt_method "Verbatim quote: what it does"
        text excerpt_limitations "Verbatim quote: stated limits"
        text excerpt_biology "Verbatim quote: biology constraints"
        text excerpt_obstacles "Verbatim quote: cost/regulatory"
        smallint vet_transferability_score "0-3 LLM assessment"
        text vet_obstacle_summary "One sentence"
        boolean is_stub "Phase 2: unresolved external protocol"
    }

    protocol_sources {
        int id PK "Bridge: protocol ↔ chunk"
        int protocol_id FK "Which protocol"
        int review_chunk_id FK "From review chunk (XOR)"
        int paper_chunk_id FK "From paper chunk (XOR)"
        int paper_id FK "Denormalized for query perf"
        text mention_type "defines|uses|validates|critiques"
        text verbatim_excerpt "Source-specific quote"
        text excerpt_type "method|limitation|biology|obstacle"
    }

    review_chunks {
        int id PK
        text heading "Section from review article"
    }

    paper_chunks {
        int id PK
        text heading "Section from cited paper"
    }

    papers {
        int id PK
        text pmc_id "Paper identifier"
    }
```

---

## Query Flow: RAG + Protocol Context

How a user query flows through the system:

```mermaid
graph TD
    A[User Query: 'NGS for arbovirus in CSF'] --> B[Embed Query]
    B --> C[Vector Search]
    C --> D[review_chunks<br/>embedding cosine similarity]
    C --> E[paper_chunks<br/>embedding cosine similarity]

    D --> F[Top-k Review Chunks]
    E --> G[Top-k Paper Chunks]

    F --> H[Join chunk_citations → citations]
    G --> I[Join papers → citations]

    H --> J[Collect ref_ids: B5, B12, ...]
    I --> J

    F --> K[Build Context Block]
    G --> K
    J --> K

    K --> L[LLM: Generate Answer with Citations]

    L --> M{--quote flag?}
    M -->|Yes| N[BM25 Re-rank Sentences]
    M -->|No| O[Return Answer]

    N --> O

    F --> P[Join protocol_sources → protocols]
    G --> P
    P --> Q[Enrich Answer with Protocol Metadata]
    Q --> O

    O --> R[Display: Answer + Citations + Quotes + Protocols]

    style A fill:#e1f5ff
    style R fill:#d4edda
    style L fill:#fff3cd
    style P fill:#f8d7da
```

---

## Protocol Extraction Flow

How `extract_protocols.py` processes chunks:

```mermaid
graph TD
    A[Chunk Text from DB] --> B[LLM: Structured Extraction<br/>JSON Schema Mode]
    B --> C{NGS Protocol Found?}

    C -->|No| D[Skip - No protocols extracted]
    C -->|Yes| E[Protocol JSON:<br/>modality, specimen, excerpts]

    E --> F[Find Existing Protocol<br/>by Identity Match]
    F --> G{Exists?}

    G -->|Yes| H[Reuse protocol_id]
    G -->|No| I[Insert New Protocol]
    I --> J[Get new protocol_id]
    H --> J

    J --> K[Insert protocol_sources Row<br/>Link: protocol ↔ chunk]
    K --> L[Store: mention_type, verbatim_excerpt]

    L --> M[Next Chunk]
    M --> A

    style B fill:#fff3cd
    style F fill:#e1f5ff
    style K fill:#d4edda
```

---

## Domain Gap Analysis (Planned - Phase 2)

How veterinary corpus integration will enable gap scoring:

```mermaid
graph TD
    A[Medical Literature<br/>domain='medical'] --> B[Extract Protocols]
    C[Veterinary Literature<br/>domain='veterinary'] --> D[Extract Protocols]

    B --> E[Medical Protocol Set<br/>M = 150 protocols]
    D --> F[Veterinary Protocol Set<br/>V = 25 protocols]

    E --> G[Embed All Chunks]
    F --> G

    G --> H[HDBSCAN Clustering<br/>on combined embeddings]

    H --> I[Cluster 1: CNS mNGS<br/>Medical: 45 chunks, Vet: 2 chunks]
    H --> J[Cluster 2: Blood WGS<br/>Medical: 30 chunks, Vet: 18 chunks]
    H --> K[Cluster 3: Respiratory Panels<br/>Medical: 20 chunks, Vet: 0 chunks]

    I --> L[Gap Score = 0.96<br/>HIGH GAP]
    J --> M[Gap Score = 0.25<br/>LOW GAP]
    K --> N[Gap Score = 1.00<br/>TOTAL GAP]

    L --> O[Priority: High-value<br/>translational opportunity]
    M --> P[Priority: Active area,<br/>check for differentiation]
    N --> Q[Priority: Blue ocean<br/>no vet equivalent]

    O --> R[Store cluster_id, gap_score<br/>in chunks/protocols tables]
    P --> R
    Q --> R

    R --> S[Query: 'Show high-gap clusters<br/>with vet_transferability_score ≥ 2']
    S --> T[Output: Ranked translational<br/>opportunities with evidence]

    style I fill:#f8d7da
    style K fill:#f8d7da
    style J fill:#d4edda
    style T fill:#e1f5ff
```

---

## Data Flow: From Download to Query

End-to-end pipeline:

```mermaid
graph LR
    A[PMC HTML Downloads] --> B[extractors/pmc.py<br/>Chunk + Parse Refs]
    B --> C[chunks.json<br/>reference_index.json]

    C --> D[embed_chunks.py<br/>OpenAI API]
    D --> E[embeddings.json<br/>1536-dim vectors]

    E --> F[load_chunks.py<br/>PostgreSQL]
    F --> G[(review_chunks<br/>review_sources<br/>citations)]

    A --> H[load_paper_chunks.py<br/>PostgreSQL]
    H --> I[(papers<br/>paper_chunks)]

    G --> J[extract_protocols.py<br/>LLM JSON Schema]
    I --> J

    J --> K[(protocols<br/>protocol_sources)]

    G --> L[query_kb.py<br/>RAG + BM25]
    I --> L
    K --> L

    L --> M[User: Answer + Citations + Quotes]

    style A fill:#e1f5ff
    style D fill:#fff3cd
    style J fill:#fff3cd
    style L fill:#fff3cd
    style M fill:#d4edda
```

---

## Key Constraints & Indexes

Important schema rules visualized:

```mermaid
graph TD
    A[protocol_sources] --> B{Constraint: Exactly One Chunk}
    B --> C[review_chunk_id IS NOT NULL<br/>XOR<br/>paper_chunk_id IS NOT NULL]

    A --> D[UNIQUE protocol_id, review_chunk_id]
    A --> E[UNIQUE protocol_id, paper_chunk_id]

    F[protocols] --> G[Identity Match:<br/>ngs_modality + pathogen_class +<br/>specimen_type + platform +<br/>bioinformatics_pipeline]
    G --> H[Same identity → Reuse protocol_id<br/>Different source → New protocol_sources row]

    I[review_chunks<br/>paper_chunks] --> J[HNSW Index on embedding<br/>vector_cosine_ops]
    J --> K[Fast vector similarity search<br/>for RAG queries]

    L[citations] --> M[UNIQUE ref_id, source_id<br/>One citation per ref per review]

    style C fill:#f8d7da
    style G fill:#fff3cd
    style J fill:#d4edda
```

---

**Generated:** 2026-02-19
**Database:** `mngs_kb` PostgreSQL schema v2
**Related:** `create_schema.sql`, `SESSION_CONTEXT.md`
