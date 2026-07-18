#!/usr/bin/env python3
"""Build src/DanishEnglish.xml — the file Apple's Dictionary
Development Kit compiles into a .dictionary bundle.

Every Danish entry gets a <d:index> for the headword AND for every
inflected form (from Wiktionary + COR), so looking up "husene" finds
"hus". English entries come from the reverse index, so "house" works
too. AI-written content is wrapped in classes the CSS labels clearly.

Usage: python3 scripts/build_xml.py
"""
import json
import pathlib
import sys
from xml.sax.saxutils import escape, quoteattr

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "DanishEnglish.xml"

POS_NAMES = {
    "noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb",
    "pron": "pronoun", "prep": "preposition", "conj": "conjunction",
    "intj": "interjection", "num": "numeral", "article": "article",
    "det": "determiner", "particle": "particle", "phrase": "phrase",
    "prep_phrase": "prepositional phrase", "proverb": "proverb",
    "name": "proper noun", "suffix": "suffix", "prefix": "prefix",
    "contraction": "contraction", "abbrev": "abbreviation",
}


def indexes(word, forms):
    seen = {word}
    out = [f"<d:index d:value={quoteattr(word)} d:title={quoteattr(word)}/>"]
    for form in forms:
        f = form.strip()
        if not f or f in seen or len(f) > 60:
            continue
        seen.add(f)
        # d:title makes the lookup panel show the inflected form the user
        # selected, while the entry body shows the base word
        out.append(f"<d:index d:value={quoteattr(f)} d:title={quoteattr(f)}/>")
    return out


def danish_entry(n, word, blocks):
    eid = f"da_{n}"
    all_forms = sorted({f for b in blocks for f in b.get("forms", [])})
    parts = ["\n".join(indexes(word, all_forms))]
    parts.append(f"<h1>{escape(word)}</h1>")

    for b in blocks:
        pos = POS_NAMES.get(b["pos"], b["pos"])
        meta = []
        if pos:
            meta.append(f"<span class=\"pos\">{escape(pos)}</span>")
        if b.get("gender") and b["pos"] == "noun":
            g = "neuter (et)" if b["gender"] == "et" else "common (en)"
            meta.append(f"<span class=\"gender\">{g}</span>")
        if b.get("plural"):
            meta.append(f"<span class=\"plural\">plural: {escape(b['plural'])}</span>")
        if b.get("ipa"):
            meta.append(f"<span class=\"ipa\">{escape(b['ipa'])}</span>")
        parts.append(f"<div class=\"meta\">{' · '.join(meta)}</div>")

        parts.append("<ol class=\"senses\">")
        for s in b["senses"]:
            ex_html = ""
            for ex in s.get("examples", []):
                cls = "example ai" if ex.get("ai") else "example"
                en = f"<span class=\"ex-en\">{escape(ex['en'])}</span>" if ex.get("en") else ""
                ex_html += (f"<div class=\"{cls}\">"
                            f"<span class=\"ex-da\">{escape(ex['da'])}</span> {en}</div>")
            parts.append(f"<li>{escape(s['gloss'])}{ex_html}</li>")
        parts.append("</ol>")

        if b.get("gotcha"):
            parts.append(
                "<div class=\"gotcha\"><span class=\"gotcha-head\">⚠️ Gotcha "
                "<span class=\"ai-tag\">AI-generated</span></span> "
                f"{escape(b['gotcha'])}</div>"
            )
    body = "\n".join(parts)
    return f"<d:entry id=\"{eid}\" d:title={quoteattr(word)}>\n{body}\n</d:entry>"


def english_entry(n, word, translations):
    eid = f"en_{n}"
    parts = [f"<d:index d:value={quoteattr(word)} d:title={quoteattr(word)}/>"]
    parts.append(f"<h1>{escape(word)}</h1>")
    parts.append("<div class=\"meta\"><span class=\"pos\">English → Danish</span></div>")
    parts.append("<ul class=\"translations\">")
    for t in translations[:10]:
        pos = POS_NAMES.get(t["pos"], t["pos"])
        pos_html = f" <span class=\"pos\">{escape(pos)}</span>" if pos else ""
        gloss = t["gloss"]
        gloss_html = (f" <span class=\"ex-en\">({escape(gloss)})</span>"
                      if gloss.lower() != word.lower() else "")
        parts.append(f"<li><span class=\"da-word\">{escape(t['da'])}</span>"
                     f"{pos_html}{gloss_html}</li>")
    parts.append("</ul>")
    body = "\n".join(parts)
    return f"<d:entry id=\"{eid}\" d:title={quoteattr(word)}>\n{body}\n</d:entry>"


FRONT_MATTER = """<d:entry id="front_back_matter" d:title="Front/Back Matter">
<h1><b>Danish – English Dictionary</b></h1>
<p>Danish ⇄ English for macOS Look Up. Data from Wiktionary (via Wiktextract/kaikki.org, CC BY-SA 4.0), FreeDict, and the Danish Central Word Register (COR, CC0). Example sentences and “gotcha” notes for the most common words are AI-generated and clearly labeled.</p>
<p>Source &amp; issues: github.com/dharanshuman/danish-english-dictionary-macos</p>
</d:entry>"""


def main():
    data_path = ROOT / "data" / "enriched.json"
    if not data_path.exists():
        data_path = ROOT / "data" / "normalized.json"
        print("note: data/enriched.json not found, building without AI content")
    data = json.loads(data_path.read_text(encoding="utf-8"))

    entries = [FRONT_MATTER]
    for n, (word, blocks) in enumerate(sorted(data["danish"].items())):
        entries.append(danish_entry(n, word, blocks))
    for n, (word, translations) in enumerate(sorted(data["english"].items())):
        # skip English words identical to a Danish headword we already have;
        # both would match anyway, and the Danish entry is richer
        entries.append(english_entry(n, word, translations))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<d:dictionary xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rng">\n'
        + "\n".join(entries) + "\n</d:dictionary>\n"
    )
    SRC.write_text(xml, encoding="utf-8")
    n_da = len(data["danish"])
    n_en = len(data["english"])
    print(f"wrote {SRC} ({SRC.stat().st_size:,} bytes): "
          f"{n_da:,} Danish + {n_en:,} English entries")


if __name__ == "__main__":
    sys.exit(main())
