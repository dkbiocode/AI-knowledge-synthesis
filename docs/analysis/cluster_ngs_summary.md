# NGS Topics in Clusters - Quick Reference

**Generated:** 2026-02-19
**Based on:** analyze_cluster_topics.py output

---

## Cluster Priority for NGS Protocol Extraction

### 🔥 HIGH PRIORITY - NGS-Rich Clusters

**Cluster 6** - Main NGS Protocols Cluster
- **Size:** 930 chunks (33% of dataset)
- **Gap Score:** 2.42 (medical-dominated, 5.4:1 ratio)
- **NGS Relevance:** 8996 (HIGHEST)
- **Top NGS Terms:** mNGS (2454), NGS (1079), blood (569), metagenomic (547), CSF (465)
- **Top TF-IDF:** sequencing, mngs, patients, clinical, culture, dna, pathogens, detection
- **Content:** Clinical mNGS applications, pathogen detection, CSF/blood specimens
- **Action:** ✅ **EXTRACT PROTOCOLS FROM THIS CLUSTER**

---

### ⚠️ MEDIUM PRIORITY - Limited NGS Content

**Cluster 3** - Data Availability Statements
- **Size:** 99 chunks
- **Gap Score:** 2.73 (medical-dominated)
- **NGS Relevance:** 25
- **Top NGS Terms:** FASTQ (6), metagenomic (2), NGS (2)
- **Content:** SRA accession numbers, data sharing statements
- **Action:** Low protocol value - skip

**Cluster 7** - Author Contributions
- **Size:** 36 chunks
- **Gap Score:** 10.00 (medical-only)
- **NGS Relevance:** 39
- **Top NGS Terms:** mNGS (5), next-generation sequencing (4), CSF (3)
- **Content:** Author contribution statements, acknowledgments
- **Action:** Low protocol value - skip

---

### ❌ LOW PRIORITY - Administrative Content

**Cluster 0** - Unknown (small cluster)
- **Size:** 30 chunks
- **NGS Relevance:** 0
- **Content:** Generic content - needs manual review

**Cluster 1** - Conflicts of Interest
- **Size:** 108 chunks
- **NGS Relevance:** 0
- **Content:** "conflict, competing, interests"

**Cluster 2** - Supplementary Materials
- **Size:** 40 chunks
- **NGS Relevance:** 0
- **Content:** "supplementary, supplementary material, material"

**Cluster 4** - Associated Data
- **Size:** 93 chunks
- **NGS Relevance:** 0
- **Content:** "data availability, associated data, section"

**Cluster 5** - Ethics Statements
- **Size:** 68 chunks
- **NGS Relevance:** 3
- **Content:** "consent, ethics, written"

---

## Summary Statistics

### NGS Content Distribution
```
Cluster 6:  8996 NGS keywords (99.5% of all NGS content)
Cluster 7:    39 NGS keywords (0.4%)
Cluster 3:    25 NGS keywords (0.3%)
Other:        11 NGS keywords (0.1%)
---------------------------------------------------------
TOTAL:      9074 NGS keywords across 1404 clustered chunks
```

### Medical-Veterinary Gap by Cluster Type
```
NGS-rich (C6):     784 medical, 146 vet (5.4:1)
Administrative:   1536 medical, 363 vet (4.2:1)
```

---

## Recommendations

### For Protocol Extraction
1. **Focus on Cluster 6** - Contains 99.5% of NGS-specific content
2. **Run targeted extraction:**
   ```bash
   python extract_protocols.py --cluster-id 6 --source papers
   ```
3. **Skip clusters 0-5, 7** - Administrative/structural content

### For Topic Discovery
Cluster 6 is too broad (930 chunks). Consider:
1. **Sub-cluster Cluster 6** using tighter parameters:
   ```bash
   # Extract just Cluster 6 chunks and re-cluster
   python cluster_topics.py --cluster-filter 6 --min-cluster-size 15
   ```
2. **Use TF-IDF terms** to identify sub-topics within C6:
   - CSF/CNS infections
   - Blood/plasma diagnostics
   - Pathogen detection methods
   - Clinical validation studies

### For Gap Analysis
- **Current 5.4:1 medical:vet ratio in Cluster 6** suggests strong transfer opportunity
- **After loading remaining 46 vet papers:** Re-run clustering to see if gap narrows
- **High-value targets:** mNGS for CSF (465 mentions), blood diagnostics (569 mentions)

---

## Next Steps While Pipeline Runs

1. ✅ **Extract protocols from Cluster 6**
   ```bash
   python extract_protocols.py --source papers --cluster-id 6
   ```

2. ✅ **Query representative chunks**
   ```sql
   SELECT
     cc.chunk_id,
     pc.heading,
     LEFT(pc.text, 200) as preview,
     p.pmc_id,
     p.domain
   FROM chunk_clusters cc
   JOIN paper_chunks pc ON cc.chunk_id = 'paper_' || pc.id
   JOIN papers p ON pc.paper_id = p.id
   WHERE cc.cluster_id = 6
     AND pc.text ~* '(mngs|metagenomic|ngs)'
     AND LENGTH(pc.text) > 500
   ORDER BY RANDOM()
   LIMIT 10;
   ```

3. ✅ **Update SESSION_CONTEXT.md** with clustering findings

---

**Key Insight:**
The clustering successfully separated **NGS technical content (Cluster 6)** from **administrative boilerplate (Clusters 0-5, 7)**. This allows focused protocol extraction from the 930-chunk NGS-rich cluster rather than processing all 2,829 chunks.
