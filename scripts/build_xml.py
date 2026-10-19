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
import re
import sys
from xml.sax.saxutils import escape, quoteattr

import english as english_mod

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


def indexes(word, forms, headwords=()):
    """Look Up lists every entry indexed under the selected text, sorted
    alphabetically, so a form that is also a headword ("hus", "er") would
    bury the real entry under "huse", "accelerere"…. Such forms are left to
    their own entry, whose "also: command form of huse" line links across."""
    seen = {word}
    out = [f"<d:index d:value={quoteattr(word)} d:title={quoteattr(word)}/>"]
    for form in forms:
        f = form.strip()
        if not f or f in seen or len(f) > 60 or f in headwords or f.startswith("-") or f.endswith("-"):
            continue
        seen.add(f)
        # d:title makes the lookup panel show the inflected form the user
        # selected, while the entry body shows the base word
        out.append(f"<d:index d:value={quoteattr(f)} d:title={quoteattr(f)}/>")
    return out


NOUN_LABELS = ("a …", "the …", "plural", "the … (pl.)")
VERB_LABELS = ("infinitive", "present", "past", "perfect")


def form_cells(word, b):
    """The memorize-me forms, in the order Danish courses use, each paired
    with its English (to read / reads / read / has read) when the first gloss
    inflects cleanly, else a grammar label. Returns [(danish, under, is_label)]."""
    infl = b.get("infl") or {}
    pos = b["pos"]
    gloss = b["senses"][0]["gloss"] if b["senses"] else ""
    if pos == "noun" and infl:
        art = b.get("gender") or ""
        danish = [f"{art} {word}".strip()] + [infl.get(k) for k in ("def_sg", "pl", "def_pl")]
        # penge, forældre: no "a money" (but et læs / to læs is a normal noun)
        plural_only = infl.get("pl") == word and not infl.get("def_sg")
        english = None if plural_only else english_mod.noun_forms(
            gloss, countable=bool(infl.get("pl") or infl.get("def_pl")))
        labels = NOUN_LABELS
    elif pos == "verb" and infl.get("present"):
        aux = b.get("aux", "har")
        danish = [f"at {word}", infl["present"], infl.get("past"),
                  f"{aux} {infl['part']}" if infl.get("part") else None]
        english, labels = english_mod.verb_forms(gloss), VERB_LABELS
    elif pos == "adj" and infl:
        danish = [word, infl.get("t"), infl.get("e"), infl.get("comp"), infl.get("sup")]
        english, labels = None, ("en-word", "et-word", "the / plural", "more", "most")
    else:
        return []
    if english and len(english) < len(danish) and any(danish[len(english):]):
        english = None
    cells = [(d, english[i] if english else labels[i], not english)
             for i, d in enumerate(danish) if d]
    return cells if len(cells) > 1 else []


def forms_html(cells, with_under, highlight=None):
    if not with_under:  # later blocks: one compact line
        return ("<div class=\"infl\">"
                + " <span class=\"sep\">·</span> ".join(escape(d) for d, _, _ in cells) + "</div>")
    out = []
    for d, under, is_label in cells:
        cls = "f-label" if is_label else "f-en"
        hit = highlight and (d == highlight or d.endswith(" " + highlight))
        out.append(f"<span class=\"fcell{' hit' if hit else ''}\"><span class=\"f-da\">{escape(d)}</span>"
                   f"<span class=\"{cls}\">{escape(under)}</span></span>")
    return f"<div class=\"forms\">{''.join(out)}</div>"


def short_gloss(gloss):
    """'worker, workman, laborer (a person who…)' -> 'worker, workman':
    no parentheses, at most two synonyms, no trailing definition."""
    g = re.sub(r"\s*\([^)]*\)", "", gloss).strip(" ,;.")
    if re.match(r"(A|An|To|The) [a-z]", g):  # Wiktionary's sentence style: "A novel."
        g = g[0].lower() + g[1:]
    first, *rest = re.split(r"[,;] ", g)
    # a short synonym is worth keeping; a definition ("factory, place of
    # industrial production") is not
    if rest and len(rest[0].split()) <= 3:
        first += ", " + rest[0]
    g = first
    return g if len(g) <= 48 else g[:46].rsplit(" ", 1)[0] + "…"


