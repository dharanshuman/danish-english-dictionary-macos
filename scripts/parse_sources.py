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
# the most common N headwords were checked by hand against ordnet.dk, so the
# automatic COR corrections leave them to data/curated/fixes.json
TIER1_REVIEWED = 1000
# forms of words up to this frequency rank are kept in "form_only"
FORM_ENTRY_MAX_RANK = 6000

# ---------------------------------------------------------------- kaikki ---

SKIP_FORM_TAGS = {"table-tags", "inflection-template", "class"}
IGNORE_INFL_TAGS = {"obsolete", "alternative", "dated", "archaic",
                    "genitive", "passive"}
# sense tags that mean "not the everyday meaning"; used to order blocks
MARKED_TAGS = {"rare", "archaic", "obsolete", "dated", "dialectal", "nonstandard",
               "misspelling", "pejorative", "vulgar", "slang", "historical",
               "uncommon", "Jutland", "Bornholm", "regional"}


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
        if form in ("er", "har", "at"):  # "er/har kværket" split into two forms
            continue
        if pos == "noun":
            if {"definite", "singular"} <= tags:
                infl.setdefault("def_sg", form)
            elif {"indefinite", "plural"} <= tags:
                infl.setdefault("pl", form)
            elif {"definite", "plural"} <= tags:
                infl.setdefault("def_pl", form)
        elif pos == "verb":
            # order matters: participles are tagged past+participle; the
            # present participle (udforskende) is not the one we memorize
            if "participle" in tags and "present" in tags:
                continue
            if "participle" in tags or "perfect" in tags:
                # "har stukket", "har (have /havde /er /var) stukket" -> stukket
                infl.setdefault("part", form.split()[-1])
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
                sense = {"gloss": glosses[-1], "examples": examples[:MAX_EXAMPLES]}
                marked = sorted(set(tags) & MARKED_TAGS)
                if marked:
                    sense["tags"] = marked
                senses.append(sense)
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

# COR form codes -> the label a learner sees, e.g. "past tense of være"
COR_FORM_LABELS = [
    ("vb.imp", "command form"),
    ("vb.præs.akt", "present tense"),
    ("vb.præt.akt", "past tense"),
    ("vb.perf.part", "past participle"),
    ("vb.præs.part", "-ing form"),
    ("sb.fk.sg.best", "“the …” form"), ("sb.itk.sg.best", "“the …” form"),
    ("sb.fk.pl.ubest", "plural"), ("sb.itk.pl.ubest", "plural"),
    ("sb.fk.pl.best", "“the …” plural"), ("sb.itk.pl.best", "“the …” plural"),
    ("adj.sg.ubest.itk", "et-word form"),
    ("adj.adv", "adverb form"),
    ("adj.kompar", "comparative"),
    ("adj.superl", "superlative"),
    ("adj.sg.best", "-e form"), ("adj.pl", "-e form"),
    ("pron.pl", "plural"), ("pron.sg.itk", "et-word form"),
    ("pron.obl", "object form"),
]


COR_POS = {"vb": "verb", "sb": "noun", "adj": "adj", "pron": "pron"}


def cor_form_label(code):
    """("past tense", "verb") for a COR code, or None if not worth showing."""
    if ".gen" in code or ".pass" in code or code.startswith("adj.adv."):
        return None
    # kørte as an adjective (de kørte biler) is not the past participle (kørt)
    if code.startswith("vb.perf.part.") and code.endswith((".pl", ".best")):
        return None
    for prefix, label in COR_FORM_LABELS:
        if code == prefix or code.startswith(prefix + "."):
            return label, COR_POS[code.split(".")[0]]
    return None


def parse_cor():
    """lemma -> set of inflected forms; lemma -> gender for nouns;
    form -> [(label, lemma, pos)] for forms that belong to another lemma."""
    forms = {}
    gender = {}
    form_of = {}
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
            labelled = cor_form_label(pos_code)
            if labelled and form != lemma:
                ref = (labelled[0], lemma, labelled[1])
                lst = form_of.setdefault(form, [])
                if ref not in lst:
                    lst.append(ref)
            if pos_code.startswith("sb.itk"):
                gender.setdefault(lemma, "et")
            elif pos_code.startswith("sb.fk"):
                gender.setdefault(lemma, "en")
    total = sum(len(v) for v in forms.values())
    print(f"COR: {len(forms):,} lemmas, {total:,} extra inflected forms")
    return forms, gender, form_of


# COR slot codes for the forms we show; mirrors extract_infl's keys
COR_SLOTS = {
    "noun": {"def_sg": ("sb.fk.sg.best", "sb.itk.sg.best"),
             "pl": ("sb.fk.pl.ubest", "sb.itk.pl.ubest"),
             "def_pl": ("sb.fk.pl.best", "sb.itk.pl.best")},
    "verb": {"present": ("vb.præs.akt",), "past": ("vb.præt.akt",),
             "part": ("vb.perf.part",), "imp": ("vb.imp",)},
    "adj": {"t": ("adj.sg.ubest.itk",), "e": ("adj.sg.best",),
            "comp": ("adj.kompar",), "sup": ("adj.superl.sg.ubest",)},
}
# suppletive comparatives COR doesn't model (mangen -> flere, flest)
COR_SKIP = {"mangen"}
COR_POS_PREFIX = {"noun": "sb.", "verb": "vb.", "adj": "adj."}


