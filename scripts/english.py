"""Tiny English inflector for the forms line, so each Danish form can show
its English: at læse / læser / læste / har læst -> to read / reads / read /
has read, and et læs / læsset / læs / læssene -> a load / the load / loads /
the loads.

Everything returns None when the gloss isn't a plain enough verb or noun to
inflect safely; the caller then shows grammar labels instead.
"""
import re

# base: (3rd person present, past, past participle)
IRREGULAR_VERBS = {
    "be": ("is", "was", "been"), "have": ("has", "had", "had"),
    "do": ("does", "did", "done"), "go": ("goes", "went", "gone"),
    "say": ("says", "said", "said"), "make": ("makes", "made", "made"),
    "get": ("gets", "got", "got"), "know": ("knows", "knew", "known"),
    "think": ("thinks", "thought", "thought"), "take": ("takes", "took", "taken"),
    "see": ("sees", "saw", "seen"), "come": ("comes", "came", "come"),
    "give": ("gives", "gave", "given"), "find": ("finds", "found", "found"),
    "tell": ("tells", "told", "told"), "become": ("becomes", "became", "become"),
    "leave": ("leaves", "left", "left"), "feel": ("feels", "felt", "felt"),
    "bring": ("brings", "brought", "brought"), "begin": ("begins", "began", "begun"),
    "keep": ("keeps", "kept", "kept"), "hold": ("holds", "held", "held"),
    "write": ("writes", "wrote", "written"), "stand": ("stands", "stood", "stood"),
    "hear": ("hears", "heard", "heard"), "let": ("lets", "let", "let"),
    "mean": ("means", "meant", "meant"), "set": ("sets", "set", "set"),
    "meet": ("meets", "met", "met"), "run": ("runs", "ran", "run"),
    "pay": ("pays", "paid", "paid"), "sit": ("sits", "sat", "sat"),
    "speak": ("speaks", "spoke", "spoken"), "lie": ("lies", "lay", "lain"),
    "lead": ("leads", "led", "led"), "read": ("reads", "read", "read"),
    "grow": ("grows", "grew", "grown"), "lose": ("loses", "lost", "lost"),
    "fall": ("falls", "fell", "fallen"), "send": ("sends", "sent", "sent"),
    "build": ("builds", "built", "built"), "understand": ("understands", "understood", "understood"),
    "draw": ("draws", "drew", "drawn"), "break": ("breaks", "broke", "broken"),
    "spend": ("spends", "spent", "spent"), "cut": ("cuts", "cut", "cut"),
    "rise": ("rises", "rose", "risen"), "drive": ("drives", "drove", "driven"),
    "buy": ("buys", "bought", "bought"), "wear": ("wears", "wore", "worn"),
    "choose": ("chooses", "chose", "chosen"), "seek": ("seeks", "sought", "sought"),
    "throw": ("throws", "threw", "thrown"), "catch": ("catches", "caught", "caught"),
    "deal": ("deals", "dealt", "dealt"), "win": ("wins", "won", "won"),
    "forget": ("forgets", "forgot", "forgotten"), "sell": ("sells", "sold", "sold"),
    "fight": ("fights", "fought", "fought"), "teach": ("teaches", "taught", "taught"),
    "eat": ("eats", "ate", "eaten"), "drink": ("drinks", "drank", "drunk"),
    "sing": ("sings", "sang", "sung"), "swim": ("swims", "swam", "swum"),
    "fly": ("flies", "flew", "flown"), "sleep": ("sleeps", "slept", "slept"),
    "steal": ("steals", "stole", "stolen"), "hide": ("hides", "hid", "hidden"),
    "shoot": ("shoots", "shot", "shot"), "ride": ("rides", "rode", "ridden"),
    "hit": ("hits", "hit", "hit"), "put": ("puts", "put", "put"),
    "shut": ("shuts", "shut", "shut"), "hurt": ("hurts", "hurt", "hurt"),
    "cost": ("costs", "cost", "cost"), "bite": ("bites", "bit", "bitten"),
    "blow": ("blows", "blew", "blown"), "freeze": ("freezes", "froze", "frozen"),
    "forgive": ("forgives", "forgave", "forgiven"), "shake": ("shakes", "shook", "shaken"),
    "wake": ("wakes", "woke", "woken"), "show": ("shows", "showed", "shown"),
    "sink": ("sinks", "sank", "sunk"), "ring": ("rings", "rang", "rung"),
    "lend": ("lends", "lent", "lent"), "bend": ("bends", "bent", "bent"),
    "light": ("lights", "lit", "lit"), "feed": ("feeds", "fed", "fed"),
    "hang": ("hangs", "hung", "hung"), "dig": ("digs", "dug", "dug"),
    "stick": ("sticks", "stuck", "stuck"), "strike": ("strikes", "struck", "struck"),
    "swear": ("swears", "swore", "sworn"), "tear": ("tears", "tore", "torn"),
    "bear": ("bears", "bore", "borne"), "shit": ("shits", "shat", "shat"),
    "sing": ("sings", "sang", "sung"), "think of": ("thinks of", "thought of", "thought of"), "beat": ("beats", "beat", "beaten"),
    "bet": ("bets", "bet", "bet"), "bind": ("binds", "bound", "bound"),
    "bleed": ("bleeds", "bled", "bled"), "breed": ("breeds", "bred", "bred"),
    "flee": ("flees", "fled", "fled"), "grind": ("grinds", "ground", "ground"),
    "kneel": ("kneels", "knelt", "knelt"), "lay": ("lays", "laid", "laid"),
    "quit": ("quits", "quit", "quit"), "shine": ("shines", "shone", "shone"),
    "slide": ("slides", "slid", "slid"), "spin": ("spins", "spun", "spun"),
    "spread": ("spreads", "spread", "spread"), "spring": ("springs", "sprang", "sprung"),
    "sting": ("stings", "stung", "stung"), "stink": ("stinks", "stank", "stunk"),
    "swing": ("swings", "swung", "swung"), "weep": ("weeps", "wept", "wept"),
    "wind": ("winds", "wound", "wound"), "dream": ("dreams", "dreamt", "dreamt"),
    "smell": ("smells", "smelled", "smelled"), "burn": ("burns", "burned", "burned"),
    "learn": ("learns", "learned", "learned"), "lie down": ("lies down", "lay down", "lain down"),
    "undergo": ("undergoes", "underwent", "undergone"), "withdraw": ("withdraws", "withdrew", "withdrawn"),
    "overcome": ("overcomes", "overcame", "overcome"), "arise": ("arises", "arose", "arisen"),
    "forbid": ("forbids", "forbade", "forbidden"), "mistake": ("mistakes", "mistook", "mistaken"),
}
# modal and odd verbs whose English has no regular forms
NO_FORMS = {"can", "could", "must", "shall", "should", "will", "would", "may", "might",
            "ought", "need", "dare", "used"}

