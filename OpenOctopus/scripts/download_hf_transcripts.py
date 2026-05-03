#!/usr/bin/env python3
"""Download sp500_earnings_transcripts from Hugging Face and save as JSONL cache."""

import json
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Apply Zscaler / corporate proxy CA bundle if present, so the HF datasets
# library (which uses requests under the hood) can verify SSL.
_CERT_CANDIDATES = [
    PROJECT_ROOT / ".cache" / "zscaler_certs.pem",
    Path(os.environ.get("REQUESTS_CA_BUNDLE", "")),
    Path(os.environ.get("CURL_CA_BUNDLE", "")),
]
for _cert in _CERT_CANDIDATES:
    if _cert and _cert.exists() and _cert.stat().st_size > 0:
        os.environ.setdefault("REQUESTS_CA_BUNDLE", str(_cert))
        os.environ.setdefault("CURL_CA_BUNDLE", str(_cert))
        break


def download_transcripts(output_path: str | None = None) -> Path:
    """Download transcripts from HF and write JSONL cache file."""
    try:
        from datasets import load_dataset
    except ImportError:
        print("Installing 'datasets' library...")
        os.system(f"{sys.executable} -m pip install datasets --quiet")
        from datasets import load_dataset

    if output_path is None:
        from config import settings
        output_path = settings.HF_TRANSCRIPTS_PATH

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Detect corrupt/HTML files (e.g. Zscaler block pages saved as JSONL)
    if out.exists():
        with out.open("rb") as fh:
            header = fh.read(16)
        if header.startswith(b"<!") or header.startswith(b"<html"):
            print(f"Corrupt file detected (HTML response) at {out}. Removing and re-downloading.")
            out.unlink()
        else:
            line_count = sum(1 for _ in out.open())
            print(f"Cache already exists at {out} ({line_count} records). Use --force to re-download.")
            return out

    print(f"Downloading kurry/sp500_earnings_transcripts from Hugging Face...")
    ds = load_dataset("kurry/sp500_earnings_transcripts", split="train")
    print(f"Downloaded {len(ds)} records. Writing to {out}...")

    count = 0
    with out.open("w", encoding="utf-8") as fh:
        for record in ds:
            row = {
                "symbol": record.get("symbol", ""),
                "year": record.get("year"),
                "quarter": record.get("quarter"),
                "date": record.get("date", ""),
                "company_name": record.get("company_name", ""),
                "content": record.get("content", ""),
                "structured_content": record.get("structured_content", []),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            if count % 5000 == 0:
                print(f"  {count} records written...")

    print(f"Done. {count} records saved to {out}")
    return out


if __name__ == "__main__":
    force = "--force" in sys.argv
    from config import settings
    out_path = Path(settings.HF_TRANSCRIPTS_PATH)
    if force and out_path.exists():
        out_path.unlink()
    download_transcripts()