# an "also: …" line under the main meaning is noise unless the other word is
# reasonably common; command forms (hus = "house!" of huse) need to be very
# common to be worth a line
ALSO_AFTER_MAX_RANK = 5000
ALSO_COMMAND_MAX_RANK = 1000


def also_worth_showing(ref, danish):
    limit = ALSO_COMMAND_MAX_RANK if ref["label"] == "command form" else ALSO_AFTER_MAX_RANK
    return lemma_rank(ref["of"], danish) <= limit


def lemma_rank(lemma, danish):
    return min((b.get("freq_rank") or 10**9) for b in danish.get(lemma, [{}]))


def is_weak(b):
    return b["pos"] == "name" or not b["senses"] or all(s.get("tags") for s in b["senses"])


GLANCE_POS = {"noun": "noun", "verb": "verb", "adj": "adj.", "adv": "adv.", "pron": "pron.",
              "prep": "prep.", "conj": "conj.", "intj": "interj.", "num": "num."}


def glance_items(blocks):
    """The meaning at a glance: top two senses of the main block, or, when the
    word is several words in one (gift = married / poison), the first sense
    of each, so a homograph can't hide behind "more"."""
    others = [b for b in blocks[1:3] if not is_weak(b) and b["pos"] != blocks[0]["pos"]]
    if others:
        items = [(short_gloss(b["senses"][0]["gloss"]), GLANCE_POS.get(b["pos"]))
                 for b in [blocks[0]] + others if b["senses"]]
    else:
        items = [(short_gloss(s["gloss"]), None) for s in blocks[0]["senses"][:2]]
    kept = []
    for g, p in items:  # "to be" · "to be, exist" says the same thing twice
        if not any(g == k or g.startswith(k + ",") for k, _ in kept):
            kept.append((g, p))
    return kept


def glance_html(glance):
    if len(glance) > 1:
        return "<div class=\"glance\">" + " ".join(
            f"<span class=\"g-n\">{i}</span> {escape(g)}"
            + (f" <span class=\"g-pos\">{p}</span>" if p else "")
            for i, (g, p) in enumerate(glance, 1)) + "</div>"
    return f"<div class=\"glance\">{escape(glance[0][0])}</div>" if glance else ""


def concept_glance(c):
    """skal → 'am / is going to · must · shall I…?' from the concept's uses."""
    seen, out = set(), []
    for u in c.get("uses", [])[:4]:
        g = short_gloss(u["en"]).split(", ")[0].strip()
        if g and g not in seen:
            seen.add(g)
            out.append((g, None))
    return out[:3]


def concept_html(c):
    """Curated "learn it as Danish" box for words with no one English
    equivalent (skal, vil, blive, hygge…): data/curated/concepts.json."""
    uses = "".join(
        f"<li><span class=\"c-when\">{escape(u['when'])}</span> "
        f"<span class=\"c-en\">{escape(u['en'])}</span>"
        + (f"<div class=\"example\"><span class=\"ex-da\">{escape(u['da'])}</span> "
           f"<span class=\"ex-en\">{escape(u['da_en'])}</span></div>" if u.get("da") else "")
        + "</li>" for u in c.get("uses", []))
    note = f"<div class=\"c-note\">{escape(c['note'])}</div>" if c.get("note") else ""
    return (f"<div class=\"concept\"><div class=\"c-head\">{escape(c['summary'])}</div>"
            f"<ul>{uses}</ul>{note}</div>")


NOUN_CUES = "en|et|den|det|de|var|er|som|blev|bliver|min|mit|din|dit|hans|hendes|sin|sit|vores|jeres|deres|god|gode|ny|nye"


