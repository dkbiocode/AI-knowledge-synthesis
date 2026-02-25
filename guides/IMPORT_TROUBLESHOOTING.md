# Import Troubleshooting Guide

## The Problem

When running scripts or web apps, you may encounter:
```
ModuleNotFoundError: No module named 'scripts'
```

This happens when Python can't find the project modules because the working directory isn't in Python's module search path.

## Solutions Applied

### 1. Added `__init__.py` Files

Created package markers:
- `/scripts/__init__.py`
- `/scripts/query/__init__.py`

This makes directories proper Python packages.

### 2. Fixed Import Paths in Scripts

#### In `web_query.py`:
```python
# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Now imports work
from scripts.query.query_kb import embed_query, search, ...
```

#### In `web_aspect_search.py`:
```python
# Import from same directory
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import decompose_query as decompose_module
```

## How to Use in Your Web App

### Option 1: Run from Project Root (Recommended)

```bash
cd /Users/david/work/informatics_ai_workflow
python example_webapp.py
```

In your app:
```python
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Now import works
from scripts.query.web_aspect_search import search_with_highlights
```

### Option 2: Use PYTHONPATH Environment Variable

```bash
export PYTHONPATH="/Users/david/work/informatics_ai_workflow:$PYTHONPATH"
python your_app.py
```

### Option 3: Install as Package (Advanced)

Create `setup.py`:
```python
from setuptools import setup, find_packages

setup(
    name="mngs_kb",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        'openai',
        'psycopg2',
        'flask',
        # ... other dependencies
    ]
)
```

Then install in development mode:
```bash
pip install -e .
```

## Testing Imports

### From Python REPL:
```python
import sys
print(sys.path)  # Check if project root is included

from scripts.query.web_aspect_search import search_with_highlights
print("✓ Import successful")
```

### From Project Root:
```bash
python -c "from scripts.query.web_aspect_search import search_with_highlights; print('✓ Works')"
```

### From Subdirectory:
```bash
cd scripts/query
python -c "import sys; sys.path.insert(0, '../..'); from scripts.query.web_aspect_search import search_with_highlights; print('✓ Works')"
```

## Example Web App Structure

```
/Users/david/work/informatics_ai_workflow/
├── example_webapp.py           # ← Run from here
├── scripts/
│   ├── __init__.py             # ← Package marker
│   └── query/
│       ├── __init__.py         # ← Package marker
│       ├── web_aspect_search.py
│       ├── decompose_query.py
│       └── query_logger.py
└── ...
```

## Common Patterns

### Pattern 1: Flask/FastAPI App

```python
# app.py (in project root)
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from flask import Flask
from scripts.query.web_aspect_search import search_with_highlights

app = Flask(__name__)

@app.route('/api/search', methods=['POST'])
def search():
    html = search_with_highlights(query)
    return {"results": html}
```

### Pattern 2: Streamlit App

```python
# streamlit_app.py (in project root)
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import streamlit as st
from scripts.query.web_aspect_search import search_with_highlights

query = st.text_input("Enter query:")
if query:
    html = search_with_highlights(query)
    st.markdown(html, unsafe_allow_html=True)
```

### Pattern 3: Jupyter Notebook

```python
# In first cell
import os
import sys

PROJECT_ROOT = '/Users/david/work/informatics_ai_workflow'
sys.path.insert(0, PROJECT_ROOT)

# In subsequent cells
from scripts.query.web_aspect_search import search_with_highlights
```

## Debugging Import Issues

### Check Python Path:
```python
import sys
print('\n'.join(sys.path))
```

### Check Current Working Directory:
```python
import os
print(f"CWD: {os.getcwd()}")
print(f"Script location: {os.path.abspath(__file__)}")
```

### Verify Module Exists:
```bash
ls -la /Users/david/work/informatics_ai_workflow/scripts/query/web_aspect_search.py
```

### Test Import Step-by-Step:
```python
# Test 1: Can we import the module?
try:
    import scripts
    print("✓ scripts package found")
except ImportError as e:
    print(f"✗ scripts package not found: {e}")

# Test 2: Can we import the subpackage?
try:
    import scripts.query
    print("✓ scripts.query package found")
except ImportError as e:
    print(f"✗ scripts.query not found: {e}")

# Test 3: Can we import the module?
try:
    from scripts.query import web_aspect_search
    print("✓ web_aspect_search module found")
except ImportError as e:
    print(f"✗ web_aspect_search not found: {e}")

# Test 4: Can we import the function?
try:
    from scripts.query.web_aspect_search import search_with_highlights
    print("✓ search_with_highlights function found")
except ImportError as e:
    print(f"✗ Function not found: {e}")
```

## Quick Fix for Existing Apps

If you have an existing app that's failing, add this at the top:

```python
import os
import sys

# Get the directory containing this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Get the project root (adjust '../..' based on nesting level)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../..'))

# Add to path if not already there
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

print(f"✓ Added {PROJECT_ROOT} to Python path")

# Now imports should work
from scripts.query.web_aspect_search import search_with_highlights
```

## Example Usage

### Working Example (example_webapp.py):

```bash
# From project root
cd /Users/david/work/informatics_ai_workflow
python example_webapp.py

# Visit http://localhost:5000
```

This app includes:
- Proper path setup
- Example high-quality queries
- Color-coded aspect highlighting
- Full integration example

## Still Having Issues?

1. **Check you're running from project root**
2. **Verify `__init__.py` files exist**
3. **Check file permissions** (should be readable)
4. **Verify Python version** (3.8+ required)
5. **Check for circular imports**
6. **Try absolute imports** instead of relative

If all else fails, use:
```bash
cd /Users/david/work/informatics_ai_workflow
export PYTHONPATH="$PWD:$PYTHONPATH"
python your_app.py
```
