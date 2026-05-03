#!/usr/bin/env python3
"""
Convert a Parquet file from the kurry/sp500_earnings_transcripts HuggingFace dataset
into the JSONL format expected by hf_cache.py.

Usage:
    python scripts/convert_parquet_to_jsonl.py [--input PATH] [--output PATH]

Default input:  .cache/hf_transcripts/part-0.parquet
Default output: .cache/hf_transcripts/sp500_earnings_transcripts.jsonl

To obtain the parquet file on a machine without Zscaler:
    python -c "
    from datasets import load_dataset
    ds = load_dataset('kurry/sp500_earnings_transcripts', split='train')
    ds.to_parquet('part-0.parquet')
    "
Then copy part-0.parquet to .cache/hf_transcripts/ and run this script.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _detect_corrupt(path: Path) -> bool:
    """Return True if file is an HTML block page (Zscaler/proxy error)."""
    with path.open("rb") as fh:
        header = fh.read(16)
    return header.startswith(b"<!") or header.startswith(b"<html") or header.startswith(b"<!D")


def convert(input_path: Path, output_path: Path) -> int:
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        print()
        print("To download the dataset on a machine without Zscaler, run:")
        print("  pip install datasets pyarrow")
        print("  python -c \"from datasets import load_dataset; ds = load_dataset('kurry/sp500_earnings_transcripts', split='train'); ds.to_parquet('part-0.parquet')\"")
        print("Then copy part-0.parquet here and re-run this script.")
        return 0

    if _detect_corrupt(input_path):
        print(f"ERROR: {input_path} appears to be an HTML block page (Zscaler proxy intercept).")
        print("The file is not a valid Parquet file. Please download it on a machine without the corporate proxy.")
        return 0

    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("Installing pyarrow...")
        import os
        os.system(f"{sys.executable} -m pip install pyarrow --quiet")
        import pyarrow.parquet as pq

    print(f"Reading {input_path} ...")
    table = pq.read_table(input_path)
    df = table.to_pydict()
    n = len(df.get("symbol", []))
    print(f"  {n} records found. Columns: {list(df.keys())}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove stale .idx.json if it exists
    idx_path = output_path.with_suffix(".idx.json")
    if idx_path.exists():
        idx_path.unlink()
        print(f"  Removed stale index: {idx_path}")

    print(f"Writing JSONL to {output_path} ...")
    count = 0
    with output_path.open("w", encoding="utf-8") as fh:
        for i in range(n):
            row = {
                "symbol": str(df.get("symbol", [""])[i] or ""),
                "year": df.get("year", [None])[i],
                "quarter": df.get("quarter", [None])[i],
                "date": str(df.get("date", [""])[i] or ""),
                "company_name": str(df.get("company_name", [""])[i] or ""),
                "content": str(df.get("content", [""])[i] or ""),
                "structured_content": df.get("structured_content", [[]])[i] or [],
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            if count % 5000 == 0:
                print(f"  {count}/{n} records written...")

    print(f"Done. {count} records saved to {output_path}")
    return count


def main() -> None:
    from config import settings

    parser = argparse.ArgumentParser(description="Convert HF Parquet to JSONL cache")
    parser.add_argument("--input", default=None, help="Path to part-0.parquet")
    parser.add_argument("--output", default=settings.HF_TRANSCRIPTS_PATH, help="Output JSONL path")
    args = parser.parse_args()

    default_parquet = Path(settings.HF_TRANSCRIPTS_PATH).parent / "part-0.parquet"
    input_path = Path(args.input) if args.input else default_parquet
    output_path = Path(args.output)

    count = convert(input_path, output_path)
    if count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