def own_reading_example(ex, word, ref, b0, danish):
    """Which reading an AI example illustrates, when an inflected-form reading
    leads: 'Toget kører klokken ni' uses the noun's own form (toget), and in
    'Hans far var arbejder' the word follows var, so both belong to the
    noun, not to the verb reading above it."""
    if ref["pos"] == b0["pos"]:
        return False
    text = ex["da"].lower()
    other = {f for b in danish.get(ref["of"], []) for f in (b.get("infl") or {}).values()}
    own_forms = {f.lower() for f in (b0.get("infl") or {}).values()} - {word.lower()} - other
    if any(re.search(rf"\b{re.escape(f)}\b", text) for f in own_forms):
        return True
    return b0["pos"] == "noun" and bool(
        re.search(rf"\b(?:{NOUN_CUES})\s+(?:\w+\s+)??{re.escape(word.lower())}\b", text))


def header_gloss(gloss):
    """'worker, workman, laborer, labourer' -> 'worker, workman', but keep an
    explanation: 'aware (only in blive var = notice)'."""
    main, paren, rest = gloss.partition(" (")
    return ", ".join(re.split(r"[,;] ", main)[:2]) + (paren + rest if paren else "")


def gotcha_html(text):
    return ("<div class=\"gotcha\"><span class=\"gotcha-head\">⚠️ Gotcha</span> "
            f"{escape(text)}</div>")


def pos_tag(pos):
    name = POS_NAMES.get(pos, pos)
    return f"<span class=\"r-pos\">{escape(name)}</span> " if name else ""


def lead_html(ref, danish, id_of, word):
    """The reading that leads an entry (arbejder = present tense of arbejde):
    a header, then that word's forms with this one underlined."""
    lemma = ref["of"]
    blocks = danish.get(lemma, [])
    b = next((x for x in blocks if x["pos"] == ref["pos"]), blocks[0] if blocks else None)
    meaning = f" — {escape(short_gloss(b['senses'][0]['gloss']))}" if b and b["senses"] else ""
    link = (f"<a href=\"x-dictionary:r:{id_of[lemma]}\">{escape(lemma)}</a>"
            if lemma in id_of else escape(lemma))
    head = (f"<div class=\"reading\">{pos_tag(ref['pos'])}"
            f"{escape(ref['label'])} of {link}{meaning}</div>")
    # the forms row, as also_html builds it
    return head + also_html(ref, danish, id_of, word=word).split("</div>", 1)[1]


def also_html(ref, danish, id_of, word=None):
    """'also: past tense of være (to be)'. With word: also the other word's
    forms, this one in bold (arbejder → at arbejde · **arbejder** · …)."""
    lemma = ref["of"]
    blocks = danish.get(lemma, [])
    b = next((x for x in blocks if x["pos"] == ref["pos"]), blocks[0] if blocks else None)
    meaning = f" ({escape(short_gloss(b['senses'][0]['gloss']))})" if b and b["senses"] else ""
    link = (f"<a href=\"x-dictionary:r:{id_of[lemma]}\">{escape(lemma)}</a>"
            if lemma in id_of else escape(lemma))
    out = (f"<div class=\"also\"><span class=\"also-head\">also</span> "
           f"{escape(ref['label'])} of {link}{meaning}</div>")
    cells = form_cells(lemma, b) if word and b and b["pos"] == ref["pos"] else []
    if cells and ref["label"] == "command form" and (b.get("infl") or {}).get("imp"):
        english = english_mod.verb_forms(b["senses"][0]["gloss"])
        under = english[0].removeprefix("to ") + "!" if english else "command"
        cells.append((b["infl"]["imp"] + "!", under, not english))
        word += "!"
    if cells:
        out += forms_html(cells, with_under=True, highlight=word)
    return out


