"""
web_query.py

Streamlit web interface for querying the NGS knowledge base.

Usage:
  conda activate openai
  streamlit run web_query.py

Environment variables:
  OPENAI_API_KEY (required)
  PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE (optional, defaults to localhost)
"""

import os
import sys
import re
import streamlit as st
import psycopg2
from typing import List, Dict, Set

# Import functions from query_kb.py
from scripts.query.query_kb import (
    embed_query,
    search,
    fetch_citation_metadata,
    format_citation,
    get_conn,
    build_context,
    generate_answer,
)

# Import query analyzer
from src.query_analyzer import analyze_query_specificity, format_analysis_message


# Page configuration
st.set_page_config(
    page_title="NGS Knowledge Base",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def extract_query_terms(query: str) -> Set[str]:
    """Extract meaningful terms from query for highlighting."""
    # Remove common stop words
    stop_words = {
        'what', 'which', 'how', 'when', 'where', 'who', 'why',
        'is', 'are', 'was', 'were', 'the', 'a', 'an', 'and', 'or',
        'for', 'in', 'on', 'at', 'to', 'from', 'by', 'with', 'of'
    }

    # Extract words (alphanumeric sequences)
    words = re.findall(r'\b\w+\b', query.lower())

    # Filter out stop words and short words
    terms = {w for w in words if w not in stop_words and len(w) > 2}

    return terms


def highlight_text(text: str, query_terms: Set[str], max_length: int = None) -> str:
    """
    Highlight query terms in text using HTML.

    Args:
        text: Text to highlight
        query_terms: Set of terms to highlight
        max_length: Maximum length to truncate to (None for full text)

    Returns:
        HTML string with highlighted terms
    """
    if not query_terms:
        result = text
    else:
        # Create regex pattern for all query terms (case insensitive)
        pattern = '|'.join(re.escape(term) for term in query_terms)

        # Highlight matching terms
        result = re.sub(
            f'\\b({pattern})\\b',
            r'<mark style="background-color: #ffeb3b; padding: 0 2px;">\1</mark>',
            text,
            flags=re.IGNORECASE
        )

    # Truncate if needed
    if max_length and len(text) > max_length:
        # Try to find a good break point near max_length
        truncated = text[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.8:  # If we found a space in the last 20%
            truncated = truncated[:last_space]
        result = highlight_text(truncated, query_terms, None) + "..."

    return result


def get_source_label(chunk: Dict, citation_metadata: Dict[str, Dict]) -> str:
    """Create a short source label for the table."""
    ref_ids = chunk.get("ref_ids") or []

    if ref_ids:
        # Use first citation
        ref_id = sorted(ref_ids)[0]
        metadata = citation_metadata.get(ref_id, {})
        formatted = format_citation(ref_id, metadata)
        if len(ref_ids) > 1:
            formatted += f" +{len(ref_ids)-1}"
        return formatted
    else:
        source_type = chunk.get("source_type", "unknown")
        if source_type == "review":
            return "Review"
        else:
            pmc_id = chunk.get('paper_pmc_id', '')
            return pmc_id[:12] if pmc_id else "Paper"


def display_chunk_table_row(chunk: Dict, index: int, citation_metadata: Dict[str, Dict],
                             query_terms: Set[str]) -> None:
    """Display a single chunk as a compact table row."""
    domain = chunk.get("domain", "unknown")
    score = chunk['score']
    text = chunk.get("text", "").strip()
    chunk_id = chunk.get("chunk_id", "?")
    heading = chunk.get("heading", "")
    parent_heading = chunk.get("parent_heading", "")

    # Create section path for debugging
    if parent_heading:
        section = f"{parent_heading} › {heading}"
    else:
        section = heading or "(no heading)"

    # Domain badge
    if domain == "medical":
        domain_badge = "🔵 Med"
    elif domain == "veterinary":
        domain_badge = "🔴 Vet"
    else:
        domain_badge = "⚪ Unk"

    # Source label
    source_label = get_source_label(chunk, citation_metadata)

    # Highlighted text preview
    highlighted_preview = highlight_text(text, query_terms, max_length=300)

    # Create table row with columns
    # Column widths: #, Source, Domain, Score, Highlighted Text, Button
    cols = st.columns([0.5, 1.2, 0.8, 0.6, 3.5, 0.4])

    with cols[0]:
        # Show index and chunk_id for debugging
        st.markdown(f"**{index}**", help=f"Chunk ID: {chunk_id} | Section: {section}")

    with cols[1]:
        st.markdown(f"<small>{source_label}</small>", unsafe_allow_html=True, help=chunk.get("doc_title", ""))

    with cols[2]:
        st.markdown(domain_badge)

    with cols[3]:
        st.markdown(f"`{score:.3f}`")

    with cols[4]:
        st.markdown(highlighted_preview, unsafe_allow_html=True)

    with cols[5]:
        # Click button to show details
        if st.button("🔍", key=f"select_{index}", help="View details"):
            st.session_state.selected_chunk = index


def display_chunk_detail(chunk: Dict, index: int, citation_metadata: Dict[str, Dict],
                         query_terms: Set[str]) -> None:
    """Display full chunk details in the detail pane."""
    domain = chunk.get("domain", "unknown")

    # Domain header
    if domain == "medical":
        st.markdown("### 🔵 Medical Literature")
    elif domain == "veterinary":
        st.markdown("### 🔴 Veterinary Literature")
    else:
        st.markdown("### ⚪ Unknown Domain")

    # Metadata
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(f"**Document:** {chunk.get('doc_title', 'Unknown')}")

        # Section path
        heading = chunk.get("heading") or "(no heading)"
        parent_heading = chunk.get("parent_heading")
        if parent_heading:
            section_path = f"{parent_heading} › {heading}"
        else:
            section_path = heading
        st.markdown(f"**Section:** {section_path}")

    with col2:
        st.metric("Similarity Score", f"{chunk['score']:.3f}")
        st.markdown(f"*{chunk.get('source_type', 'unknown').title()}*")

    # Citations
    ref_ids = chunk.get("ref_ids") or []
    if ref_ids:
        st.markdown("**Citations:**")
        for ref_id in sorted(set(ref_ids)):
            metadata = citation_metadata.get(ref_id, {})
            formatted_cite = format_citation(ref_id, metadata)

            if metadata:
                title = metadata.get('title', '')
                journal = metadata.get('journal', '')

                # PMC link if available
                pmc_id = chunk.get('paper_pmc_id')
                if pmc_id:
                    pmc_link = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"
                    st.markdown(f"- **{formatted_cite}** ({ref_id}): {title}. *{journal}*. [PMC]({pmc_link})")
                else:
                    st.markdown(f"- **{formatted_cite}** ({ref_id}): {title}. *{journal}*")
            else:
                st.markdown(f"- {ref_id}")
    else:
        pmc_id = chunk.get('paper_pmc_id')
        if pmc_id:
            pmc_link = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"
            st.markdown(f"**Source:** [Cited paper ({pmc_id})]({pmc_link})")

    # Full text with highlighting
    st.markdown("**Full Text:**")
    text = chunk.get("text", "").strip()
    highlighted_full = highlight_text(text, query_terms, max_length=None)
    st.markdown(highlighted_full, unsafe_allow_html=True)


def main():
    """Main Streamlit application."""

    # Check for OpenAI API key
    if not os.environ.get("OPENAI_API_KEY"):
        st.error("⚠️ OPENAI_API_KEY environment variable not set.")
        st.stop()

    # Sidebar
    with st.sidebar:
        st.title("⚙️ Settings")

        st.subheader("Search Parameters")
        top_k = st.slider("Number of chunks to retrieve", 1, 20, 8)
        min_score = st.slider("Minimum similarity score", 0.0, 1.0, 0.25, 0.05)
        deduplicate = st.checkbox("Remove duplicate chunks", value=True,
                                  help="Filter out chunks with identical text (data quality issue)")

        st.subheader("Models")
        embed_model = st.selectbox(
            "Embedding model",
            ["text-embedding-3-small", "text-embedding-3-large"],
            index=0,
        )

        chat_model = st.selectbox(
            "Answer generation model",
            ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
            index=0,
            help="Model used to synthesize answers from retrieved chunks"
        )

        st.subheader("Database")
        dbname = st.text_input("Database name", "mngs_kb")

        st.divider()
        st.markdown("""
        ### About
        This interface queries the NGS Knowledge Base, which contains medical and
        veterinary literature on next-generation sequencing diagnostic protocols.

        **Domains:**
        - 🔵 Medical: Human diagnostics
        - 🔴 Veterinary: Animal diagnostics
        """)

    # Initialize session state
    if 'selected_chunk' not in st.session_state:
        st.session_state.selected_chunk = None
    if 'answer' not in st.session_state:
        st.session_state.answer = None
    if 'current_query' not in st.session_state:
        st.session_state.current_query = None

    # Main content
    st.title("🧬 NGS Knowledge Base Query Interface")
    st.markdown("Search medical and veterinary NGS diagnostic literature")

    # Query input
    query = st.text_area(
        "Enter your question:",
        placeholder="What NGS methods detect arboviruses in CSF?",
        height=100,
    )

    # Search button
    search_button = st.button("🔍 Search", type="primary", use_container_width=True)

    # Process search
    if search_button and query.strip():
        # Reset selection and answer on new search
        st.session_state.selected_chunk = None
        st.session_state.answer = None
        st.session_state.current_query = query.strip()

        # Analyze query specificity
        query_analysis = analyze_query_specificity(query.strip())
        st.session_state.query_analysis = query_analysis

        with st.spinner("Embedding query..."):
            try:
                query_vec = embed_query(query.strip(), embed_model)
            except Exception as e:
                st.error(f"Error embedding query: {e}")
                return

        with st.spinner(f"Searching database (top {top_k} chunks)..."):
            try:
                conn = get_conn(dbname)
                cur = conn.cursor()

                hits = search(cur, query_vec, top_k, min_score)

                if not hits:
                    st.warning("No results found above the minimum score threshold. Try lowering the minimum score or broadening your question.")
                    return

                # Fetch citation metadata for all ref_ids
                all_ref_ids = []
                for h in hits:
                    ref_ids = h.get("ref_ids") or []
                    all_ref_ids.extend(ref_ids)
                all_ref_ids = list(set(all_ref_ids))

                citation_metadata = fetch_citation_metadata(cur, all_ref_ids)

                # Deduplicate if requested
                if deduplicate:
                    seen_texts = set()
                    deduped_hits = []
                    duplicates_removed = 0

                    for hit in hits:
                        text = hit.get('text', '').strip()
                        if text not in seen_texts:
                            seen_texts.add(text)
                            deduped_hits.append(hit)
                        else:
                            duplicates_removed += 1

                    hits = deduped_hits
                    if duplicates_removed > 0:
                        st.info(f"ℹ️ Removed {duplicates_removed} duplicate chunk(s)")

                # Store in session state
                st.session_state.hits = hits
                st.session_state.citation_metadata = citation_metadata
                st.session_state.query_terms = extract_query_terms(query.strip())

            except Exception as e:
                st.error(f"Database error: {e}")
                return
            finally:
                cur.close()
                conn.close()

    # Display results if available
    if 'hits' in st.session_state and st.session_state.hits:
        hits = st.session_state.hits
        citation_metadata = st.session_state.citation_metadata
        query_terms = st.session_state.query_terms

        # Summary stats
        st.success(f"✅ Found {len(hits)} relevant chunks")

        # Display query analysis
        if 'query_analysis' in st.session_state:
            analysis = st.session_state.query_analysis

            # Show query type info
            with st.expander("📊 Query Analysis", expanded=False):
                st.markdown(format_analysis_message(analysis))

                if analysis['specificity'] == 'specific':
                    st.markdown(
                        "**Expected Answer Style:** Lists of specific items with citations "
                        "(e.g., pathogen names, method details, protocol specifications)"
                    )
                else:
                    st.markdown(
                        "**Expected Answer Style:** General explanation or overview with examples"
                    )

            # Show warning for specific queries
            if analysis.get('warning'):
                st.warning(analysis['warning'])

        medical_count = sum(1 for h in hits if h.get("domain") == "medical")
        vet_count = sum(1 for h in hits if h.get("domain") == "veterinary")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Chunks", len(hits))
        with col2:
            st.metric("Medical", medical_count)
        with col3:
            st.metric("Veterinary", vet_count)

        st.divider()

        # Answer Generation Section
        st.subheader("🤖 AI-Generated Answer")

        col1, col2 = st.columns([3, 1])
        with col1:
            if st.session_state.answer:
                st.info("Answer generated successfully. Click 'Regenerate Answer' to create a new one.")
            else:
                st.info("Generate a synthesized answer from the retrieved chunks using AI.")

        with col2:
            if st.session_state.answer:
                answer_button_label = "🔄 Regenerate Answer"
            else:
                answer_button_label = "✨ Generate Answer"

            generate_answer_button = st.button(
                answer_button_label,
                use_container_width=True,
                type="secondary"
            )

        # Generate or display answer
        if generate_answer_button or st.session_state.answer:
            if generate_answer_button:
                with st.spinner(f"Generating answer with {chat_model}..."):
                    try:
                        # Build context from hits
                        context = build_context(hits)

                        # Generate answer
                        answer = generate_answer(
                            st.session_state.current_query,
                            context,
                            chat_model
                        )

                        st.session_state.answer = answer
                    except Exception as e:
                        st.error(f"Error generating answer: {e}")
                        st.session_state.answer = None

            # Display answer if available
            if st.session_state.answer:
                with st.container():
                    st.markdown("### Answer")
                    # Display with nice formatting
                    st.markdown(st.session_state.answer)

        st.divider()

        # Table header
        st.subheader("📚 Retrieved Chunks")
        cols = st.columns([0.5, 1.2, 0.8, 0.6, 3.5, 0.4])
        with cols[0]:
            st.markdown("**#**")
        with cols[1]:
            st.markdown("**Source**")
        with cols[2]:
            st.markdown("**Domain**")
        with cols[3]:
            st.markdown("**Score**")
        with cols[4]:
            st.markdown("**Highlighted Text**")
        with cols[5]:
            st.markdown("")

        st.divider()

        # Display chunks as table rows
        for i, chunk in enumerate(hits, 1):
            display_chunk_table_row(chunk, i, citation_metadata, query_terms)

        # Detail pane
        if st.session_state.selected_chunk:
            st.divider()
            st.subheader("📄 Chunk Details")

            selected_idx = st.session_state.selected_chunk - 1  # Convert to 0-indexed
            if 0 <= selected_idx < len(hits):
                selected_chunk = hits[selected_idx]
                display_chunk_detail(selected_chunk, st.session_state.selected_chunk,
                                   citation_metadata, query_terms)

                # Close button
                if st.button("✕ Close Detail View"):
                    st.session_state.selected_chunk = None
                    st.rerun()

    elif search_button:
        st.warning("Please enter a question.")


if __name__ == "__main__":
    main()
