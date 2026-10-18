#!/usr/bin/env python3
"""Download all data sources into data/raw/.

By default it downloads the pinned snapshot (each source's pinned_url in
config.json, a GitHub release holding exact copies) and checks every file
against its sha256, so every build sees the same data that
data/curated/fixes.json was written for. Files already present with the
right checksum are kept; files with the wrong one are replaced.

  python3 scripts/fetch_data.py           pinned snapshot (normal builds)
  python3 scripts/fetch_data.py --latest  fresh upstream data, overwriting
                                          data/raw/; prints new checksums
"""
import hashlib
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


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    print(f"downloading {url} ...")
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    print(f"  saved {dest.name} ({dest.stat().st_size:,} bytes)")


def main():
    latest = "--latest" in sys.argv
    config = json.loads((ROOT / "config.json").read_text())
    RAW.mkdir(parents=True, exist_ok=True)
    for filename, key in FILES.items():
        src = config["sources"][key]
        dest = RAW / filename
        if latest:
            download(src["url"], dest)
            print(f"  sha256 {sha256(dest)}")
            continue
        if dest.exists() and sha256(dest) == src["sha256"]:
            print(f"already have {filename} (checksum ok) - skipping")
            continue
        if dest.exists():
            print(f"{filename} differs from the pinned snapshot - replacing it")
        download(src["pinned_url"], dest)
        if sha256(dest) != src["sha256"]:
            sys.exit(f"checksum mismatch for {filename}: the pinned download is not the expected file")
    print("done.")


if __name__ == "__main__":
    sys.exit(main())