def meta_html(b, b0, top, show_pos=True):
    pos = POS_NAMES.get(b["pos"], b["pos"])
    meta = []
    if pos and show_pos:
        meta.append(f"<span class=\"pos\">{escape(pos)}</span>")
    if b.get("gender") and b["pos"] == "noun":
        g = "neuter (et)" if b["gender"] == "et" else "common (en)"
        meta.append(f"<span class=\"gender\">{g}</span>")
    if b.get("plural") and not (b.get("infl") or {}).get("pl"):
        meta.append(f"<span class=\"plural\">plural: {escape(b['plural'])}</span>")
    if b.get("ipa"):
        meta.append(f"<span class=\"ipa\">{escape(b['ipa'])}</span>")
    if top and b0.get("sounds_like"):
        meta.append(f"<span class=\"sounds\">sounds like “{escape(b0['sounds_like'])}”"
                    f"<span class=\"ai-mini\">✦</span></span>")
    if top and b0.get("spoken"):
        meta.append(f"<span class=\"sounds\">in fast speech: “{escape(b0['spoken'])}”"
                    f"<span class=\"ai-mini\">✦</span></span>")
    return f"<div class=\"meta\">{' · '.join(meta)}</div>" if meta else ""


def examples_html(examples):
    out = ""
    for ex in examples:
        cls = "example ai" if ex.get("ai") else "example"
        en = f"<span class=\"ex-en\">{escape(ex['en'])}</span>" if ex.get("en") else ""
        out += f"<div class=\"{cls}\"><span class=\"ex-da\">{escape(ex['da'])}</span> {en}</div>"
    return out


# Wiktionary sometimes quotes whole paragraphs of literature as examples
MAX_EXAMPLE_CHARS = 160


def senses_html(b, skip=frozenset()):
    items = []
    for s in b["senses"]:
        exs = [ex for ex in s.get("examples", [])
               if id(ex) not in skip and len(ex["da"]) <= MAX_EXAMPLE_CHARS]
        items.append(f"<li>{escape(s['gloss'])}{examples_html(exs)}</li>")
    return "<ol class=\"senses\">" + "".join(items) + "</ol>"


def form_entry(n, form, refs, danish, id_of, form_examples):
    """A small entry for an inflected form that isn't a headword (sagde).
    Look Up opens one entry and can't tell it which form was selected, and
    its popup can't follow links, so this entry stands on its own: the same
    lead reading as arbejder gets (header, the base word's forms with this
    one underlined), sentences using this exact form, then all of the base
    word's meanings and its gotcha."""
    ref = refs[0]
    lemma = ref["of"]
    lemma_blocks = danish[lemma]
    b = next((x for x in lemma_blocks if x["pos"] == ref["pos"]), lemma_blocks[0])
    parts = [f"<d:index d:value={quoteattr(form)} d:title={quoteattr(form)}/>",
             f"<h1>{escape(form)}</h1>",
             lead_html(ref, danish, id_of, form)]
    # sentences written for this form; else the base word's own examples
    # that happen to use it
    shown = form_examples.get(form, [])[:2]
    if not shown:
        shown = [ex for x in lemma_blocks if x["pos"] == ref["pos"] for s in x["senses"]
                 for ex in s.get("examples", [])
                 if len(ex["da"]) <= MAX_EXAMPLE_CHARS
                 and re.search(rf"\b{re.escape(form)}\b", ex["da"], re.I)][:2]
    if shown:
        parts.append(f"<div class=\"examples lead\">{examples_html(shown)}</div>")
    # the base word's meanings, short: everyday senses only, no repeats
    brief = []
    for sense in b["senses"]:
        g = short_gloss(sense["gloss"])
        if not sense.get("tags") and g and g not in brief:
            brief.append(g)
    parts.append("<ol class=\"senses brief\">"
                 + "".join(f"<li>{escape(g)}</li>" for g in brief[:4]) + "</ol>")
    if lemma_blocks[0] is b and b.get("gotcha"):
        parts.append(gotcha_html(b["gotcha"]))
    parts += [also_html(r, danish, id_of) for r in refs[1:] if r["of"] != lemma]
    if lemma in id_of:
        parts.append(f"<div class=\"full-entry\">Full entry: "
                     f"<a href=\"x-dictionary:r:{id_of[lemma]}\">{escape(lemma)}</a></div>")
    body = "\n".join(parts)
    return f"<d:entry id=\"fo_{n}\" d:title={quoteattr(form)}>\n{body}\n</d:entry>"


