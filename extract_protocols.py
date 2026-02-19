"""
extract_protocols.py

Extract NGS diagnostic protocol mentions from all chunks in the database using
structured LLM extraction.

For each chunk, the LLM identifies:
  - Protocol identity (modality, pathogen, specimen, platform, etc.)
  - Typed verbatim excerpts (method, performance, limitations, biology, obstacles)
  - Veterinary transferability assessment

Populates:
  - protocols table (canonical protocol records)
  - protocol_sources table (chunk → protocol many-to-many with excerpts)

Usage:
  conda activate openai

  # Extract from all chunks (review + papers):
  python extract_protocols.py

  # Dry-run (print first 3 extractions without writing to DB):
  python extract_protocols.py --dry-run --limit 3

  # Extract from papers only:
  python extract_protocols.py --source papers

  # Extract from a specific paper:
  python extract_protocols.py --paper-id 5

Connection env vars: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
"""

import argparse
import json
import os
import sys
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Database connection (same pattern as other scripts)
# ---------------------------------------------------------------------------

def get_conn(dbname: str):
    params = {
        "host":     os.environ.get("PGHOST", "localhost"),
        "port":     int(os.environ.get("PGPORT", 5432)),
        "user":     os.environ.get("PGUSER", os.environ.get("USER", "")),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname":   dbname,
    }
    return psycopg2.connect(**{k: v for k, v in params.items() if v != ""})


# ---------------------------------------------------------------------------
# JSON Schema for structured extraction
# ---------------------------------------------------------------------------

