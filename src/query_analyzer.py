"""
Query Analyzer - Detect if user is asking for specific details vs. general information

This helps set appropriate expectations before answer generation.
"""

import re
from typing import Dict, List


def analyze_query_specificity(query: str) -> Dict:
    """
    Analyze whether the query is asking for specific details or general information.

    Returns:
        {
            "specificity": "specific" | "general",
            "query_type": "list" | "comparison" | "explanation" | "definition",
            "expected_details": ["pathogens", "methods", "protocols", etc.],
            "warning": "Optional warning if specific details may not be available"
        }
    """
    query_lower = query.lower()

    # Patterns that indicate requests for specific details
    specific_patterns = [
        r'\bspecific\b',
        r'\bwhich\s+\w+\b',
        r'\blist\b',
        r'\bname\b',
        r'\benumerate\b',
        r'\bidentify\s+(the|all)\b',
        r'\bwhat\s+(specific|exact|particular)\b',
        r'\bhow\s+many\b',
    ]

    # Patterns that indicate general questions
    general_patterns = [
        r'\bhow\s+(does|do|can)\b',
        r'\bwhy\b',
        r'\bexplain\b',
        r'\bdescribe\b',
        r'\bwhat\s+(is|are)\s+(?!specific)',
        r'\boverview\b',
        r'\bsummary\b',
    ]

    # Entity types being requested
    entity_patterns = {
        'pathogens': [r'\bpathogen', r'\bbacter', r'\bvirus', r'\bfung', r'\bparasit', r'\bspecies', r'\bstrain'],
        'methods': [r'\bmethod', r'\bprotocol', r'\bprocedure', r'\btechnique', r'\bapproach'],
        'platforms': [r'\bplatform', r'\bsequenc(er|ing)', r'\binstrument', r'\bdevice'],
        'specimens': [r'\bspecimen', r'\bsample', r'\btissue', r'\bfluid', r'\bCSF', r'\bblood'],
        'metrics': [r'\bsensitivity', r'\bspecificity', r'\baccuracy', r'\bresult', r'\boutcome'],
    }

    # Check for specificity
    is_specific = any(re.search(pattern, query_lower) for pattern in specific_patterns)
    is_general = any(re.search(pattern, query_lower) for pattern in general_patterns)

    # Determine query type
    if re.search(r'\b(list|enumerate|which|name)\b', query_lower):
        query_type = "list"
    elif re.search(r'\b(compar|versus|vs|difference|similar)\b', query_lower):
        query_type = "comparison"
    elif re.search(r'\b(how|why|explain|describe)\b', query_lower):
        query_type = "explanation"
    else:
        query_type = "definition"

    # Identify expected entities
    expected_details = []
    for entity_type, patterns in entity_patterns.items():
        if any(re.search(pattern, query_lower) for pattern in patterns):
            expected_details.append(entity_type)

    # Determine specificity level
    if is_specific or query_type == "list":
        specificity = "specific"
        warning = (
            "⚠️ This query requests specific details. "
            "If the answer contains vague generalizations instead of specific names/values, "
            "the information may not be present in the retrieved sources."
        )
    else:
        specificity = "general"
        warning = None

    return {
        "specificity": specificity,
        "query_type": query_type,
        "expected_details": expected_details,
        "warning": warning,
    }


def format_analysis_message(analysis: Dict) -> str:
    """Format the analysis as a user-friendly message."""
    msg_parts = []

    msg_parts.append(f"**Query Type:** {analysis['query_type'].title()}")

    if analysis['expected_details']:
        entities = ", ".join(analysis['expected_details'])
        msg_parts.append(f"**Expected Details:** {entities}")

    msg_parts.append(f"**Specificity:** {analysis['specificity'].title()}")

    return " | ".join(msg_parts)


# Example usage
if __name__ == "__main__":
    test_queries = [
        "what specific pathogens are found using long read sequencing methods?",
        "what diagnostic methods use long read sequencing?",
        "how does nanopore sequencing work?",
        "list all bacteria detected with mNGS",
        "compare sensitivity of Illumina vs PacBio",
    ]

    for query in test_queries:
        print(f"\nQuery: {query}")
        analysis = analyze_query_specificity(query)
        print(f"  Specificity: {analysis['specificity']}")
        print(f"  Type: {analysis['query_type']}")
        print(f"  Expected: {analysis['expected_details']}")
        if analysis['warning']:
            print(f"  Warning: {analysis['warning']}")
