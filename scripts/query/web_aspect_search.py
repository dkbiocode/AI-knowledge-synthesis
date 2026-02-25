#!/usr/bin/env python3
"""
Web-app ready aspect-based search with color-coded highlighting.

This module provides HTML output with:
- Color-coded highlights per aspect category
- Alpha-scaled by match score
- Mouseover tooltips showing scores
- Sentence-level highlighting in context

Usage:
    from web_aspect_search import search_with_highlights

    html_results = search_with_highlights(
        query="what specific pathogens are found using long read sequencing methods?",
        limit=5
    )
"""

import os
import sys
import psycopg2
from openai import OpenAI
from typing import List, Dict, Any
import html as html_module

# Add parent directory to path for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from config.db_config import get_connection

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Color palette for aspect categories
ASPECT_COLORS = {
    "methodology": "#3B82F6",  # Blue
    "target": "#10B981",        # Green
    "sample": "#F59E0B",        # Amber
    "performance": "#8B5CF6",   # Purple
    "workflow": "#EF4444",      # Red
    "comparison": "#EC4899",    # Pink
    "clinical_context": "#06B6D4",  # Cyan
    "validation": "#6366F1"     # Indigo
}


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return html_module.escape(text)


def generate_highlight_span(
    text: str,
    aspect_category: str,
    score: float,
    aspect_question: str
) -> str:
    """
    Generate HTML span with color-coded highlight.

    Args:
        text: Text to highlight
        aspect_category: Category (methodology, target, etc.)
        score: Match score (0-1)
        aspect_question: The aspect question for tooltip

    Returns:
        HTML span element
    """
    color = ASPECT_COLORS.get(aspect_category, "#6B7280")  # Default gray
    alpha = score  # Alpha scales directly with score

    # Create rgba color with alpha
    # Convert hex to rgb, then add alpha
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    bg_color = f"rgba({r}, {g}, {b}, {alpha * 0.4})"  # 0.4 max alpha for readability

    tooltip = f"{aspect_question} (score: {score:.3f})"

    return (
        f'<span style="background-color: {bg_color}; '
        f'padding: 2px 4px; border-radius: 3px;" '
        f'title="{escape_html(tooltip)}">'
        f'{escape_html(text)}'
        f'</span>'
    )


