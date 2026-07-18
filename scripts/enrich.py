#!/usr/bin/env python3
"""Add AI-written examples and "gotcha" notes to the most common words.

How it works:
- Tier 1 = the top N most common Danish words (N = tier1_size in
  config.json) that exist in our data. Only these get AI content.
- The AI content itself lives in data/ai_cache/*.json. Each file maps
  headword -> {"examples": [{"da","en"}], "gotcha": "..."}.
  The cache is committed to the repo, so rebuilding is free and offline.
- This script merges the cache into the data and writes
  data/enriched.json. AI fields are marked with "ai": true so the
  build step can label them in the entry.

Two commands:
  python3 scripts/enrich.py --list   Write data/tier1_words.json
                                     (the words that still need AI content)
  python3 scripts/enrich.py          Merge cache -> data/enriched.json
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "ai_cache"
CURATED_DIR = ROOT / "data" / "curated"
NORMALIZED = ROOT / "data" / "normalized.json"
ENRICHED = ROOT / "data" / "enriched.json"
TIER1_LIST = ROOT / "data" / "tier1_words.json"


def load_cache(pattern="batch_*.json"):
    cache = {}
    for path in sorted(CACHE_DIR.glob(pattern)):
        cache.update(json.loads(path.read_text(encoding="utf-8")))
    return cache


def load_curated(name):
    path = CURATED_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def tier1_words(data, size):
    """The `size` most common Danish headwords, by frequency rank."""
    ranked = []
    for word, blocks in data["danish"].items():
        rank = min((b.get("freq_rank") or 10**9) for b in blocks)
        if rank < 10**9:
            ranked.append((rank, word))
    ranked.sort()
    return [w for _, w in ranked[:size]]


def main():
    config = json.loads((ROOT / "config.json").read_text())
    data = json.loads(NORMALIZED.read_text(encoding="utf-8"))
    words = tier1_words(data, config["tier1_size"])
    cache = load_cache()

    if "--list" in sys.argv:
        missing = []
        for w in words:
            if w in cache:
                continue
            blocks = data["danish"][w]
            missing.append({
                "word": w,
                "pos": [b["pos"] for b in blocks],
                "gender": next((b["gender"] for b in blocks if b.get("gender")), None),
                "glosses": [s["gloss"][:80] for b in blocks for s in b["senses"]][:4],
                "has_real_example": any(s["examples"] for b in blocks for s in b["senses"]),
            })
        TIER1_LIST.write_text(json.dumps(missing, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"tier 1 = {len(words)} words; {len(missing)} still need AI content")
        print(f"wrote {TIER1_LIST}")
        return

    enriched_count = 0
    tier1 = set(words)
    for word, blocks in data["danish"].items():
        if word not in tier1 or word not in cache:
            continue
        ai = cache[word]
        b = blocks[0]
        examples = [
            {"da": ex["da"], "en": ex["en"], "ai": True}
            for ex in ai.get("examples", [])
        ]
        if examples and b["senses"]:
            existing = b["senses"][0]["examples"]
            room = config["max_examples_per_entry"] - len(existing)
            b["senses"][0]["examples"] = existing + examples[:max(room, 0)]
        gotcha = (ai.get("gotcha") or "").strip()
        if gotcha:
            b["gotcha"] = gotcha
        enriched_count += 1

    # AI pronunciation respellings ("sounds like") for tier-1 words
    pron = load_cache("pron_*.json")
    pron_count = 0
    for word, blocks in data["danish"].items():
        p = pron.get(word)
        if not p:
            continue
        if (p.get("sounds_like") or "").strip():
            blocks[0]["sounds_like"] = p["sounds_like"].strip()
        if (p.get("spoken") or "").strip():
            blocks[0]["spoken"] = p["spoken"].strip()
        pron_count += 1

    # stub entries for important words Wiktionary lacks as headwords
    for word, stub in load_curated("stubs.json").items():
        if word not in data["danish"]:
            data["danish"][word] = [{
                "pos": stub["pos"], "gender": None, "ipa": None,
                "plural": None, "infl": {},
                "senses": [{"gloss": stub["gloss"], "examples": []}],
                "forms": [], "source": "curated", "freq_rank": None,
            }]

    # curated word-level data (committed to the repo, editable by PR)
    curated_missing = []

    def attach(filename, key):
        count = 0
        for word, value in load_curated(filename).items():
            blocks = data["danish"].get(word)
            if not blocks:
                curated_missing.append(f"{filename}:{word}")
                continue
            blocks[0][key] = value
            count += 1
        return count

    n_ff = attach("false_friends.json", "false_friend")
    n_cf = attach("confusables.json", "confusables")
    n_ch = attach("chunks.json", "chunks")
    n_no = attach("notes.json", "usage_note")
    n_pa = attach("particles.json", "particle")

    # which verbs form their perfect with "er" (er kommet) instead of "har"
    er_verbs = set(json.loads((CURATED_DIR / "er_verbs.json").read_text())
                   if (CURATED_DIR / "er_verbs.json").exists() else [])
    for word, blocks in data["danish"].items():
        for b in blocks:
            if b["pos"] == "verb" and b.get("infl", {}).get("part"):
                b["aux"] = "er" if word in er_verbs else "har"

    ENRICHED.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"merged AI content for {enriched_count:,} of {len(words):,} tier-1 words")
    print(f"pronunciation respellings: {pron_count:,}")
    print(f"curated: {n_ff} false friends, {n_cf} confusables, {n_ch} chunk sets, "
          f"{n_no} usage notes, {n_pa} particles")
    if curated_missing:
        print(f"WARNING - curated words not found as headwords: {curated_missing}")
    print(f"wrote {ENRICHED}")


if __name__ == "__main__":
    sys.exit(main())
