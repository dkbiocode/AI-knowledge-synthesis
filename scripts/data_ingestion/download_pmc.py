"""
download_pmc.py

Read reference_index.json, extract all PMC IDs, and download the article
HTML from https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/ into a local
html/ directory.

Filenames are saved as {ref_id}_{PMCID}.html (e.g. B5_PMC2581791.html)
so they can be matched back to the reference index.

A download log (download_log.json) tracks status of each attempt so the
script is safe to rerun — already-downloaded files are skipped unless
--force is passed.

Usage:
  python download_pmc.py
  python download_pmc.py --force          # re-download everything
  python download_pmc.py --limit 10       # download first N only (for testing)
  python download_pmc.py --delay 2.0      # seconds between requests (default 1.5)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests


PMC_BASE_URL = "https://pmc.ncbi.nlm.nih.gov/articles"


def load_log(log_path: Path) -> dict:
    if log_path.exists():
        with open(log_path) as f:
            return json.load(f)
    return {}


def save_log(log_path: Path, log: dict):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refs", default="reference_index.json",
                        help="Reference index JSON (default: reference_index.json)")
    parser.add_argument("--outdir", default="html",
                        help="Output directory for HTML files (default: html/)")
    parser.add_argument("--log", default="download_log.json",
                        help="Download log file (default: download_log.json)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if file already exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only download first N articles (for testing)")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between requests (default: 1.5)")
    args = parser.parse_args()

    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    refs_path = script_dir / args.refs
    out_dir   = script_dir / args.outdir
    log_path  = script_dir / args.log

    if not refs_path.exists():
        sys.exit(f"Reference index not found: {refs_path}")

    out_dir.mkdir(exist_ok=True)

    with open(refs_path) as f:
        reference_index = json.load(f)

    # Collect entries that have a PMC ID
    to_download = [
        (ref_id, ref["pmc_id"], ref)
        for ref_id, ref in reference_index.items()
        if ref.get("pmc_id")
    ]

    # Sort by B-number (handle both "B5" and "B10-animals-14-01578" formats)
    def extract_b_number(ref_id: str) -> int:
        # Strip 'B' prefix and extract first numeric part
        try:
            stripped = ref_id.lstrip("B")
            # Handle formats like "10-animals-14-01578" by taking first number
            num_str = stripped.split("-")[0] if "-" in stripped else stripped
            return int(num_str)
        except (ValueError, IndexError):
            return 0

    to_download.sort(key=lambda x: extract_b_number(x[0]))

    if args.limit:
        to_download = to_download[:args.limit]

    log = load_log(log_path)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (research KB builder; contact: see repo)"
    })

    total   = len(to_download)
    skipped = 0
    success = 0
    failed  = 0

    print(f"PMC articles to download: {total}")
    print(f"Output directory: {out_dir}\n")

    for i, (ref_id, pmc_id, ref) in enumerate(to_download, 1):
        filename = f"{ref_id}_{pmc_id}.html"
        out_path = out_dir / filename
        log_key  = f"{ref_id}_{pmc_id}"

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
            "ref_id":    ref_id,
            "pmc_id":    pmc_id,
            "filename":  filename,
            "status":    status,
            "message":   msg,
            "timestamp": timestamp,
            "doi":       ref.get("doi"),
            "title":     ref.get("title"),
        }

        # Save log after each download so progress is preserved on interruption
        save_log(log_path, log)

        if i < total:
            time.sleep(args.delay)

    print(f"\nDone.  Success: {success}  Skipped: {skipped}  Failed: {failed}")
    print(f"Log saved to {log_path}")


if __name__ == "__main__":
    main()
