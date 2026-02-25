#!/usr/bin/env python3
"""
Query decomposition for aspect-based hierarchical search.

This script uses an LLM to break complex queries into discrete, searchable aspects.
Each aspect gets its own embedding for precise sentence-level matching.

Usage:
    python decompose_query.py "What NGS methods detect arboviruses in CSF and what are their sensitivity and turnaround times?"

Output:
    {
      "is_complex": true,
      "original_query": "...",
      "aspects": [
        {"name": "method", "question": "What NGS methods are used?", "category": "methodology"},
        {"name": "pathogen", "question": "What pathogens (arboviruses)?", "category": "target"},
        {"name": "specimen", "question": "What specimen type (CSF)?", "category": "sample"},
        {"name": "sensitivity", "question": "What is the sensitivity?", "category": "performance"},
        {"name": "turnaround_time", "question": "What is the turnaround time?", "category": "workflow"}
      ]
    }
"""

import argparse
import json
import sys
import os
from typing import Dict, List, Any
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# LLM model for decomposition
DECOMPOSITION_MODEL = "gpt-4o-mini"  # Fast and cheap for this task


DECOMPOSITION_PROMPT = """Analyze this scientific query about NGS diagnostics and identify distinct aspects that could be answered by separate sentences or facts.

Common aspect categories in NGS diagnostic literature:
- **methodology**: NGS method/modality (mNGS, targeted, amplicon, WGS, platforms like Illumina/MinION)
- **target**: Pathogen or target organism (bacteria, virus, fungus, parasite, specific species)
- **sample**: Specimen type (CSF, blood, tissue, respiratory, etc.)
- **performance**: Diagnostic metrics (sensitivity, specificity, PPV, NPV, accuracy)
- **workflow**: Operational metrics (turnaround time, cost, sample volume, hands-on time)
- **comparison**: Comparisons to other methods (vs culture, vs PCR, vs serology)
- **clinical_context**: Clinical setting or population (pre-antibiotic, pediatric, immunocompromised, severity)
- **validation**: Study design or validation approach (retrospective, prospective, sample size)

Query: {query}

First, determine if this is a simple query (single question) or complex (multiple aspects):
- Simple: "What is mNGS?" or "What pathogens cause meningitis?"
- Complex: "What NGS methods detect X and what is their sensitivity?" (multiple aspects)

For complex queries, break into discrete aspects. Each aspect should:
1. Be answerable by a single sentence or short fact
2. Have a clear category from the list above
3. Be phrased as a focused question
4. Not overlap with other aspects

Return JSON:
{{
  "is_complex": true/false,
  "reasoning": "Brief explanation of why this is simple or complex",
  "aspects": [
    {{
      "name": "short_identifier",
      "question": "Focused question for this aspect",
      "category": "one of the categories above",
      "keywords": ["key", "terms", "for", "this", "aspect"]
    }}
  ]
}}

For simple queries, return a single aspect.
For complex queries, return 2-6 aspects (don't over-decompose).

Examples:

Query: "What is metagenomic NGS?"
{{
  "is_complex": false,
  "reasoning": "Single definitional question",
  "aspects": [
    {{"name": "definition", "question": "What is metagenomic NGS?", "category": "methodology", "keywords": ["metagenomic", "mNGS", "definition"]}}
  ]
}}

Query: "What NGS methods detect arboviruses in CSF and what are their sensitivity and turnaround times?"
{{
  "is_complex": true,
  "reasoning": "Query asks about multiple aspects: method type, pathogen target, specimen, performance metrics (sensitivity), and workflow metrics (turnaround time)",
  "aspects": [
    {{"name": "method", "question": "What NGS methods are used for arbovirus detection?", "category": "methodology", "keywords": ["NGS", "method", "mNGS", "targeted", "sequencing"]}},
    {{"name": "pathogen", "question": "Detection of arboviruses", "category": "target", "keywords": ["arbovirus", "viral", "pathogen"]}},
    {{"name": "specimen", "question": "CSF specimen type", "category": "sample", "keywords": ["CSF", "cerebrospinal fluid", "specimen"]}},
    {{"name": "sensitivity", "question": "What is the diagnostic sensitivity?", "category": "performance", "keywords": ["sensitivity", "detection rate", "percent"]}},
    {{"name": "turnaround_time", "question": "What is the turnaround time?", "category": "workflow", "keywords": ["turnaround", "time", "hours", "days", "TAT"]}}
  ]
}}

Now analyze the user's query."""


def decompose_query(query: str, model: str = DECOMPOSITION_MODEL) -> Dict[str, Any]:
    """
    Use LLM to decompose a query into searchable aspects.

    Args:
        query: User's question
        model: OpenAI model to use

    Returns:
        Dictionary with is_complex flag and list of aspects
    """
    prompt = DECOMPOSITION_PROMPT.format(query=query)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are an expert at analyzing scientific queries about NGS diagnostics."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.3  # Lower temperature for more consistent decomposition
    )

    result = json.loads(response.choices[0].message.content)

    # Add original query to result
    result["original_query"] = query

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Decompose complex queries into searchable aspects"
    )
    parser.add_argument(
        "query",
        nargs="+",
        help="Query to decompose"
    )
    parser.add_argument(
        "--model",
        default=DECOMPOSITION_MODEL,
        help=f"OpenAI model to use (default: {DECOMPOSITION_MODEL})"
    )
    parser.add_argument(
        "--output",
        help="Output JSON file (if not specified, prints to stdout)"
    )

    args = parser.parse_args()
    query = " ".join(args.query)

    print(f"Decomposing query: {query}", file=sys.stderr)
    print(f"Using model: {args.model}", file=sys.stderr)

    # Decompose
    result = decompose_query(query, args.model)

    # Output
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2))

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Complexity: {'COMPLEX' if result['is_complex'] else 'SIMPLE'}", file=sys.stderr)
    print(f"Reasoning: {result['reasoning']}", file=sys.stderr)
    print(f"Aspects: {len(result['aspects'])}", file=sys.stderr)

    if result['is_complex']:
        print(f"\nAspect Breakdown:", file=sys.stderr)
        for i, aspect in enumerate(result['aspects'], 1):
            print(f"  {i}. [{aspect['category']}] {aspect['question']}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)


if __name__ == "__main__":
    main()
