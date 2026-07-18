# Danish ⇄ English dictionary for macOS

A native dictionary for the built-in macOS **Dictionary.app** and the
system **Look Up** panel (three-finger tap, Force Touch, or Ctrl-Cmd-D on
any word, in any app).

Look up a Danish word and you get:

- the English translation(s), numbered when there are several
- part of speech, and for nouns the gender (**en**/**et**) and plural
- pronunciation (IPA) where available
- example sentences (Danish + English)
- a short **⚠️ Gotcha** note for tricky words — false friends
  (*eventuelt* ≠ *eventually*), surprising gender, silent d, and so on

It works in **both directions**: looking up *hus* or *house* both give you
an answer. It also understands **inflected forms** — looking up *husene*
("the houses") finds *hus*, because every conjugated and declined form from
the official Danish word register (COR) is indexed.

> **Screenshot placeholder** — add a screenshot of the Look Up panel here.

## Install (easy way)

1. Download `Danish-English.dictionary.zip` from the
   [Releases](../../releases) page.
2. Unzip it.
3. Move the `Danish-English.dictionary` folder into `~/Library/Dictionaries`
   (in Finder: Go → Go to Folder… → type `~/Library/Dictionaries`).
4. Quit and reopen **Dictionary.app**, open **Settings…**, and tick
   **Danish-English**. Drag it up the list to control its order in Look Up.

## Build from source

You need macOS with the Xcode Command Line Tools (`xcode-select --install`).
Everything else is plain Python 3 (standard library only) and `make`.

```bash
git clone https://github.com/dharanshuman/danish-english-dictionary-macos.git
cd danish-english-dictionary-macos

# 1. Apple's Dictionary Development Kit (build tool, not committed here)
git clone https://github.com/SebastianSzturo/Dictionary-Development-Kit.git tools/Dictionary-Development-Kit

# 2. Download the open data sources (~120 MB)
python3 scripts/fetch_data.py

# 3. Normalize everything into one JSON file
python3 scripts/parse_sources.py

# 4. Merge in the AI-written examples/notes (already cached in data/ai_cache/)
python3 scripts/enrich.py

# 5. Generate the dictionary XML and compile it
python3 scripts/build_xml.py
cd src && make && make install
```

Then quit and reopen Dictionary.app and enable **Danish-English** in
Settings.

## How it's put together

| Step | Script | What it does |
|---|---|---|
| Fetch | `scripts/fetch_data.py` | Downloads all sources into `data/raw/` (skips files it already has) |
| Parse | `scripts/parse_sources.py` | Merges Wiktionary + FreeDict + COR into `data/normalized.json` |
| Enrich | `scripts/enrich.py` | Adds cached AI examples/notes for the most common words |
| Build | `scripts/build_xml.py` | Writes `src/DanishEnglish.xml` in Apple's dictionary format |
| Compile | `src/Makefile` | Runs Apple's Dictionary Development Kit to make the `.dictionary` bundle |

The English→Danish direction is built by *inverting* the Danish→English
translations, so it has broad coverage (~26,000 English headwords) even
though the FreeDict English→Danish file itself is tiny.

## The AI-generated parts (and how to expand them)

Only the **~1,000 most common Danish words** (ranked by a subtitle-based
frequency list) carry AI-written example sentences and gotcha notes. All of
that content is cached as plain JSON in `data/ai_cache/`, committed to the
repo, and **clearly labeled in the dictionary** with a purple
"AI-generated" tag — treat it as helpful but fallible. It never replaces
real Wiktionary data; it only fills gaps.

To expand coverage: raise `tier1_size` in `config.json`, run
`python3 scripts/enrich.py --list` to get the words that still need
content (`data/tier1_words.json`), generate cache entries for them in the
same JSON shape as the existing files in `data/ai_cache/`, then re-run
steps 4–5 above.

## Data sources & licensing

Full details and credits are in [NOTICE](NOTICE).

| Source | What we use | License |
|---|---|---|
| [Wiktionary via Wiktextract/kaikki.org](https://kaikki.org/dictionary/Danish/) | words, meanings, gender, forms, examples | CC BY-SA 4.0 |
| [FreeDict dan-eng / eng-dan](https://freedict.org/) | extra bilingual pairs | GPL |
| [COR (ordregister.dk)](https://ordregister.dk/) | inflected forms, noun gender | CC0 |
| [hermitdave FrequencyWords](https://github.com/hermitdave/FrequencyWords) | word frequency ranking | CC BY-SA 4.0 |
| AI (Claude, Anthropic) | examples + gotcha notes for common words | CC BY-SA 4.0, labeled |

**License split:** the *code* is [MIT](LICENSE); the *data* (including the
built dictionary) is [CC BY-SA 4.0](LICENSE-DATA), because Wiktionary's
ShareAlike terms carry over to anything built from it.

## Known limitations

- AI examples and gotcha notes can contain mistakes. They are labeled so
  you always know which parts they are. Corrections welcome!
- Wiktionary's Danish coverage is good but not complete (~25,000 real
  headwords here). It is not a replacement for Den Danske Ordbog.
- Compound words that aren't in the sources won't resolve, even though
  Danish loves gluing words together.
- Only the first sense block of a word gets the AI examples attached.

## Contributing

- **Wrong translation or missing word?** Best fixed upstream on
  [Wiktionary](https://da.wiktionary.org/) — this repo rebuilds from it.
- **Wrong AI example or gotcha?** Edit the matching entry in
  `data/ai_cache/` and open a pull request.
- **Code improvements?** PRs welcome. Keep scripts standard-library-only.