IRREGULAR_PLURALS = {
    "man": "men", "woman": "women", "child": "children", "person": "people",
    "foot": "feet", "tooth": "teeth", "mouse": "mice", "goose": "geese",
    "knife": "knives", "wife": "wives", "life": "lives", "leaf": "leaves",
    "half": "halves", "wolf": "wolves", "shelf": "shelves", "thief": "thieves",
    "loaf": "loaves", "calf": "calves", "sheep": "sheep", "fish": "fish",
    "deer": "deer", "ox": "oxen", "louse": "lice", "crisis": "crises",
    "analysis": "analyses", "thesis": "theses", "phenomenon": "phenomena",
    "criterion": "criteria", "potato": "potatoes", "tomato": "tomatoes",
    "hero": "heroes", "echo": "echoes", "veto": "vetoes",
}
SILENT_H = ("hour", "honest", "honour", "honor", "heir")
YOU_SOUND = ("uni", "use", "usu", "eu", "one", "once", "ewe")

PLAIN = re.compile(r"[a-z][a-z' -]*")


def head(gloss):
    """'to put, place, set' -> 'to put'; 'goal (something aspired to)' -> 'goal'.
    Keeps capitals (TV, Christmas) but lowercases a sentence-style first letter."""
    g = re.sub(r"\([^)]*\)", "", gloss)
    g = re.split(r"[;,:/]", g)[0].strip().rstrip(".")
    if g[:1].isupper() and g[1:2].islower():
        first = g.split()[0]
        if first.lower() in ("a", "an", "the", "to"):
            g = g[0].lower() + g[1:]
    if not PLAIN.fullmatch(g.lower()) or len(g.split()) > 4:
        return None
    return g


def _s(word):
    if re.search(r"(s|x|z|ch|sh)$", word):
        return word + "es"
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    if re.search(r"[^aeiou]o$", word):
        return word + "es"
    return word + "s"


def _ed(word):
    if word.endswith("e"):
        return word + "d"
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ied"
    if re.fullmatch(r"[^aeiou]*[aeiou][bdgmnpt]", word):  # stop -> stopped
        return word + word[-1] + "ed"
    return word + "ed"


def verb_forms(gloss):
    """'to read' -> ('to read', 'reads', 'read', 'has read') or None."""
    h = head(gloss)
    if not h:
        return None
    h = h.removeprefix("to ").strip()
    if not h:
        return None
    words = h.lower().split()
    two = " ".join(words[:2])
    if two in IRREGULAR_VERBS:  # "lie down"
        verb, rest = two, words[2:]
    else:
        verb, rest = words[0], words[1:]
    # "-ing" words are usually not base verbs (being, making), but sing and
    # bring are
    if verb in NO_FORMS or (verb.endswith("ing") and len(verb) > 5 and verb not in IRREGULAR_VERBS):
        return None
    if verb in IRREGULAR_VERBS:
        third, past, part = IRREGULAR_VERBS[verb]
    else:
        third, past, part = _s(verb), _ed(verb), _ed(verb)
    tail = (" " + " ".join(rest)) if rest else ""
    return (f"to {verb}{tail}", f"{third}{tail}", f"{past}{tail}", f"has {part}{tail}")


def article(noun):
    noun = noun.lower()
    if noun.startswith(SILENT_H):
        return "an"
    if noun.startswith(YOU_SOUND):
        return "a"
    return "an" if noun[0] in "aeiou" else "a"


def plural(phrase):
    words = phrase.split()
    i = words.index("of") - 1 if "of" in words[1:] else len(words) - 1  # blocks of flats
    w = words[i]
    if w.endswith("man") and w not in ("human", "german", "roman", "shaman"):
        words[i] = w[:-3] + "men"  # gentleman -> gentlemen
    else:
        words[i] = IRREGULAR_PLURALS.get(w) or _s(w)
    return " ".join(words)


def noun_forms(gloss, countable=True):
    """'load, lot' -> ('a load', 'the load', 'loads', 'the loads') or None.
    Uncountable (no Danish plural): 'held' -> ('luck', 'the luck')."""
    h = head(gloss)
    if h and h.lower().startswith(("a ", "an ")):  # Wiktionary's "A woman."
        h = h.split(" ", 1)[1]
    if not h or h.lower().startswith(("to ", "the ")):
        return None
    if not countable:
        return (h, f"the {h}")
    pl = plural(h)
    return (f"{article(h)} {h}", f"the {h}", pl, f"the {pl}")
