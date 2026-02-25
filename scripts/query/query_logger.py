#!/usr/bin/env python3
"""
Query logging utilities for web app integration.

This module provides functions to:
1. Log user queries with embeddings
2. Log decomposed sub-queries with parent references
3. Find similar past queries
4. Retrieve query history

Usage:
    from query_logger import log_query, log_decomposed_query, find_similar_queries

    # Log a simple query
    query_id = log_query("What is mNGS?", embedding, is_complex=False)

    # Log a complex query with aspects
    parent_id = log_decomposed_query(
        parent_query="What NGS methods detect arboviruses...",
        parent_embedding=<embedding>,
        aspects=[
            {"question": "What NGS methods?", "embedding": <emb>, "category": "methodology", ...},
            ...
        ]
    )

    # Find similar past queries
    similar = find_similar_queries(query_embedding, limit=5)
"""

import psycopg2
import os
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

# Add parent directory to path for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from config.db_config import get_connection


def log_query(
    cursor,
    query_text: str,
    embedding: List[float],
    is_complex: bool = False,
    category: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    parent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> int:
    """
    Log a single query to the database.

    Args:
        cursor: Database cursor
        query_text: The query text
        embedding: Query embedding vector
        is_complex: Whether this is a complex query
        category: Category for sub-queries (methodology, target, etc.)
        metadata: Additional metadata as dict
        parent_id: Parent query ID (for sub-queries)
        user_id: Optional user identifier
        session_id: Optional session identifier

    Returns:
        query_id: The ID of the inserted query
    """
    metadata_json = json.dumps(metadata) if metadata else None

    cursor.execute("""
        INSERT INTO query_log (
            query_text,
            embedding,
            is_complex,
            category,
            metadata,
            parent_id,
            user_id,
            session_id
        )
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        RETURNING id
    """, (
        query_text,
        embedding,
        is_complex,
        category,
        metadata_json,
        parent_id,
        user_id,
        session_id
    ))

    query_id = cursor.fetchone()[0]
    return query_id


def log_decomposed_query(
    cursor,
    parent_query: str,
    parent_embedding: List[float],
    aspects: List[Dict[str, Any]],
    reasoning: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> int:
    """
    Log a decomposed query (parent + aspects) to the database.

    Args:
        cursor: Database cursor
        parent_query: The original complex query
        parent_embedding: Embedding for the full query
        aspects: List of aspect dicts with keys:
            - question (str): Aspect question
            - embedding (List[float]): Aspect embedding
            - category (str): methodology, target, sample, etc.
            - keywords (List[str]): Optional keywords
        reasoning: Decomposition reasoning
        user_id: Optional user identifier
        session_id: Optional session identifier

    Returns:
        parent_id: The ID of the parent query
    """
    # Log parent query
    parent_metadata = {
        "reasoning": reasoning,
        "num_aspects": len(aspects),
        "aspect_categories": [a.get("category") for a in aspects]
    }

    parent_id = log_query(
        cursor,
        query_text=parent_query,
        embedding=parent_embedding,
        is_complex=True,
        metadata=parent_metadata,
        user_id=user_id,
        session_id=session_id
    )

    # Log sub-queries (aspects)
    for aspect in aspects:
        aspect_metadata = {
            "keywords": aspect.get("keywords", []),
            "name": aspect.get("name", "")
        }

        log_query(
            cursor,
            query_text=aspect["question"],
            embedding=aspect["embedding"],
            is_complex=False,
            category=aspect.get("category"),
            metadata=aspect_metadata,
            parent_id=parent_id,
            user_id=user_id,
            session_id=session_id
        )

    return parent_id


def find_similar_queries(
    cursor,
    query_embedding: List[float],
    limit: int = 10,
    similarity_threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """
    Find similar past queries using vector similarity.

    Args:
        cursor: Database cursor
        query_embedding: Embedding of the query to match
        limit: Maximum number of results
        similarity_threshold: Minimum similarity score

    Returns:
        List of dicts with query_id, query_text, similarity, created_at
    """
    cursor.execute("""
        SELECT
            id,
            query_text,
            created_at,
            is_complex,
            metadata,
            1 - (embedding <=> %s::vector) AS similarity
        FROM query_log
        WHERE parent_id IS NULL  -- Only search parent queries
          AND embedding IS NOT NULL
          AND 1 - (embedding <=> %s::vector) >= %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (query_embedding, query_embedding, similarity_threshold, query_embedding, limit))

    results = []
    for row in cursor.fetchall():
        results.append({
            "query_id": row[0],
            "query_text": row[1],
            "created_at": row[2],
            "is_complex": row[3],
            "metadata": row[4],
            "similarity": row[5]
        })

    return results


def get_query_with_aspects(cursor, query_id: int) -> Dict[str, Any]:
    """
    Retrieve a query with all its sub-queries/aspects.

    Args:
        cursor: Database cursor
        query_id: Parent query ID

    Returns:
        Dict with parent query and list of aspects
    """
    cursor.execute("""
        SELECT
            parent.id,
            parent.query_text,
            parent.is_complex,
            parent.metadata,
            parent.created_at,
            json_agg(
                json_build_object(
                    'id', child.id,
                    'question', child.query_text,
                    'category', child.category,
                    'metadata', child.metadata
                ) ORDER BY child.id
            ) FILTER (WHERE child.id IS NOT NULL) AS aspects
        FROM query_log parent
        LEFT JOIN query_log child ON child.parent_id = parent.id
        WHERE parent.id = %s
        GROUP BY parent.id, parent.query_text, parent.is_complex, parent.metadata, parent.created_at
    """, (query_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "query_id": row[0],
        "query_text": row[1],
        "is_complex": row[2],
        "metadata": row[3],
        "created_at": row[4],
        "aspects": row[5] or []
    }


def get_recent_queries(
    cursor,
    limit: int = 20,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get recent queries (parent queries only).

    Args:
        cursor: Database cursor
        limit: Maximum number of results
        user_id: Filter by user_id
        session_id: Filter by session_id

    Returns:
        List of recent queries
    """
    filters = ["parent_id IS NULL"]
    params = []

    if user_id:
        filters.append("user_id = %s")
        params.append(user_id)

    if session_id:
        filters.append("session_id = %s")
        params.append(session_id)

    params.append(limit)

    cursor.execute(f"""
        SELECT
            id,
            query_text,
            is_complex,
            created_at,
            metadata
        FROM query_log
        WHERE {" AND ".join(filters)}
        ORDER BY created_at DESC
        LIMIT %s
    """, params)

    results = []
    for row in cursor.fetchall():
        results.append({
            "query_id": row[0],
            "query_text": row[1],
            "is_complex": row[2],
            "created_at": row[3],
            "metadata": row[4]
        })

    return results


# Example usage
if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from decompose_query import decompose_query
    from openai import OpenAI
    import os

    # Initialize
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    conn = get_connection()  # Uses default 'local' config
    cursor = conn.cursor()

    # Example: Log a complex query with decomposition
    query = "What NGS methods detect arboviruses in CSF and what are their sensitivity?"

    # Decompose
    decomposition = decompose_query(query)

    # Generate embeddings
    texts = [query] + [aspect["question"] for aspect in decomposition["aspects"]]
    response = client.embeddings.create(model="text-embedding-3-small", input=texts)
    embeddings = [item.embedding for item in response.data]

    # Prepare aspects with embeddings
    aspects = [
        {
            **aspect,
            "embedding": embeddings[i+1]
        }
        for i, aspect in enumerate(decomposition["aspects"])
    ]

    # Log to database
    parent_id = log_decomposed_query(
        cursor,
        parent_query=query,
        parent_embedding=embeddings[0],
        aspects=aspects,
        reasoning=decomposition["reasoning"],
        session_id="demo_session"
    )

    conn.commit()

    print(f"Logged query with ID: {parent_id}")

    # Retrieve it back
    result = get_query_with_aspects(cursor, parent_id)
    print(f"\nRetrieved query:")
    print(f"  Query: {result['query_text']}")
    print(f"  Aspects: {len(result['aspects'])}")
    for aspect in result['aspects']:
        print(f"    - [{aspect['category']}] {aspect['question']}")

    cursor.close()
    conn.close()
