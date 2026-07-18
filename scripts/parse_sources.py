#!/usr/bin/env python3
"""Turn the raw downloaded data into one clean file: data/normalized.json.

What it does, step by step:
1. Reads Wiktionary data (kaikki JSONL) -> Danish words with meanings,
   gender, plural, pronunciation, inflected forms, and real examples.
2. Reads COR (the official Danish word register) -> extra inflected forms,
   so looking up "husene" finds "hus".
3. Reads FreeDict -> extra Danish words that Wiktionary is missing.
4. Builds a reverse English -> Danish index from the translations.
5. Attaches a frequency rank to each word (1 = most common).

Usage: python3 scripts/parse_sources.py
"""
import gzip
import json
import pathlib
import re
import struct
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "normalized.json"

MAX_EXAMPLES = 3

# ---------------------------------------------------------------- kaikki ---

SKIP_FORM_TAGS = {"table-tags", "inflection-template", "class"}
IGNORE_INFL_TAGS = {"obsolete", "alternative", "dated", "archaic",
                    "genitive", "passive"}


def extract_infl(pos, forms):
    """Pull the forms a learner memorizes into a small labeled dict.

    Nouns:      def_sg (bilen), pl (biler), def_pl (bilerne)
    Verbs:      present (bor), past (boede), part (boet), imp (bo)
    Adjectives: t (stort), e (store), comp (større), sup (størst)
    """
    infl = {}
    for fo in forms:
        form = (fo.get("form") or "").strip()
        tags = set(fo.get("tags", []))
        if not form or form == "-" or tags & SKIP_FORM_TAGS:
            continue
        if tags & IGNORE_INFL_TAGS:
            continue
        if pos == "noun":
            if {"definite", "singular"} <= tags:
                infl.setdefault("def_sg", form)
            elif {"indefinite", "plural"} <= tags:
                infl.setdefault("pl", form)
            elif {"definite", "plural"} <= tags:
                infl.setdefault("def_pl", form)
        elif pos == "verb":
            # order matters: participles are tagged past+participle
            if "participle" in tags or "perfect" in tags:
                infl.setdefault("part", form.removeprefix("har ").removeprefix("er "))
            elif "present" in tags:
                infl.setdefault("present", form)
            elif "past" in tags:
                infl.setdefault("past", form)
            elif "imperative" in tags:
                infl.setdefault("imp", form)
        elif pos == "adj":
            if "neuter" in tags:
                infl.setdefault("t", form)
            elif "comparative" in tags:
                infl.setdefault("comp", form)
            elif "superlative" in tags:
                infl.setdefault("sup", form)
            elif "definite" in tags or "plural" in tags:
                infl.setdefault("e", form)
    return infl


def parse_kaikki():
    danish = {}
    path = RAW / "kaikki.org-dictionary-Danish.jsonl"
    n_lines = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            n_lines += 1
            e = json.loads(line)
            word = e.get("word")
            pos = e.get("pos")
            if not word or not pos:
                continue

            senses = []
            gender = None
            for s in e.get("senses", []):
                tags = s.get("tags", [])
                if "form-of" in tags:
                    continue  # "huset" = definite of "hus" -> handled via forms
                glosses = s.get("glosses") or []
                if not glosses:
                    continue
                if "neuter" in tags:
                    gender = "et"
                elif "common-gender" in tags:
                    gender = "en"
                examples = []
                for ex in s.get("examples", []):
                    text = (ex.get("text") or "").strip()
                    english = (ex.get("english") or "").strip()
                    if text:
                        examples.append({"da": text, "en": english})
                senses.append({
                    "gloss": glosses[-1],
                    "examples": examples[:MAX_EXAMPLES],
                })
            if not senses:
                continue

            ipa = None
            for snd in e.get("sounds", []):
                if snd.get("ipa"):
                    ipa = snd["ipa"]
                    break

            forms = []
            plural = None
            for fo in e.get("forms", []):
                tags = set(fo.get("tags", []))
                form = (fo.get("form") or "").strip()
                if not form or tags & SKIP_FORM_TAGS or form == "-":
                    continue
                if form.lower() == word.lower():
                    continue
                forms.append(form)
                if plural is None and {"indefinite", "plural"} <= tags:
                    plural = form

            block = {
                "pos": pos,
                "gender": gender,
                "ipa": ipa,
                "plural": plural,
                "infl": extract_infl(pos, e.get("forms", [])),
                "senses": senses,
                "forms": sorted(set(forms)),
                "source": "wiktionary",
            }
            danish.setdefault(word, []).append(block)
    print(f"kaikki: {n_lines:,} lines -> {len(danish):,} Danish headwords with real senses")
    return danish


# ------------------------------------------------------------------- COR ---

