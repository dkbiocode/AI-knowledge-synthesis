# Directory Reorganization Plan

## 📊 Current State
- **68 files** in root directory
- **18 tracked by git** (will use `git mv`)
- **50 untracked** (will use regular `mv`)

## 🎯 New Structure

```
informatics_ai_workflow/
├── scripts/
│   ├── data_ingestion/    # 13 files (add, download, load, embed)
│   ├── analysis/          #  6 files (cluster, extract protocols)
│   ├── query/             #  4 files (query_kb.py, web_query.py)
│   └── utilities/         #  7 files (cleanup, debug, parse)
├── src/                    # Importable Python modules
│   ├── extractors/        # Moved from root
│   ├── query_analyzer.py
│   └── admin_blacklist.py
├── sql/                    # Database schemas (3 files)
├── data/                   # All data files (git-ignored)
├── figures/                # Plots and visualizations
└── docs/                   # Documentation (7 MD files)
```

## 🔄 Git-Tracked Files (using `git mv`)

The following files will be moved with `git mv` to preserve history:

1. **Scripts:**
   - download_pmc.py
   - embed_chunks.py
   - load_chunks.py
   - load_paper_chunks.py
   - chunk_article.py
   - extract_protocols.py
   - query_kb.py
   - setup_db.py
   - mb.py

2. **Extractors (directory):**
   - extractors/__init__.py
   - extractors/base.py
   - extractors/pmc.py

3. **SQL:**
   - create_schema.sql
   - migrate_v2.sql

4. **Docs:**
   - PERSPECTIVE.md
   - SCHEMA_DIAGRAMS.md (stays in root)
   - SESSION_CONTEXT.md (stays in root)

5. **.gitignore** (updated, stays in root)

## 📦 Untracked Files (regular `mv`)

50 files created during analysis/development phases

## 🚀 Execution Steps

### 1. Stop the Streamlit server
```bash
# Press Ctrl+C in the terminal running web_query.py
```

### 2. Run organization
```bash
python organize_project.py
```

### 3. Update imports
```bash
python update_imports.py
```

### 4. Commit git changes
```bash
git status  # Review moved files
git add .
git commit -m "Reorganize project structure

- Move scripts into categorized subdirectories
- Move source code to src/ module
- Move data files to data/
- Move documentation to docs/
- Update .gitignore for new structure
"
```

### 5. Test functionality
```bash
# Test web interface
cd scripts/query
python -m streamlit run web_query.py

# Test query from root
python -m scripts.query.query_kb -q "test query"
```

## ⚠️ Important Notes

1. **Git history preserved**: All tracked files use `git mv`
2. **Imports updated automatically**: `update_imports.py` fixes all paths
3. **Data stays local**: All data files in `data/` are git-ignored
4. **Streamlit server**: Will need to restart at new path

## 🔙 Rollback Plan

If something goes wrong:

```bash
git reset --hard HEAD  # Undo git moves
# Untracked files will need manual cleanup
```

## ✅ Verification Checklist

After reorganization:
- [ ] All git-tracked files show in `git status` as renamed
- [ ] No import errors when running scripts
- [ ] Web interface starts successfully
- [ ] Database queries work
- [ ] No files left in root (except core docs, .gitignore, organize scripts)
