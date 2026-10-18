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


# first glosses that mean "this block is not the everyday word"
WEAK_GLOSS = ("only used in", "clipping of", "alternative form of", "alternative spelling",
              "obsolete", "misspelling", "abbreviation of", "initialism of", "archaic",
              "dated form", "eye dialect", "nonstandard")


def block_rank(b):
    """Lower = more likely the meaning a learner is looking for."""
    senses = b["senses"]
    marked = sum(1 for s in senses if s.get("tags"))
    weak = senses[0]["gloss"].lower().startswith(WEAK_GLOSS) if senses else True
    # deliberately not "more senses first": that puts du = "be good" above
    # du = "you". Anything subtler is a curated "primary" fix.
    return (
        b["pos"] == "name",
        weak or marked == len(senses),  # every sense rare/archaic/dialect
    )


def order_blocks(data):
    """Wiktionary lists homographs in etymology order, so a rare noun can
    come before the everyday verb; and everything AI-written attaches to the
    first block. Put the likeliest block first (curated "primary" fixes can
    still override)."""
    moved = 0
    for word, blocks in data["danish"].items():
        ordered = sorted(blocks, key=block_rank)  # stable: ties keep source order
        if ordered[0] is not blocks[0]:
            moved += 1
        blocks[:] = ordered
    return moved


# ------------------------------------------------- curated fixes (fixes.json)

LATE_OPS = {"word", "drop_example", "fix_example"}


def select(blocks, op):
    for b in blocks:
        if b["pos"] != op.get("pos", b["pos"]):
            continue
        if op.get("match") and not (b["senses"] and op["match"] in b["senses"][0]["gloss"]):
            continue
        return b
    return None


def apply_fix(word, blocks, op):
    """Apply one op from data/curated/fixes.json; return False if it didn't apply."""
    kind = op["op"]
    if kind == "add_block":
        nb = op["block"]
        blocks.append({
            "pos": nb["pos"], "gender": nb.get("gender"), "ipa": nb.get("ipa"),
            "plural": None, "infl": nb.get("infl") or {},
            "senses": [{"gloss": g, "examples": []} for g in nb["senses"]],
            "forms": blocks[0]["forms"] if blocks else [], "source": "curated",
            "freq_rank": blocks[0].get("freq_rank") if blocks else None,
        })
        return True
    if kind == "word":
        if not blocks:
            return False
        if op["value"] is None:
            blocks[0].pop(op["field"], None)
        else:
            blocks[0][op["field"]] = op["value"]
        return True
    if kind in ("drop_example", "fix_example"):
        hit = False
        for b in blocks:
            for s in b["senses"]:
                for i, ex in enumerate(s["examples"]):
                    if op["contains"] in ex["da"]:
                        hit = True
                        if kind == "fix_example":
                            s["examples"][i] = {**ex, "da": op["da"], "en": op["en"]}
                if kind == "drop_example":
                    s["examples"] = [ex for ex in s["examples"] if op["contains"] not in ex["da"]]
        return hit

    b = select(blocks, op)
    if b is None:
        return False
    if kind == "primary":
        blocks.remove(b)
        blocks.insert(0, b)
    elif kind == "drop_block":
        blocks.remove(b)
    elif kind == "senses":
        new = [{"gloss": g, "examples": []} for g in op["glosses"]]
        if op["mode"] == "replace":
            b["senses"] = new
        elif op["mode"] == "prepend":
            b["senses"] = new + b["senses"]
        else:
            b["senses"] = b["senses"] + new
    elif kind == "drop_sense":
        b["senses"] = [s for s in b["senses"] if op["gloss"] not in s["gloss"]]
    elif kind == "set":
        if op["value"] is None:
            b.pop(op["field"], None)
        else:
            b[op["field"]] = op["value"]
    elif kind == "set_infl":
        b.setdefault("infl", {})
        if op["value"] is None:
            b["infl"].pop(op["key"], None)
        else:
            b["infl"][op["key"]] = op["value"]
    else:
        return False
    return True


def apply_fixes(data, late):
    """Early pass: structure (blocks, senses, forms). Late pass, after the AI
    and curated content is attached: notes, respellings, examples, aux."""
    applied, failed = 0, []
    for word, ops in load_curated("fixes.json").items():
        blocks = data["danish"].get(word)
        if blocks is None:
            if late:
                continue
            blocks = data["danish"][word] = []
        for op in ops:
            is_late = op["op"] in LATE_OPS or (op["op"] == "set" and op.get("field") == "aux")
            if is_late != late:
                continue
            if apply_fix(word, blocks, op):
                applied += 1
            else:
                failed.append(f"{word}:{op['op']}")
        if not blocks:
            del data["danish"][word]
    return applied, failed


def place_form_of(data):
    """Decide, per headword, whether "also: past tense of være" goes before
    the word's own meaning: when its own top block is a rare/weak reading,
    or the other word is very common (command forms: when the verb is more
    common than this spelling, as with læs → læse)."""
    da = data["danish"]
    order = load_curated("form_of_order.json")
    after, forced = set(order.get("after", [])), set(order.get("first", []))

    def rank(w):
        return min((b.get("freq_rank") or 10**9) for b in da[w]) if da.get(w) else 10**9

    first = 0
    for word, refs in data.get("form_of", {}).items():
        if not da.get(word):
            continue
        weak = block_rank(da[word][0])[1]
        for ref in refs:
            lemma_rank = rank(ref["of"])
            if ref["label"] == "command form":
                common = lemma_rank < rank(word)
            else:
                common = lemma_rank <= 300
            ref["first"] = word in forced or (word not in after and (weak or common))
            first += ref["first"]
        refs.sort(key=lambda r: (not r["first"], rank(r["of"])))
    return first


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

    moved = order_blocks(data)
    early_fixes, failed_fixes = apply_fixes(data, late=False)

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
    n_co = attach("concepts.json", "concept")

    # which verbs form their perfect with "er" (er kommet) instead of "har"
    er_verbs = set(json.loads((CURATED_DIR / "er_verbs.json").read_text())
                   if (CURATED_DIR / "er_verbs.json").exists() else [])
    for word, blocks in data["danish"].items():
        for b in blocks:
            if b["pos"] == "verb" and b.get("infl", {}).get("part"):
                b["aux"] = "er" if word in er_verbs else "har"

    late_fixes, failed_late = apply_fixes(data, late=True)
    failed_fixes += failed_late
    n_first = place_form_of(data)

    ENRICHED.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"block order: everyday block moved to the top for {moved:,} words")
    print(f"fixes.json: {early_fixes + late_fixes:,} ops applied")
    print(f"form-of readings shown before the word's own meaning: {n_first:,}")
    if failed_fixes:
        print(f"WARNING - {len(failed_fixes)} fixes matched nothing: {failed_fixes}")
    print(f"merged AI content for {enriched_count:,} of {len(words):,} tier-1 words")
    print(f"pronunciation respellings: {pron_count:,}")
    print(f"curated: {n_ff} false friends, {n_cf} confusables, {n_ch} chunk sets, "
          f"{n_no} usage notes, {n_co} concepts")
    if curated_missing:
        print(f"WARNING - curated words not found as headwords: {curated_missing}")
    print(f"wrote {ENRICHED}")


if __name__ == "__main__":
    sys.exit(main())