def parse_cor():
    """lemma -> set of inflected forms; also lemma -> gender for nouns."""
    forms = {}
    gender = {}
    with open(RAW / "cor1.5.1.0.tsv", encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 5:
                continue
            lemma, pos_code, form = cols[1], cols[3], cols[4]
            if not lemma or not form:
                continue
            forms.setdefault(lemma, set())
            if form != lemma:
                forms[lemma].add(form)
            if pos_code.startswith("sb.itk"):
                gender.setdefault(lemma, "et")
            elif pos_code.startswith("sb.fk"):
                gender.setdefault(lemma, "en")
    total = sum(len(v) for v in forms.values())
    print(f"COR: {len(forms):,} lemmas, {total:,} extra inflected forms")
    return forms, gender


# -------------------------------------------------------------- stardict ---

TAG_RE = re.compile(r"<[^>]+>")


def read_stardict(tar_path):
    """Minimal StarDict reader. Returns {headword: plain-text article}."""
    with tarfile.open(tar_path) as tar:
        idx_m = next(m for m in tar.getmembers()
                     if m.name.endswith(".idx") or m.name.endswith(".idx.gz"))
        dict_m = next(m for m in tar.getmembers() if m.name.endswith(".dict.dz"))
        idx = tar.extractfile(idx_m).read()
        if idx_m.name.endswith(".gz"):
            idx = gzip.decompress(idx)
        dict_data = gzip.decompress(tar.extractfile(dict_m).read())

    entries = {}
    i = 0
    while i < len(idx):
        end = idx.index(b"\0", i)
        word = idx[i:end].decode("utf-8")
        offset, size = struct.unpack(">II", idx[end + 1:end + 9])
        article = dict_data[offset:offset + size].decode("utf-8", "replace")
        text = TAG_RE.sub(" ", article)
        text = re.sub(r"\s+", " ", text).strip()
        entries[word] = text
        i = end + 9
    return entries


def clean_freedict_article(word, text):
    """Strip the repeated headword / pronunciation from the front."""
    t = text
    if t.lower().startswith(word.lower()):
        t = t[len(word):].strip()
    t = re.sub(r"^/[^/]*/\s*", "", t)  # leading /pronunciation/
    return t.strip(" ,;")


# ------------------------------------------------------------------ main ---

def main():
    danish = parse_kaikki()
    cor_forms, cor_gender = parse_cor()

    # merge COR forms + gender into the Danish records
    merged_forms = 0
    for word, blocks in danish.items():
        extra = cor_forms.get(word, set())
        if extra:
            merged_forms += 1
        all_forms = set(extra)
        for b in blocks:
            all_forms.update(b["forms"])
            if b["pos"] == "noun" and not b["gender"]:
                b["gender"] = cor_gender.get(word)
        for b in blocks:
            b["forms"] = sorted(all_forms)
    print(f"COR forms merged into {merged_forms:,} headwords")

    # FreeDict Danish->English: add words Wiktionary doesn't have
    fd_da = read_stardict(RAW / "freedict-dan-eng-0.3.1.stardict.tar.xz")
    added = 0
    for word, text in fd_da.items():
        if word in danish:
            continue
        gloss = clean_freedict_article(word, text)
        if not gloss:
            continue
        danish[word] = [{
            "pos": "", "gender": cor_gender.get(word), "ipa": None,
            "plural": None, "infl": {},
            "senses": [{"gloss": gloss, "examples": []}],
            "forms": sorted(cor_forms.get(word, set())),
            "source": "freedict",
        }]
        added += 1
    print(f"FreeDict dan-eng: +{added:,} extra Danish headwords (of {len(fd_da):,})")

    # English -> Danish reverse index, built by inverting the glosses
    english = {}
    for word, blocks in danish.items():
        for b in blocks:
            for s in b["senses"]:
                gloss = s["gloss"]
                # split "block of flats, cottage" into candidate terms
                for term in re.split(r"[,;]", gloss):
                    term = term.strip().lower()
                    term = re.sub(r"\([^)]*\)", "", term).strip()
                    if not term or len(term) > 30 or len(term.split()) > 3:
                        continue
                    if not re.fullmatch(r"[a-z][a-z' -]*", term):
                        continue
                    lst = english.setdefault(term, [])
                    if not any(x["da"] == word and x["pos"] == b["pos"] for x in lst):
                        lst.append({"da": word, "pos": b["pos"], "gloss": gloss})

    # FreeDict English->Danish seeds
    fd_en = read_stardict(RAW / "freedict-eng-dan-0.1.0.stardict.tar.xz")
    for word, text in fd_en.items():
        gloss = clean_freedict_article(word, text)
        key = word.lower()
        if gloss and key not in english:
            english[key] = [{"da": gloss, "pos": "", "gloss": gloss}]
    print(f"English->Danish index: {len(english):,} English headwords")

    # frequency ranks
    ranks = {}
    with open(RAW / "da_50k.txt", encoding="utf-8") as f:
        for rank, line in enumerate(f, 1):
            w = line.split()[0]
            ranks.setdefault(w, rank)
    for word, blocks in danish.items():
        r = ranks.get(word.lower())
        for b in blocks:
            b["freq_rank"] = r

    out = {"danish": danish, "english": english}
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"totals: {len(danish):,} Danish + {len(english):,} English headwords")


if __name__ == "__main__":
    sys.exit(main())
