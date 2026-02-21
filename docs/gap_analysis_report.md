# Medical-Veterinary NGS Knowledge Gap Analysis

**Date:** 2026-02-19
**Method:** HDBSCAN clustering on 2,829 embedded chunks
**Embedding Model:** OpenAI text-embedding-3-small (1536-dim)

---

## Executive Summary

### Dataset Composition
- **Total chunks analyzed:** 2,829
  - Medical: 2,320 chunks (82%)
  - Veterinary: 509 chunks (18%)
  - Medical:Vet ratio: 4.6:1

### Clustering Results
- **Clusters identified:** 8 topic clusters
- **Noise points:** 1,425 (50.4%) - chunks not fitting clear topic patterns
- **Silhouette score:** 0.211 (moderate cluster coherence)
- **Algorithm:** HDBSCAN with min_cluster_size=20, min_samples=10

### Key Finding
**All 8 clusters are medical-dominated** (gap scores 1.72 to 10.0), indicating significant knowledge transfer opportunities from medical to veterinary NGS diagnostics.

---

## Gap Score Summary

| Cluster | Medical | Vet | Total | Gap Score | Label | Interpretation |
|---------|---------|-----|-------|-----------|-------|----------------|
| **7** | 36 | 0 | 36 | **10.00** | Medical-only | No vet representation - HIGH transfer priority |
| **5** | 64 | 4 | 68 | **4.00** | Medical-dominated | 16:1 ratio - ethics/consent sections |
| **1** | 95 | 13 | 108 | **2.87** | Medical-dominated | 7.3:1 ratio |
| **2** | 35 | 5 | 40 | **2.81** | Medical-dominated | 7:1 ratio |
| **3** | 86 | 13 | 99 | **2.73** | Medical-dominated | 6.6:1 ratio |
| **4** | 79 | 14 | 93 | **2.50** | Medical-dominated | 5.6:1 ratio |
| **6** | 784 | 146 | 930 | **2.42** | Medical-dominated | 5.4:1 ratio - largest cluster (generic sections) |
| **0** | 23 | 7 | 30 | **1.72** | Medical-leaning | 3.3:1 ratio - smallest cluster |

**Gap Score Scale:**
- `10.0` = Medical-only (infinite gap)
- `> 2.0` = Medical-dominated (4x+ more medical chunks)
- `1.0-2.0` = Medical-leaning (2-4x more)
- `-1.0 to 1.0` = Balanced
- `< -2.0` = Vet-dominated/vet-only

---

## Cluster Characterization

### Cluster 7 (Medical-Only) - HIGHEST PRIORITY
- **Size:** 36 chunks
- **Gap:** 10.00 (no veterinary representation)
- **Content:** [Requires manual inspection - see cluster_representatives table]
- **Transfer opportunity:** Protocols in this cluster have zero veterinary coverage

### Cluster 6 (Largest, Medical-Dominated)
- **Size:** 930 chunks (33% of total dataset)
- **Gap:** 2.42 (5.4:1 medical:vet ratio)
- **Content:** Generic paper sections (Introduction, Discussion, Results, Methods, Abstract)
- **Note:** Structural/boilerplate content rather than domain-specific protocols
- **Transfer relevance:** Low - these are paper structure, not technical protocols

### Cluster 5 (Ethics/Consent)
- **Size:** 68 chunks
- **Gap:** 4.00 (16:1 ratio)
- **Content:** Ethics statements, consent procedures, institutional review board sections
- **Transfer relevance:** Low - administrative content, not protocols

### Clusters 0-4 (Protocol-Relevant)
- **Combined size:** 370 chunks
- **Gap range:** 1.72-2.87
- **Likely content:** Technical NGS methods, applications, results
- **Next step:** Manual review to identify specific protocols

---

## Noise Analysis

**50.4% of chunks classified as noise** (1,425 out of 2,829)

**Possible reasons:**
1. **Highly specific content:** Unique methods/protocols not shared across papers
2. **Heterogeneous embeddings:** Chunks covering multiple topics
3. **Small representation:** Topics with <20 chunks don't form clusters
4. **Cluster parameters:** Could adjust min_cluster_size to capture more micro-topics

**Recommendation:** Review noise chunks for high-value outlier protocols

---

## Transferability Assessment

### High-Priority Transfer Clusters
1. **Cluster 7** (medical-only, 36 chunks) - Immediate investigation
2. **Clusters 1-4** (gap 2.5-2.9) - Protocol-heavy content likely

