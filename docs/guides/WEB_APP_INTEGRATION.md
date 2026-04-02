# Web App Integration Guide

## Aspect-Based Search with Color-Coded Highlighting

### Quick Start

```python
from scripts.query.web_aspect_search import search_with_highlights

# In your Flask/FastAPI endpoint
@app.post("/api/search")
def search_endpoint(query: str):
    # Generate HTML with color-coded highlights
    html_results = search_with_highlights(
        query=query,
        limit=5,
        domain=None  # or 'medical' or 'veterinary'
    )

    return {
        "results_html": html_results,
        "status": "success"
    }
```

### Frontend Integration

```html
<!-- Search form -->
<form id="search-form">
    <input type="text" id="query" placeholder="Enter your query...">
    <button type="submit">Search</button>
</form>

<!-- Results container -->
<div id="results-container"></div>

<script>
document.getElementById('search-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const query = document.getElementById('query').value;

    const response = await fetch('/api/search', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query: query})
    });

    const data = await response.json();

    // Inject HTML results
    document.getElementById('results-container').innerHTML = data.results_html;
});
</script>
```

## Color Scheme Reference

The system uses color-coding for different aspect categories:

| Aspect Category | Color | Hex Code |
|----------------|-------|----------|
| Methodology | Blue | #3B82F6 |
| Target (Pathogens) | Green | #10B981 |
| Sample (Specimen) | Amber | #F59E0B |
| Performance | Purple | #8B5CF6 |
| Workflow | Red | #EF4444 |
| Comparison | Pink | #EC4899 |
| Clinical Context | Cyan | #06B6D4 |
| Validation | Indigo | #6366F1 |

## Highlighting Features

### 1. Alpha Scaling by Score

```python
# Score → Opacity mapping
alpha = score * 0.4  # Max 40% opacity for readability

# Example:
# score=0.9 → alpha=0.36 (36% opacity) - Very visible
# score=0.7 → alpha=0.28 (28% opacity) - Moderately visible
# score=0.5 → alpha=0.20 (20% opacity) - Faint
```

### 2. Mouseover Tooltips

Each highlighted span includes:
```html
<span title="What specific pathogens are detected? (score: 0.635)">
    Highlighted sentence text
</span>
```

### 3. Context Display

Shows ±1 sentence around each match:
- Previous sentence (context, not highlighted)
- **Matched sentence (highlighted with color + alpha)**
- Next sentence (context, not highlighted)

## Advanced Usage

### Custom Styling

You can override the default styles in your web app:

```css
/* Override highlight opacity */
.aspect-search-results span[style*="background-color"] {
    /* Your custom styles */
}

/* Add highlight border */
.aspect-search-results span[title] {
    border-bottom: 2px solid currentColor;
}

/* Hover effects */
.aspect-search-results span[title]:hover {
    filter: brightness(0.9);
    cursor: help;
}
```

### Programmatic Access

If you need structured data instead of HTML:

```python
from scripts.query import decompose_query
from scripts.query import query_logger
import psycopg2
from openai import OpenAI

def structured_search(query: str):
    """
    Returns structured JSON instead of HTML.
    """
    # Decompose
    decomposition = decompose_query.decompose_query(query)

    # Generate embeddings
    client = OpenAI()
    texts = [query] + [a["question"] for a in decomposition["aspects"]]
    response = client.embeddings.create(model="text-embedding-3-small", input=texts)

    embeddings = [item.embedding for item in response.data]

    # Search (pseudo-code - implement your own logic)
    results = []
    for section in search_sections(embeddings[0], limit=5):
        aspect_matches = []

        for i, aspect in enumerate(decomposition["aspects"]):
            sentence = search_best_sentence(section.id, embeddings[i+1])

            aspect_matches.append({
                "aspect": aspect["question"],
                "category": aspect["category"],
                "sentence": sentence.text,
                "score": sentence.score,
                "color": ASPECT_COLORS[aspect["category"]]
            })

        results.append({
            "citation": section.citation,
            "section": section.heading,
            "section_score": section.score,
            "aspects": aspect_matches
        })

    return {
        "query": query,
        "decomposition": decomposition,
        "results": results
    }
```

## Query Logging

Don't forget to log queries for analytics:

```python
from scripts.query.query_logger import log_decomposed_query

# After search, log to database
conn = psycopg2.connect("dbname=mngs_kb")
cursor = conn.cursor()

parent_id = log_decomposed_query(
    cursor,
    parent_query=query,
    parent_embedding=query_embedding,
    aspects=[
        {
            **aspect,
            "embedding": aspect_embeddings[aspect["name"]]
        }
        for aspect in decomposition["aspects"]
    ],
    reasoning=decomposition["reasoning"],
    user_id=current_user.id,  # From your auth system
    session_id=session.id
)

conn.commit()
```

## Example Flask App

Complete minimal example:

```python
from flask import Flask, request, jsonify, render_template
from scripts.query.web_aspect_search import search_with_highlights
from scripts.query.query_logger import log_decomposed_query
import psycopg2

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('search.html')

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({"error": "Query required"}), 400

    # Perform search
    html_results = search_with_highlights(query, limit=5)

    # TODO: Log query to database
    # log_decomposed_query(...)

    return jsonify({
        "results_html": html_results,
        "status": "success"
    })

if __name__ == '__main__':
    app.run(debug=True)
```

## Testing

Test the HTML output locally:

```bash
# Generate standalone HTML file
python scripts/query/web_aspect_search.py \
  "what specific pathogens are found using long read sequencing methods?" \
  test_results.html

# Open in browser
open test_results.html  # macOS
# or
xdg-open test_results.html  # Linux
# or
start test_results.html  # Windows
```

## Performance Considerations

- **Decomposition**: ~500ms (LLM call)
- **Embedding generation**: ~200ms (batch API call for 1 query + N aspects)
- **Database search**: ~100-200ms (depends on section + sentence queries)
- **Total**: ~800-900ms per complex query

**Optimization tips:**
1. Cache decompositions for common queries
2. Use async/await for concurrent operations
3. Implement query result caching (Redis)
4. Pre-compute embeddings for frequent aspect questions

## Browser Compatibility

The HTML output uses standard CSS and works in all modern browsers:
- ✅ Chrome/Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+

Features used:
- CSS rgba() colors
- Flexbox layouts
- HTML5 title attribute (tooltips)
- Border-radius, box-shadow

No JavaScript required for basic display (progressive enhancement recommended for interactivity).
