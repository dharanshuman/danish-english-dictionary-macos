#!/usr/bin/env python3
"""Download all data sources into data/raw/. Safe to run again: it skips
files that are already downloaded.

Usage: python3 scripts/fetch_data.py
"""
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

FILES = {
    "kaikki.org-dictionary-Danish.jsonl": "kaikki",
    "freedict-dan-eng-0.3.1.stardict.tar.xz": "freedict_dan_eng",
    "freedict-eng-dan-0.1.0.stardict.tar.xz": "freedict_eng_dan",
    "cor1.5.1.0.tsv": "cor",
    "da_50k.txt": "frequency",
}


def main():
    config = json.loads((ROOT / "config.json").read_text())
    RAW.mkdir(parents=True, exist_ok=True)
    for filename, key in FILES.items():
        dest = RAW / filename
        url = config["sources"][key]["url"]
        if dest.exists() and dest.stat().st_size > 0:
            print(f"already have {filename} ({dest.stat().st_size:,} bytes) - skipping")
            continue
        print(f"downloading {url} ...")
        with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
        print(f"  saved {filename} ({dest.stat().st_size:,} bytes)")
    print("done.")


if __name__ == "__main__":
    sys.exit(main())