### Low-Priority Clusters
- **Cluster 6** (generic sections) - Structural, not technical
- **Cluster 5** (ethics) - Administrative, not protocol-relevant

### Noise Category
- **1,425 chunks** - May contain unique/novel protocols worth individual review

---

## Next Steps

### 1. Manual Cluster Review
```sql
-- Get representative chunks for cluster 7 (medical-only)
SELECT
  cc.chunk_id,
  CASE
    WHEN cc.chunk_type = 'review' THEN rc.heading
    WHEN cc.chunk_type = 'paper' THEN pc.heading
  END as heading,
  CASE
    WHEN cc.chunk_type = 'review' THEN rc.text
    WHEN cc.chunk_type = 'paper' THEN pc.text
  END as text
FROM chunk_clusters cc
LEFT JOIN review_chunks rc ON cc.chunk_id = 'review_' || rc.id
LEFT JOIN paper_chunks pc ON cc.chunk_id = 'paper_' || pc.id
WHERE cc.cluster_id = 7
LIMIT 10;
```

### 2. Extract Protocols from High-Gap Clusters
Run protocol extraction on clusters 1-4 and 7:
```bash
python extract_protocols.py --cluster-filter "1,2,3,4,7"
```

### 3. Topic Labeling
Manually review 5-10 chunks per cluster and assign semantic labels:
- Cluster 0: ?
- Cluster 1: ?
- Cluster 2: ?
- Cluster 3: ?
- Cluster 4: ?
- Cluster 7: ?

### 4. Refine Clustering (Optional)
If too much noise:
- Increase `min_cluster_size` to 30 for tighter clusters
- OR decrease to 15 to capture more micro-topics
- Try K-means with K=20-30 for comparison

### 5. Protocol Citation Analysis
For high-gap clusters, trace citation chains to external SOPs (protocols.io, CDC, WOAH)

---

## Visualizations

Generated plots in `cluster_plots/`:
1. **umap_by_domain.png** - Medical (blue) vs Veterinary (green) distribution
2. **umap_by_cluster.png** - 8 clusters color-coded
3. **umap_by_gap_score.png** - Heatmap (red=medical-heavy, green=vet-heavy)

---

## Database Queries

### View all gap scores
```sql
SELECT * FROM cluster_gap_scores ORDER BY gap_score DESC;
```

### Find chunks in a specific cluster
```sql
SELECT cc.chunk_id, cc.chunk_type, cc.umap_x, cc.umap_y
FROM chunk_clusters cc
WHERE cc.cluster_id = 7;
```

### Count chunks per cluster by domain
```sql
SELECT
  cc.cluster_id,
  CASE
    WHEN cc.chunk_type = 'review' THEN (SELECT rs.domain FROM review_chunks rc JOIN review_sources rs ON rs.id = rc.source_id WHERE rc.id = REGEXP_REPLACE(cc.chunk_id, '^review_', '')::int)
    WHEN cc.chunk_type = 'paper' THEN (SELECT p.domain FROM paper_chunks pc JOIN papers p ON p.id = pc.paper_id WHERE pc.id = REGEXP_REPLACE(cc.chunk_id, '^paper_', '')::int)
  END as domain,
  COUNT(*) as count
FROM chunk_clusters cc
GROUP BY cc.cluster_id, domain
ORDER BY cc.cluster_id, domain;
```

---

## Limitations

1. **Imbalanced dataset:** 4.6:1 medical:vet ratio means clusters naturally skew medical
2. **Incomplete vet corpus:** Only 25/71 veterinary papers loaded (46 remaining)
3. **Generic content:** Cluster 6 (largest) captures structural sections, not protocols
4. **High noise:** 50% of chunks don't cluster - may need parameter tuning
5. **No topic labels:** Clusters identified numerically, need manual semantic labeling

---

## Recommendations

### Immediate
1. **Manual review cluster 7** (medical-only) for high-value protocols
2. **Label clusters 0-4** with semantic topics
3. **Extract protocols** from high-gap clusters

### Short-term
1. **Complete vet corpus loading** (46 papers remaining) and re-run clustering
2. **Adjust clustering parameters** based on manual review
3. **Compute cluster centroids** and extract top TF-IDF terms for automatic labeling

### Long-term
1. **Build protocol resolution pipeline** (follow citations to external SOPs)
2. **Create transfer recommendation system** (score protocols by vet applicability)
3. **Develop web interface** for browsing clusters and gap scores

---

**Analysis by:** Claude Code
**Scripts:** `cluster_topics.py`, `cluster_schema.sql`
**Data:** PostgreSQL `mngs_kb` database
