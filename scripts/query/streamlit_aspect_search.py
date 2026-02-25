"""
Streamlit web interface with aspect-based search and color-coded highlighting.

Usage:
  cd /Users/david/work/informatics_ai_workflow
  streamlit run scripts/query/streamlit_aspect_search.py

Environment variables:
  OPENAI_API_KEY (required)
"""

import os
import sys
import streamlit as st
import streamlit.components.v1 as components

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import aspect search
from scripts.query.web_aspect_search import search_with_highlights

# Page configuration
st.set_page_config(
    page_title="NGS Knowledge Base - Aspect Search",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Title
st.title("🧬 NGS Knowledge Base - Aspect Search")

# Sidebar
with st.sidebar:
    st.header("Search Settings")

    num_results = st.slider(
        "Number of results",
        min_value=1,
        max_value=10,
        value=5,
        help="Number of sections to retrieve"
    )

    domain_filter = st.selectbox(
        "Domain filter",
        options=["All", "Medical", "Veterinary"],
        index=0,
        help="Filter results by domain"
    )

    st.markdown("---")
    st.header("About")
    st.markdown("""
    This search uses:
    - **Query decomposition** into aspects
    - **Color-coded highlighting** by aspect category
    - **Sentence-level matching** for precision
    - **Coverage reporting** (how many aspects answered)
    """)

    st.markdown("---")
    st.header("Aspect Colors")
    st.markdown("""
    - 🔵 **Blue** = Methodology
    - 🟢 **Green** = Target/Pathogens
    - 🟠 **Amber** = Sample/Specimen
    - 🟣 **Purple** = Performance
    - 🔴 **Red** = Workflow
    """)

# Example queries
st.subheader("Try these high-quality queries:")

example_queries = [
    "What is the sensitivity of mNGS for bacterial meningitis in CSF?",
    "How does mNGS detect viral infections in CSF?",
    "What mNGS methods detect bacteria in blood samples?",
    "What is the sensitivity and specificity of mNGS for tuberculosis?",
    "What is the turnaround time for mNGS in CSF samples?",
]

cols = st.columns(len(example_queries))
for i, col in enumerate(cols):
    if col.button(f"Example {i+1}", key=f"ex_{i}", use_container_width=True):
        st.session_state.query = example_queries[i]

# Query input
query = st.text_input(
    "Enter your query:",
    value=st.session_state.get('query', example_queries[0]),
    help="Ask a question about NGS diagnostic methods",
    key="query_input"
)

# Update session state
st.session_state.query = query

# Search button
if st.button("🔍 Search", type="primary", use_container_width=True):
    if not query.strip():
        st.warning("Please enter a query")
    else:
        # Convert domain filter
        domain = None
        if domain_filter == "Medical":
            domain = "medical"
        elif domain_filter == "Veterinary":
            domain = "veterinary"

        # Show spinner while searching
        with st.spinner(f"Searching... (decomposing query, embedding {num_results} sections + sentences)"):
            try:
                # Perform aspect-based search
                html_results = search_with_highlights(
                    query=query,
                    limit=num_results,
                    db_name="mngs_kb",
                    domain=domain
                )

                # Display results as HTML
                st.markdown("---")
                components.html(html_results, height=2000, scrolling=True)

            except Exception as e:
                st.error(f"Error during search: {str(e)}")
                st.exception(e)

# Footer
st.markdown("---")
st.caption("NGS Knowledge Base | Aspect-Based Semantic Search with Multi-Granularity Chunking")
