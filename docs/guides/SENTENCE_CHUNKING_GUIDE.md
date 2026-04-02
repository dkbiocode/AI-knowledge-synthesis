# Sentence-Level Chunking Guide

## Overview

The knowledge base now supports **multi-granularity semantic search** with both section-level and sentence-level embeddings.

### Why Two Granularities?

- **Section-level**: Captures conceptual context, discourse structure, and topic relevance
- **Sentence-level**: Enables precise fact extraction and transparent result highlighting

## Database Schema

### Tables

```sql
paper_sentences (
    id SERIAL PRIMARY KEY,
    paper_chunk_id INT → paper_chunks(id),
    sentence_index INT,
    text TEXT,
    embedding vector(1536)
)

review_sentences (
    id SERIAL PRIMARY KEY,
    review_chunk_id INT → review_chunks(id),
    sentence_index INT,
    text TEXT,
    embedding vector(1536)
)
```

### Statistics
- **Total sentences**: 31,805
- **Paper sentences**: ~31,023
- **Review sentences**: ~782
- **Average**: ~11 sentences per chunk
- **Embedding cost**: ~$0.013 (one-time)

## Pipeline Scripts

### 1. Extract Sentences
```bash
python scripts/data_ingestion/extract_sentences.py \
  --source both \
  --output all_sentences.json
```

**Features**:
- Regex-based sentence splitting optimized for scientific text
- Handles abbreviations (et al., Fig., Dr., etc.)
- Filters short fragments (< 20 chars)
- Output: JSON with chunk_id, sentences, and indices

### 2. Generate Embeddings
```bash
python scripts/data_ingestion/embed_sentences.py \
  --input all_sentences.json \
  --output all_sentence_embeddings.json
```

**Features**:
- Batch processing (100 sentences per API call)
- Cost estimation before running
- Progress tracking
- Uses text-embedding-3-small model

### 3. Load to Database
```bash
python scripts/data_ingestion/load_sentences.py \
  --input all_sentence_embeddings.json
```

**Features**:
- Loads to paper_sentences and review_sentences tables
- Duplicate prevention (ON CONFLICT)
- Verification step
- `--force` flag to reload

## Usage Patterns

### Hierarchical Search (Recommended)

```python
# 1. Section-level search (broad context)
top_sections = semantic_search(
    query_embedding,
    paper_chunks,
    limit=10
)

# 2. Sentence-level search within top sections
for section in top_sections:
    sentences = get_sentences(section.chunk_id)
    best_sentence = semantic_search(
        query_embedding,
        sentences,
        limit=1
    )[0]

    # Show section with highlighted sentence
    print(f"Section score: {section.score}")
    print(f"Best sentence score: {best_sentence.score}")

    if best_sentence.score > 0.75:
        print("🎯 DIRECT ANSWER")
    elif section.score > 0.75 and best_sentence.score < 0.60:
        print("📖 TOPIC DISCUSSED (no specific answer)")
```

### Result Quality Labels

Based on combined scores:

| Section Score | Sentence Score | Label |
|--------------|----------------|-------|
| High (>0.75) | High (>0.75) | 🎯 DIRECT ANSWER |
| High (>0.75) | Low (<0.60) | 📖 TOPIC DISCUSSED |
| High (>0.75) | Mid (0.60-0.75) | 📌 PARTIAL ANSWER |
| Low (<0.75) | Any | ❓ WEAK MATCH |

## Future Enhancements

### Query Decomposition (Planned)

For complex queries like:
> "What NGS methods detect arboviruses in CSF and what are their sensitivity and turnaround times?"

Decompose into aspects:
1. Method (NGS modality)
2. Pathogen (arbovirus)
3. Specimen (CSF)
4. Performance (sensitivity)
5. Workflow (turnaround time)

Then search each aspect separately and report coverage (e.g., "3/5 aspects answered").

### Protocol Extraction Enhancement

Link protocol fields to source sentences:
```python
protocol = {
    "ngs_modality": "metagenomic NGS",
    "ngs_modality_source_sentence_id": 12345,
    "sensitivity": "87%",
    "sensitivity_source_sentence_id": 12350,
    ...
}
```

## Maintenance

### Reindexing Vector Indexes

After loading all sentences:
```sql
-- Drop and recreate indexes for better performance
DROP INDEX idx_paper_sentences_embedding;
CREATE INDEX idx_paper_sentences_embedding
    ON paper_sentences USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);  -- Adjust based on row count
```

### Adding New Data

When adding new papers/reviews:
1. Load chunks normally (existing workflow)
2. Run sentence extraction on new chunks only
3. Generate embeddings
4. Load sentences to database

## Files

| File | Purpose |
|------|---------|
| `sentence_schema.sql` | Database schema for sentence tables |
| `extract_sentences.py` | Extract sentences from chunks |
| `embed_sentences.py` | Generate OpenAI embeddings |
| `load_sentences.py` | Load sentences to database |

## Date Created
2026-02-22

## Status
✅ Infrastructure complete
🔄 Embeddings generating (in progress)
📋 Enhanced query script (pending)