def danish_entry(n, word, blocks, id_of, form_of, danish, headwords):
    """Top of the entry is what the Look Up popup shows before its "more"
    link: headword, the 'also: past tense of …' readings that matter most,
    the meaning at a glance, then the forms with their English. The full
    numbered senses and examples follow."""
    eid = f"da_{n}"
    all_forms = sorted({f for b in blocks for f in b.get("forms", [])})
    parts = ["\n".join(indexes(word, all_forms, headwords))]
    parts.append(f"<h1>{escape(word)}</h1>")
    b0 = blocks[0]
    refs = form_of.get(word, [])[:2]

    # An entry is one or more readings, each shown the same way: a header
    # (part of speech + meaning), its forms, its examples. When an
    # inflected-form reading leads (arbejder = present tense of arbejde, læs
    # = command form of læse), it is the first reading, and the AI examples
    # and gotcha, written for that everyday reading, go with it.
    lead = [r for r in refs if r.get("first")]
    lead_form = bool(lead)
    lead_examples = []
    ai_examples = [ex for s in b0["senses"] for ex in s.get("examples", []) if ex.get("ai")]
    concept = b0.get("concept")
    lead_gotcha = lead_form and not concept and b0.get("gotcha")
    if concept:
        # a one-line meaning first: when several entries match, the popup
        # shows only the first two lines of each
        glance = (concept_glance(concept) if lead_form else None) or glance_items(blocks)
        parts.append(glance_html(glance))
        parts.append(concept_html(concept))
        parts.append(meta_html(b0, b0, top=True))
    elif lead_form:
        parts.append(lead_html(lead[0], danish, id_of, word))
        lead_examples = [ex for ex in ai_examples
                         if not own_reading_example(ex, word, lead[0], b0, danish)]
        if lead_examples:
            parts.append(f"<div class=\"examples lead\">{examples_html(lead_examples)}</div>")
        if lead_gotcha:
            parts.append(gotcha_html(b0["gotcha"]))
        parts += [also_html(r, danish, id_of) for r in lead[1:] if r["of"] != lead[0]["of"]]
        parts.append("<hr class=\"reading-sep\"/>")
        # the word's own reading: full glosses when there are only one or two
        # (var = "aware (only in blive var = notice)"), so no list repeats them
        own = ([(header_gloss(s["gloss"]), None) for s in b0["senses"]] if len(b0["senses"]) <= 2
               else glance_items(blocks))
        parts.append(f"<div class=\"reading\">{pos_tag(b0['pos'])}"
                     + " · ".join(escape(g) for g, _ in own) + "</div>")
        parts.append(meta_html(b0, b0, top=True, show_pos=False))
    else:
        parts.append(glance_html(glance_items(blocks)))
        parts.append(meta_html(b0, b0, top=True))
    cells = form_cells(word, b0)
    if cells:
        parts.append(forms_html(cells, with_under=True))
    lead_lemmas = {r["of"] for r in lead}
    parts += [also_html(r, danish, id_of) for r in refs
              if not r.get("first") and r["of"] not in lead_lemmas and also_worth_showing(r, danish)]

    if b0.get("false_friend"):
        parts.append(f"<div class=\"falsefriend\"><span class=\"ff-head\">🚨 Common English mistake</span> "
                     f"{escape(b0['false_friend'])}</div>")

    for i, b in enumerate(blocks):
        if i > 0:
            parts.append("<hr class=\"block-sep\"/>")
            parts.append(meta_html(b, b0, top=False))
            cells = form_cells(word, b)
            if cells:
                parts.append(forms_html(cells, with_under=False))
        shown = {id(ex) for ex in lead_examples} if i == 0 else set()
        own_examples = [ex for s in b["senses"] for ex in s.get("examples", []) if id(ex) not in shown]
        if i == 0 and lead_form and not concept and len(b["senses"]) <= 2:
            # the reading's header already shows these glosses: examples only
            if own_examples:
                parts.append(f"<div class=\"examples\">{examples_html(own_examples)}</div>")
        elif i == 0 and not own_examples and len(b["senses"]) <= 2 and all(
                short_gloss(s["gloss"]) == s["gloss"] for s in b["senses"]):
            pass  # the at-a-glance line already says it all
        else:
            parts.append(senses_html(b, skip=shown))
        if b.get("gotcha") and not (i == 0 and lead_gotcha):
            parts.append(gotcha_html(b["gotcha"]))

    if b0.get("chunks"):
        items = "".join(f"<li>{escape(c)}</li>" for c in b0["chunks"])
        parts.append(f"<div class=\"chunks\"><span class=\"chunks-head\">🧩 In phrases</span>"
                     f"<ul>{items}</ul></div>")

    if b0.get("usage_note"):
        parts.append(f"<div class=\"usagenote\">📌 {escape(b0['usage_note'])}</div>")

    for c in b0.get("confusables", []):
        other = c["with"]
        other_id = id_of.get(other)
        label = (f"<a href=\"x-dictionary:r:{other_id}\">{escape(other)}</a>"
                 if other_id else escape(other))
        parts.append(f"<div class=\"confuse\"><span class=\"confuse-head\">🔀 Don't confuse with "
                     f"{label}</span> {escape(c['rule'])}</div>")

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
<h1><b>Dansk-English Dictionary</b></h1>
<p>Danish ⇄ English for macOS Look Up. Data from Wiktionary (via Wiktextract/kaikki.org, CC BY-SA 4.0), FreeDict, and the Danish Central Word Register (COR, CC0). Example sentences and “gotcha” notes for the most common words are AI-generated and clearly labeled.</p>
<p>Source &amp; issues: github.com/dharanshuman/danish-english-dictionary-macos</p>
</d:entry>"""


def main():
    data_path = ROOT / "data" / "enriched.json"
    if not data_path.exists():
        data_path = ROOT / "data" / "normalized.json"
        print("note: data/enriched.json not found, building without AI content")
    data = json.loads(data_path.read_text(encoding="utf-8"))

    sorted_danish = sorted(data["danish"].items())
    id_of = {word: f"da_{n}" for n, (word, _) in enumerate(sorted_danish)}

    # inflected forms with an entry of their own (config.json form_entries:
    # a list of forms, or "all")
    wanted = json.loads((ROOT / "config.json").read_text()).get("form_entries", [])
    form_only = data.get("form_only", {})
    form_words = [w for w in (sorted(form_only) if wanted == "all" else wanted)
                  if w in form_only and w not in data["danish"]]  # stubs like har
    headwords = set(data["danish"]) | set(form_words)

    entries = [FRONT_MATTER]
    for n, (word, blocks) in enumerate(sorted_danish):
        if word.startswith("-") or word.endswith("-"):
            # Look Up ignores the hyphen, so "-er" would answer every lookup
            # of "er"; affixes aren't worth that to a learner
            continue
        entries.append(danish_entry(n, word, blocks, id_of, data.get("form_of", {}),
                                    data["danish"], headwords))
    for n, form in enumerate(form_words):
        entries.append(form_entry(n, form, form_only[form], data["danish"], id_of,
                                  data.get("form_examples", {})))
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
    print(f"form entries: {len(form_words):,}")
    n_da = len(data["danish"])
    n_en = len(data["english"])
    print(f"wrote {SRC} ({SRC.stat().st_size:,} bytes): "
          f"{n_da:,} Danish + {n_en:,} English entries")


if __name__ == "__main__":
    sys.exit(main())