def search_with_highlights(
    query: str,
    limit: int = 5,
    db_config: str = "local",
    domain: str = None
) -> str:
    """
    Perform aspect-based search with color-coded HTML highlighting.

    Args:
        query: User query
        limit: Number of sections to retrieve
        db_config: Database configuration to use ('local' or 'supabase')
        domain: Optional domain filter ('medical' or 'veterinary')

    Returns:
        HTML string with highlighted results
    """
    # Import decomposition from same directory
    import sys
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    import decompose_query as decompose_module
    decompose_query_func = decompose_module.decompose_query

    # Step 1: Decompose query
    decomposition = decompose_query_func(query)

    # Step 2: Generate embeddings
    texts_to_embed = [query] + [aspect["question"] for aspect in decomposition["aspects"]]
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts_to_embed
    )

    query_embedding = response.data[0].embedding
    aspect_embeddings = {
        decomposition["aspects"][i]["name"]: response.data[i+1].embedding
        for i in range(len(decomposition["aspects"]))
    }

    # Step 3: Connect to database and search sections
    conn = get_connection(db_config)
    cursor = conn.cursor()

    domain_filter = ""
    params = [query_embedding, query_embedding, limit]
    if domain:
        domain_filter = "AND p.domain = %s"
        params.insert(2, domain)

    cursor.execute(f"""
        SELECT
            pc.id AS chunk_id,
            p.id AS paper_id,
            p.title,
            p.authors,
            p.year,
            p.domain,
            pc.heading,
            pc.full_text,
            1 - (pc.embedding <=> %s::vector) AS similarity
        FROM paper_chunks pc
        JOIN papers p ON pc.paper_id = p.id
        WHERE pc.embedding IS NOT NULL
          {domain_filter}
        ORDER BY pc.embedding <=> %s::vector
        LIMIT %s
    """, params)

    sections = cursor.fetchall()

    # Build HTML output
    html_parts = []

    # Header
    html_parts.append(f"""
    <div class="aspect-search-results">
        <div class="query-header">
            <h2>Query: {escape_html(query)}</h2>
            <div class="complexity-badge">
                {'COMPLEX' if decomposition['is_complex'] else 'SIMPLE'}
            </div>
        </div>

        <div class="aspects-legend">
            <h3>Aspects Identified:</h3>
            <ul class="aspects-list">
    """)

    for i, aspect in enumerate(decomposition["aspects"], 1):
        color = ASPECT_COLORS.get(aspect["category"], "#6B7280")
        html_parts.append(f"""
            <li>
                <span style="display: inline-block; width: 12px; height: 12px;
                             background-color: {color}; border-radius: 2px;
                             margin-right: 6px;"></span>
                <strong>[{aspect["category"].upper()}]</strong> {escape_html(aspect["question"])}
            </li>
        """)

    html_parts.append("</ul></div>")

    # Process each section
    for rank, section in enumerate(sections, 1):
        chunk_id, paper_id, title, authors, year, domain, heading, full_text, section_score = section

        # Format citation
        first_author = authors.split(',')[0] if authors else "Unknown"
        citation = f"{first_author} et al. {year}" if year else first_author
        domain_label = "MEDICAL" if domain == "medical" else "VETERINARY"

        html_parts.append(f"""
        <div class="result-section" style="margin-top: 30px; border: 1px solid #E5E7EB;
                                           border-radius: 8px; padding: 20px;">
            <div class="result-header">
                <h3>Result {rank}: {escape_html(citation)}</h3>
                <span class="domain-badge" style="background-color: {'#3B82F6' if domain == 'medical' else '#10B981'};
                                                   color: white; padding: 4px 8px; border-radius: 4px;
                                                   font-size: 12px;">{domain_label}</span>
            </div>
            <div class="section-info" style="margin: 10px 0;">
                <strong>Section:</strong> {escape_html(heading)}<br>
                <strong>Section Score:</strong> {section_score:.3f}
            </div>
        """)

        # Get all sentences for this section
        cursor.execute("""
            SELECT
                id,
                sentence_index,
                text
            FROM paper_sentences
            WHERE paper_chunk_id = %s
            ORDER BY sentence_index
        """, (chunk_id,))

        all_sentences = cursor.fetchall()

        if not all_sentences:
            html_parts.append("<p><em>⚠️ No sentences found in this section</em></p></div>")
            continue

        # Find best match for each aspect
        aspect_matches = {}
        for aspect in decomposition["aspects"]:
            aspect_name = aspect["name"]
            aspect_emb = aspect_embeddings[aspect_name]

            cursor.execute("""
                SELECT
                    id,
                    sentence_index,
                    text,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM paper_sentences
                WHERE paper_chunk_id = %s
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 1
            """, (aspect_emb, chunk_id, aspect_emb))

            result = cursor.fetchone()
            if result:
                aspect_matches[aspect_name] = {
                    "sentence_id": result[0],
                    "sentence_index": result[1],
                    "text": result[2],
                    "score": result[3],
                    "aspect": aspect
                }

        # Build highlighted text with context
        highlighted_indices = set()
        highlight_map = {}  # sentence_index -> (aspect, score)

        for aspect_name, match in aspect_matches.items():
            idx = match["sentence_index"]
            highlighted_indices.add(idx)
            highlight_map[idx] = (match["aspect"], match["score"])

        # Generate highlighted excerpt (show ±1 sentence context for each highlight)
        excerpt_parts = []
        shown_indices = set()

        for aspect_name, match in sorted(
            aspect_matches.items(),
            key=lambda x: x[1]["sentence_index"]
        ):
            matched_idx = match["sentence_index"]

            # Collect sentences: 1 before, matched, 1 after
            context_indices = []
            for idx in [matched_idx - 1, matched_idx, matched_idx + 1]:
                if idx >= 0 and idx not in shown_indices:
                    context_indices.append(idx)
                    shown_indices.add(idx)

            if not context_indices:
                continue

            excerpt_parts.append('<div class="aspect-excerpt" style="margin: 15px 0; padding: 10px; background-color: #F9FAFB; border-radius: 4px;">')

            # Add aspect label
            color = ASPECT_COLORS.get(match["aspect"]["category"], "#6B7280")
            score = match["score"]

            if score >= 0.70:
                quality = "STRONG MATCH"
            elif score >= 0.55:
                quality = "WEAK MATCH"
            else:
                quality = "POOR MATCH"

            excerpt_parts.append(f"""
                <div style="margin-bottom: 8px;">
                    <span style="display: inline-block; width: 12px; height: 12px;
                                 background-color: {color}; border-radius: 2px;
                                 margin-right: 6px;"></span>
                    <strong>[{match["aspect"]["category"].upper()}]</strong>
                    {escape_html(match["aspect"]["question"])}
                    <span style="color: #6B7280; font-size: 14px;"> — {quality} ({score:.3f})</span>
                </div>
            """)

            # Add sentences with highlighting
            excerpt_parts.append('<div style="line-height: 1.6; color: #374151;">')

            for sent_id, sent_idx, sent_text in all_sentences:
                if sent_idx not in context_indices:
                    continue

                if sent_idx == matched_idx:
                    # Highlight this sentence
                    highlighted_text = generate_highlight_span(
                        sent_text,
                        match["aspect"]["category"],
                        score,
                        match["aspect"]["question"]
                    )
                    excerpt_parts.append(highlighted_text + " ")
                else:
                    # Context sentence (not highlighted)
                    excerpt_parts.append(escape_html(sent_text) + " ")

            excerpt_parts.append('</div></div>')

        html_parts.append("".join(excerpt_parts))
        html_parts.append("</div>")  # Close result-section

    html_parts.append("</div>")  # Close aspect-search-results

    cursor.close()
    conn.close()

    return "".join(html_parts)