def parse_cor_paradigms():
    """lemma -> [ {code: set(forms)} ], one dict per COR paradigm (homograph)."""
    paradigms = {}
    with open(RAW / "cor1.5.1.0.tsv", encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 5 or not cols[1] or not cols[4]:
                continue
            pid = ".".join(cols[0].split(".")[:2])
            paradigms.setdefault(cols[1], {}).setdefault(pid, {}).setdefault(cols[3], set()).add(cols[4])
    return {lemma: list(p.values()) for lemma, p in paradigms.items()}


def correct_from_cor(danish, ranks, skip_rank):
    """Wiktionary's scraped forms have typos (fægtemaskeer, partilederene,
    stillinget) and gaps (være had no present tense). Where COR has exactly
    one paradigm for the word's part of speech, fill missing forms from it,
    and trust it over Wiktionary for gender and wrong forms — except for the
    most common words, reviewed by hand (data/curated/fixes.json), and
    "mere X / mest X" comparatives (also correct Danish)."""
    paradigms = parse_cor_paradigms()
    fixed = filled = 0
    for word, blocks in danish.items():
        if word in COR_SKIP:
            continue
        skip = (ranks.get(word.lower()) or 10**9) <= skip_rank
        for b in blocks:
            pos = b["pos"]
            if pos not in COR_SLOTS:
                continue
            same_pos = [p for p in paradigms.get(word, [])
                        if any(code.startswith(COR_POS_PREFIX[pos]) for code in p)]
            if len(same_pos) != 1:
                continue
            p = same_pos[0]
            if pos == "noun" and not skip:
                genders = {"et" if c.startswith("sb.itk") else "en"
                           for c in p if c.startswith(("sb.itk", "sb.fk"))}
                if len(genders) == 1 and b.get("gender") and b["gender"] not in genders:
                    b["gender"] = genders.pop()
                    fixed += 1
            infl = b.setdefault("infl", {})
            for key, codes in COR_SLOTS[pos].items():
                if not infl.get(key):
                    # fill a gap (være had no present tense); nothing is
                    # overwritten, so this runs for every word. Nouns with no
                    # forms at all are left alone (uncountables, names).
                    # Not comparatives: COR lists femininere, driftsmæssigere…
                    # where Danes say "mere feminin".
                    found = sorted({f for c in codes for f in p.get(c, ())})
                    if found and key not in ("comp", "sup") and (pos != "noun" or infl):
                        infl[key] = found[0]
                        filled += 1
                    continue
                if skip or infl[key].startswith(("mere ", "mest ")):
                    continue
                # several allowed = spelling variants (målebægeret/målebægret)
                allowed = sorted({f for c in codes for f in p.get(c, ())})
                if allowed and infl[key] not in allowed:
                    infl[key] = allowed[0]
                    fixed += 1
    return fixed, filled


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
    cor_forms, cor_gender, cor_form_of = parse_cor()

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

    # tier 1 (see config.json) is reviewed by hand; rank of its last word
    tier1_rank = sorted(r for w, r in ranks.items() if w in danish)[TIER1_REVIEWED - 1]
    fixed, filled = correct_from_cor(danish, ranks, tier1_rank)
    print(f"COR: corrected {fixed:,} wrong forms/genders, filled {filled:,} missing forms")

    # "læs" is also the command form of "læse": keep those readings (only
    # for lemmas we have an entry for, so the line can show its meaning)
    def refs_for(word):
        refs = []
        for label, lemma, pos in cor_form_of.get(word, []):
            if lemma not in danish:
                continue
            same = next((r for r in refs if r["of"] == lemma and r["pos"] == pos), None)
            if same:  # "store" is both the -e form and plural: one line
                if label not in same["label"]:
                    same["label"] += f" / {label}"
            else:
                refs.append({"label": label, "of": lemma, "pos": pos})
        return refs

    form_of = {w: refs for w in danish if (refs := refs_for(w))}
    print(f"form-of readings for {len(form_of):,} headwords")

    # Inflected forms that are not headwords (sagde, gik, husene) of common
    # words: build_xml can give them a small entry of their own, so the
    # popup can underline the form that was looked up (config: form_entries)
    def lemma_rank(lemma):
        return min((b.get("freq_rank") or 10**9) for b in danish[lemma])

    form_only = {}
    for form in cor_form_of:
        if form in danish or " " in form:
            continue
        refs = [r for r in refs_for(form) if lemma_rank(r["of"]) <= FORM_ENTRY_MAX_RANK]
        if refs:
            form_only[form] = refs
    print(f"form-of readings for {len(form_only):,} other forms of common words")

    out = {"danish": danish, "english": english, "form_of": form_of, "form_only": form_only}
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"totals: {len(danish):,} Danish + {len(english):,} English headwords")


if __name__ == "__main__":
    sys.exit(main())