PROTOCOL_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "protocols": {
            "type": "array",
            "description": "List of distinct NGS/molecular diagnostic protocols mentioned in this chunk",
            "items": {
                "type": "object",
                "properties": {
                    # Identity
                    "ngs_modality": {
                        "type": ["string", "null"],
                        "enum": ["mNGS", "targeted_NGS", "WGS", "amplicon_NGS", "panel_NGS", "other", None],
                        "description": "NGS modality: mNGS (metagenomic), targeted_NGS (gene panels), WGS (whole genome), amplicon_NGS (PCR+sequencing), panel_NGS (custom capture), other (hybrid/novel NGS approaches)"
                    },
                    "pathogen_class": {
                        "type": ["string", "null"],
                        "enum": ["arbovirus", "virus", "bacteria", "fungus", "parasite", "pan-pathogen", "other", None]
                    },
                    "clinical_context": {
                        "type": ["string", "null"],
                        "enum": ["CNS", "sepsis", "respiratory", "zoonosis", "surveillance", "other", None]
                    },
                    "specimen_type": {
                        "type": ["string", "null"],
                        "enum": ["CSF", "serum", "blood", "BALF", "tissue", "swab", "other", None]
                    },
                    "platform": {
                        "type": ["string", "null"],
                        "description": "Sequencing platform: Illumina, Nanopore, BGI, Ion Torrent. Leave null (not the string 'null') if not stated."
                    },
                    "bioinformatics_pipeline": {
                        "type": ["string", "null"],
                        "description": "Analysis pipeline: BWA, Kraken, CZID, custom. Leave null (not the string 'null') if not stated."
                    },

                    # Performance (extract only if explicitly stated)
                    "sensitivity": {
                        "type": ["number", "null"],
                        "description": "Sensitivity in percent (0-100) if stated, else null"
                    },
                    "specificity": {
                        "type": ["number", "null"],
                        "description": "Specificity in percent (0-100) if stated, else null"
                    },
                    "turnaround_hours": {
                        "type": ["number", "null"],
                        "description": "Turnaround time in hours if stated, else null"
                    },

                    # Typed verbatim excerpts — EXACT QUOTES from the source text
                    "excerpt_method": {
                        "type": ["string", "null"],
                        "description": "Verbatim sentence(s) describing what the protocol does"
                    },
                    "excerpt_performance": {
                        "type": ["string", "null"],
                        "description": "Verbatim sentence(s) stating sensitivity/specificity/TAT"
                    },
                    "excerpt_limitations": {
                        "type": ["string", "null"],
                        "description": "Verbatim sentence(s) stating limitations of the method"
                    },
                    "excerpt_biology": {
                        "type": ["string", "null"],
                        "description": "Verbatim sentence(s) about biological constraints (pathogen biology, host factors)"
                    },
                    "excerpt_obstacles": {
                        "type": ["string", "null"],
                        "description": "Verbatim sentence(s) about logistical/regulatory/cost obstacles"
                    },
                    "excerpt_transferability": {
                        "type": ["string", "null"],
                        "description": "Verbatim sentence(s) about generalizability or applicability to other contexts"
                    },

                    # Veterinary transferability assessment (LLM judgment)
                    "vet_transferability_score": {
                        "type": ["integer", "null"],
                        "enum": [0, 1, 2, 3, None],
                        "description": "0=blocked, 1=needs modification, 2=likely feasible, 3=directly applicable, null=insufficient info"
                    },
                    "vet_obstacle_summary": {
                        "type": ["string", "null"],
                        "description": "One-sentence synthesis of obstacles for veterinary translation"
                    },

                    # Mention type
                    "mention_type": {
                        "type": "string",
                        "enum": ["defines", "uses", "validates", "critiques", "adapts", "citation_only"],
                        "description": "Role of this chunk: defines=contains full protocol, uses=applies it, validates=reports data, critiques=identifies problems, adapts=modifies for new context, citation_only=just cites it"
                    }
                },
                "required": [
                    "ngs_modality", "pathogen_class", "clinical_context", "specimen_type",
                    "platform", "bioinformatics_pipeline", "sensitivity", "specificity",
                    "turnaround_hours", "excerpt_method", "excerpt_performance",
                    "excerpt_limitations", "excerpt_biology", "excerpt_obstacles",
                    "excerpt_transferability", "vet_transferability_score",
                    "vet_obstacle_summary", "mention_type"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["protocols"],
    "additionalProperties": False
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert in infectious disease diagnostics and metagenomic sequencing (mNGS).

Your task: extract structured information about NEXT-GENERATION SEQUENCING (NGS) diagnostic protocols from the provided text chunk.

**CRITICAL: ONLY extract NGS-based protocols. This includes:**
- mNGS (metagenomic NGS)
- Targeted NGS (panel-based, amplicon-based sequencing)
- Whole genome sequencing (WGS)
- Any protocol involving Illumina, Nanopore, Ion Torrent, BGI, or other NGS platforms

**DO NOT extract:**
- Conventional PCR or RT-PCR (unless it's part of NGS library preparation)
- Serology (ELISA, neutralization tests, antibody assays)
- Culture-based methods
- Antigen detection
- Other non-sequencing diagnostics

**Edge cases to INCLUDE:**
- Protocols that use PCR for target enrichment before NGS
- Hybrid approaches combining amplification with sequencing
- Bioinformatics pipelines for NGS data analysis

For each distinct NGS diagnostic protocol mentioned:
1. Identify the protocol type (mNGS, targeted NGS, RT-PCR, serology, etc.)
2. Extract VERBATIM sentences that describe:
   - What the method does
   - Performance metrics (sensitivity, specificity, turnaround time) if stated
   - Stated limitations
   - Biological constraints (pathogen biology, sample timing, host factors)
   - Logistical or regulatory obstacles
   - Generalizability or applicability statements
3. Assess veterinary transferability:
   - Score 0-3: 0=blocked by fundamental constraints, 1=requires significant modification, 2=likely feasible with minor changes, 3=directly applicable
   - Write a one-sentence summary of veterinary obstacles

CRITICAL RULES:
- All excerpt fields must be EXACT QUOTES from the source text — copy-paste verbatim
- If a field is not mentioned in the text, use JSON null (not the string "null")
- If multiple protocols are mentioned, create separate entries for each
- Use "mention_type" to classify what this chunk does: defines (contains full protocol detail), uses (applies the protocol), validates (reports performance data), critiques (identifies limitations), adapts (modifies for new context), citation_only (just cites another source)
- For veterinary transferability: consider specimen collection feasibility, sample volume requirements, species differences in pathogen load, cost, and infrastructure
- For enum fields where the text doesn't match a predefined value, choose "other" or null as appropriate

Output valid JSON matching the schema exactly. Use JSON null, not string "null".\
"""


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

def extract_protocols_from_chunk(chunk_text: str, chunk_heading: str, model: str = "gpt-4o-mini") -> dict:
    """
    Call OpenAI with structured output to extract protocols from a chunk.

    Args:
        chunk_text: The plain text of the chunk
        chunk_heading: The chunk heading (for context)
        model: OpenAI model to use

    Returns:
        Dict with "protocols" key (list of protocol dicts matching schema)
    """
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package not found. Run: conda activate openai")

    client = OpenAI()  # reads OPENAI_API_KEY

    user_message = f"Section: {chunk_heading}\n\nText:\n{chunk_text}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "protocol_extraction",
                "strict": True,
                "schema": PROTOCOL_EXTRACTION_SCHEMA
            }
        },
        temperature=0.1,  # low temp for consistency
    )

    result = json.loads(response.choices[0].message.content)
    return result


# ---------------------------------------------------------------------------
# Database insertion
# ---------------------------------------------------------------------------

def find_or_create_protocol(cur, protocol_data: dict) -> int:
    """
    Find an existing protocol matching identity fields, or create a new one.

    Identity fields: ngs_modality, pathogen_class, clinical_context,
                     specimen_type, platform, bioinformatics_pipeline

    Returns: protocol_id
    """
    # Try to find existing by identity match
    cur.execute("""
        SELECT id FROM protocols
        WHERE ngs_modality = %s
          AND pathogen_class IS NOT DISTINCT FROM %s
          AND clinical_context IS NOT DISTINCT FROM %s
          AND specimen_type IS NOT DISTINCT FROM %s
          AND platform IS NOT DISTINCT FROM %s
          AND bioinformatics_pipeline IS NOT DISTINCT FROM %s
        LIMIT 1
    """, (
        protocol_data["ngs_modality"],
        protocol_data.get("pathogen_class"),
        protocol_data.get("clinical_context"),
        protocol_data.get("specimen_type"),
        protocol_data.get("platform"),
        protocol_data.get("bioinformatics_pipeline"),
    ))
    row = cur.fetchone()
    if row:
        return row["id"]

    # Create new protocol
    cur.execute("""
        INSERT INTO protocols
            (ngs_modality, pathogen_class, clinical_context, specimen_type,
             platform, bioinformatics_pipeline,
             sensitivity, specificity, turnaround_hours,
             excerpt_method, excerpt_performance, excerpt_limitations,
             excerpt_biology, excerpt_obstacles, excerpt_transferability,
             vet_transferability_score, vet_obstacle_summary)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        protocol_data["ngs_modality"],
        protocol_data.get("pathogen_class"),
        protocol_data.get("clinical_context"),
        protocol_data.get("specimen_type"),
        protocol_data.get("platform"),
        protocol_data.get("bioinformatics_pipeline"),
        protocol_data.get("sensitivity"),
        protocol_data.get("specificity"),
        protocol_data.get("turnaround_hours"),
        protocol_data.get("excerpt_method"),
        protocol_data.get("excerpt_performance"),
        protocol_data.get("excerpt_limitations"),
        protocol_data.get("excerpt_biology"),
        protocol_data.get("excerpt_obstacles"),
        protocol_data.get("excerpt_transferability"),
        protocol_data.get("vet_transferability_score"),
        protocol_data.get("vet_obstacle_summary"),
    ))
    return cur.fetchone()["id"]


def link_protocol_to_chunk(cur, protocol_id: int, chunk_id: int,
                            chunk_type: str, paper_id: Optional[int],
                            protocol_data: dict):
    """
    Insert a protocol_sources row linking protocol → chunk.

    chunk_type: 'review' | 'paper'
    """
    review_chunk_id = chunk_id if chunk_type == "review" else None
    paper_chunk_id = chunk_id if chunk_type == "paper" else None

    # Pick the best excerpt to store (prefer method, then limitations, then any non-null)
    verbatim_excerpt = (
        protocol_data.get("excerpt_method") or
        protocol_data.get("excerpt_limitations") or
        protocol_data.get("excerpt_performance") or
        protocol_data.get("excerpt_biology") or
        protocol_data.get("excerpt_obstacles") or
        protocol_data.get("excerpt_transferability")
    )

    # Determine excerpt_type
    excerpt_type = None
    if protocol_data.get("excerpt_method"):
        excerpt_type = "method"
    elif protocol_data.get("excerpt_limitations"):
        excerpt_type = "limitation"
    elif protocol_data.get("excerpt_performance"):
        excerpt_type = "performance"
    elif protocol_data.get("excerpt_biology"):
        excerpt_type = "biology"
    elif protocol_data.get("excerpt_obstacles"):
        excerpt_type = "obstacle"

    # Use INSERT ... ON CONFLICT with conditional constraint
    # The unique constraint depends on which chunk type is being inserted
    if review_chunk_id:
        cur.execute("""
            INSERT INTO protocol_sources
                (protocol_id, review_chunk_id, paper_chunk_id, paper_id,
                 mention_type, verbatim_excerpt, excerpt_type)
            VALUES (%s, %s, NULL, %s, %s, %s, %s)
            ON CONFLICT (protocol_id, review_chunk_id) DO NOTHING
        """, (
            protocol_id,
            review_chunk_id,
            paper_id,
            protocol_data["mention_type"],
            verbatim_excerpt,
            excerpt_type,
        ))
    else:
        cur.execute("""
            INSERT INTO protocol_sources
                (protocol_id, review_chunk_id, paper_chunk_id, paper_id,
                 mention_type, verbatim_excerpt, excerpt_type)
            VALUES (%s, NULL, %s, %s, %s, %s, %s)
            ON CONFLICT (protocol_id, paper_chunk_id) DO NOTHING
        """, (
            protocol_id,
            paper_chunk_id,
            paper_id,
            protocol_data["mention_type"],
            verbatim_excerpt,
            excerpt_type,
        ))


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def process_chunks(cur, chunks: list[dict], chunk_type: str, model: str, dry_run: bool):
    """
    Process a batch of chunks through LLM extraction.

    chunk_type: 'review' | 'paper'
    """
    total_protocols = 0

    for i, chunk in enumerate(chunks, 1):
        chunk_id = chunk["id"]
        heading = chunk["heading"] or "(no heading)"
        text = chunk["text"]
        paper_id = chunk.get("paper_id")

        print(f"  [{i}/{len(chunks)}] {chunk_type} chunk {chunk_id}: {heading[:60]}")

        if not text or len(text) < 50:
            print("      → skipped (too short)")
            continue

        try:
            result = extract_protocols_from_chunk(text, heading, model)
            protocols_found = result.get("protocols", [])

            if not protocols_found:
                print("      → no protocols found")
                continue

            print(f"      → {len(protocols_found)} protocol(s) extracted")

            if dry_run:
                print(json.dumps(protocols_found, indent=2))
                continue

            # Insert each protocol
            for p in protocols_found:
                try:
                    protocol_id = find_or_create_protocol(cur, p)
                    link_protocol_to_chunk(cur, protocol_id, chunk_id, chunk_type, paper_id, p)
                    total_protocols += 1
                except Exception as e:
                    print(f"      → ERROR inserting protocol: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        except Exception as e:
            print(f"      → ERROR extracting: {e}")
            continue

    return total_protocols


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dbname", default="mngs_kb",
                        help="Database name (default: mngs_kb)")
    parser.add_argument("--model", default="gpt-4o-mini",
                        help="OpenAI model for extraction (default: gpt-4o-mini)")
    parser.add_argument("--source", default="both",
                        choices=["both", "review", "papers"],
                        help="Extract from review chunks, paper chunks, or both (default: both)")
    parser.add_argument("--paper-id", type=int, default=None,
                        help="Extract from a single paper only")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of chunks to process (for testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print extractions without writing to DB")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY environment variable not set.")

    print(f"Connecting to database '{args.dbname}' ...")
    conn = get_conn(args.dbname)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        total_protocols = 0

        # Fetch review chunks
        if args.source in ["both", "review"]:
            print("\nFetching review chunks ...")
            cur.execute("""
                SELECT id, heading, text, NULL as paper_id
                FROM review_chunks
                WHERE text IS NOT NULL AND LENGTH(text) > 50
                ORDER BY id
                LIMIT %s
            """, (args.limit,))
            review_chunks = cur.fetchall()
            print(f"  {len(review_chunks)} review chunks to process")

            if review_chunks:
                total_protocols += process_chunks(cur, review_chunks, "review", args.model, args.dry_run)

        # Fetch paper chunks
        if args.source in ["both", "papers"]:
            print("\nFetching paper chunks ...")
            where_clause = "WHERE pc.text IS NOT NULL AND LENGTH(pc.text) > 50"
            if args.paper_id:
                where_clause += f" AND pc.paper_id = {args.paper_id}"

            cur.execute(f"""
                SELECT pc.id, pc.heading, pc.text, pc.paper_id
                FROM paper_chunks pc
                {where_clause}
                ORDER BY pc.paper_id, pc.id
                LIMIT %s
            """, (args.limit,))
            paper_chunks = cur.fetchall()
            print(f"  {len(paper_chunks)} paper chunks to process")

            if paper_chunks:
                total_protocols += process_chunks(cur, paper_chunks, "paper", args.model, args.dry_run)

        if not args.dry_run:
            conn.commit()
            print(f"\n✓ Extraction complete. {total_protocols} protocol-chunk links created.")

            # Summary
            cur.execute("SELECT COUNT(*) FROM protocols")
            row = cur.fetchone()
            print(f"  Total protocols in DB: {row['count'] if row else 0}")
            cur.execute("SELECT COUNT(*) FROM protocol_sources")
            row = cur.fetchone()
            print(f"  Total protocol_sources: {row['count'] if row else 0}")
        else:
            print(f"\n--dry-run: no database changes made.")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