def generate_standalone_html(query: str, limit: int = 5, output_file: str = None) -> str:
    """
    Generate standalone HTML page with search results.

    Args:
        query: Search query
        limit: Number of results
        output_file: Optional file path to save HTML

    Returns:
        Complete HTML document
    """
    results_html = search_with_highlights(query, limit)

    html_doc = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aspect-Based Search Results</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #F3F4F6;
        }}
        .aspect-search-results {{
            background-color: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .query-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        .query-header h2 {{
            margin: 0;
            color: #111827;
        }}
        .complexity-badge {{
            background-color: #6366F1;
            color: white;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 14px;
            font-weight: bold;
        }}
        .aspects-legend {{
            background-color: #F9FAFB;
            border: 1px solid #E5E7EB;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 30px;
        }}
        .aspects-legend h3 {{
            margin-top: 0;
            color: #374151;
        }}
        .aspects-list {{
            list-style: none;
            padding: 0;
            margin: 10px 0 0 0;
        }}
        .aspects-list li {{
            margin: 8px 0;
            color: #1F2937;
        }}
        .result-section {{
            transition: box-shadow 0.2s;
        }}
        .result-section:hover {{
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .result-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .result-header h3 {{
            margin: 0;
            color: #111827;
        }}
        .section-info {{
            color: #6B7280;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    {results_html}
</body>
</html>
    """

    if output_file:
        with open(output_file, 'w') as f:
            f.write(html_doc)
        print(f"HTML saved to: {output_file}")

    return html_doc


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python web_aspect_search.py '<query>' [output.html]")
        sys.exit(1)

    query = " ".join(sys.argv[1:-1]) if len(sys.argv) > 2 else sys.argv[1]
    output_file = sys.argv[-1] if len(sys.argv) > 2 and sys.argv[-1].endswith('.html') else None

    if not output_file:
        output_file = "aspect_search_results.html"

    generate_standalone_html(query, limit=5, output_file=output_file)
    print(f"\n✓ Generated HTML output: {output_file}")
    print(f"  Open in browser to view highlighted results")
