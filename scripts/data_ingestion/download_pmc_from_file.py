"""
download_pmc_from_file.py

Download PMC articles from a citations JSON file produced by:
  - add_pmc_review_article.py
  - export_citations.py

Reads a reference_index.json file containing citation metadata and downloads
HTML files for all entries with PMC IDs.

Maintains a download log to track status and avoid re-downloading.

Usage:
  # Download from citations file
  python download_pmc_from_file.py --input PMC11171117_references.json \\
    --outdir html/vet

  # Download with custom log file
  python download_pmc_from_file.py --input vet_refs.json \\
    --outdir html/vet --log vet_download.json

  # Force re-download everything
  python download_pmc_from_file.py --input refs.json --outdir html --force

  # Download first 10 only (testing)
  python download_pmc_from_file.py --input refs.json --outdir html --limit 10

  # Slower download rate (polite crawling)
  python download_pmc_from_file.py --input refs.json --outdir html --delay 3.0
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests


PMC_BASE_URL = "https://pmc.ncbi.nlm.nih.gov/articles"


def load_log(log_path: Path) -> dict:
    """Load download log if it exists."""
    if log_path.exists():
        with open(log_path) as f:
            return json.load(f)
    return {}


def save_log(log_path: Path, log: dict):
    """Save download log."""
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)


def download_article(pmc_id: str, out_path: Path, session: requests.Session) -> tuple[bool, str]:
    """
    Download the PMC article HTML. Returns (success, message).
    """
    url = f"{PMC_BASE_URL}/{pmc_id}/"
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            out_path.write_bytes(response.content)
            size_kb = len(response.content) // 1024
            return True, f"OK ({size_kb} KB)"
        else:
            return False, f"HTTP {response.status_code}"
    except requests.RequestException as e:
        return False, str(e)


def extract_b_number(ref_id: str) -> int:
    """Extract numeric part from ref_id for sorting (e.g., 'B5' -> 5)."""
    try:
        stripped = ref_id.lstrip("BR")  # Handle both B and R prefixes
        num_str = stripped.split("-")[0] if "-" in stripped else stripped
        return int(num_str)
    except (ValueError, IndexError):
        return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--input", required=True,
        help="Input citations JSON file (from add_pmc_review_article.py or export_citations.py)"
    )
    parser.add_argument(
        "--outdir", required=True,
        help="Output directory for HTML files"
    )
    parser.add_argument(
        "--log",
        help="Download log file (default: <outdir>/download_log.json)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download even if file already exists"
    )
    parser.add_argument(
        "--limit", type=int,
        help="Only download first N articles (for testing)"
    )
    parser.add_argument(
        "--delay", type=float, default=1.5,
        help="Seconds between requests (default: 1.5)"
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = script_dir / input_path

    out_dir = Path(args.outdir)
    if not out_dir.is_absolute():
        out_dir = script_dir / out_dir

    if not input_path.exists():
        sys.exit(f"Error: Input file not found: {input_path}")

    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load citations
    print(f"Loading citations from {input_path}...")
    with open(input_path) as f:
        reference_index = json.load(f)

    # Collect entries with PMC IDs
    to_download = []
    for ref_id, ref in reference_index.items():
        pmc_id = ref.get("pmc_id")
        if pmc_id:
            to_download.append((ref_id, pmc_id, ref))

    if not to_download:
        sys.exit("No citations with PMC IDs found in input file")

    # Sort by reference ID
    to_download.sort(key=lambda x: extract_b_number(x[0]))

    # Apply limit
    if args.limit:
        to_download = to_download[:args.limit]

    # Setup log
    if args.log:
        log_path = Path(args.log)
        if not log_path.is_absolute():
            log_path = script_dir / log_path
    else:
        log_path = out_dir / "download_log.json"

    log = load_log(log_path)

    # Setup HTTP session
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (research KB builder; contact: see repo)"
    })

    # Download
    total = len(to_download)
    skipped = 0
    success = 0
    failed = 0

    print(f"PMC articles to download: {total}")
    print(f"Output directory: {out_dir}")
    print(f"Download log: {log_path}\n")

    for i, (ref_id, pmc_id, ref) in enumerate(to_download, 1):
        filename = f"{ref_id}_{pmc_id}.html"
        out_path = out_dir / filename
        log_key = f"{ref_id}_{pmc_id}"

        # Skip if already downloaded successfully
        if not args.force and log.get(log_key, {}).get("status") == "ok":
            print(f"  [{i:3}/{total}] SKIP  {ref_id} {pmc_id}  (already downloaded)")
            skipped += 1
            continue

        # Short citation for display
        cite_short = (ref.get("title") or ref.get("cite_text") or "")[:50]

        ok, msg = download_article(pmc_id, out_path, session)

        timestamp = datetime.now().isoformat()
        if ok:
            success += 1
            status = "ok"
            print(f"  [{i:3}/{total}] OK    {ref_id} {pmc_id}  {msg}  {cite_short}")
        else:
            failed += 1
            status = "error"
            print(f"  [{i:3}/{total}] FAIL  {ref_id} {pmc_id}  {msg}  {cite_short}")

        log[log_key] = {
            "ref_id": ref_id,
            "pmc_id": pmc_id,
            "filename": filename,
            "status": status,
            "message": msg,
            "timestamp": timestamp,
            "doi": ref.get("doi"),
            "title": ref.get("title"),
        }

        # Save log after each download
        save_log(log_path, log)

        # Rate limiting
        if i < total:
            time.sleep(args.delay)

    print(f"\n✓ Done")
    print(f"  Success: {success}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Log saved to {log_path}")

    # Suggest next step
    if success > 0:
        print(f"\nNext step - add downloaded papers to database:")
        print(f"  # Process each downloaded file:")
        print(f"  for file in {out_dir}/*.html; do")
        print(f"    python add_pmc_article.py --html \"$file\" --domain <medical|veterinary>")
        print(f"  done")
        print(f"\n  # Or use a loop in your shell script")


if __name__ == "__main__":
    main()
