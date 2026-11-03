"""Style checks for prose, plus readability numbers. No UI code.

The checks are heuristics, not grammar: they point at places worth a second
look (a passive construction, a filler word, a sentence that runs long) and
leave the decision to the writer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from inkmill.markup import mask_non_prose


@dataclass
class Finding:
    start: int
    end: int
    rule: str
    message: str


BE = r"(?:am|is|are|was|were|be|been|being)"
IRREGULAR = (
    "arisen awoken beaten become begun bent bet bitten bled blown broken bred brought built burnt bought caught "
    "chosen clung come cost crept cut dealt dug done drawn dreamt driven drunk eaten fallen fed felt fought found "
    "fled flung flown forbidden forgotten forgiven frozen gotten given gone ground grown hung had heard hidden hit "
    "held hurt kept knelt known laid led leapt left lent let lain lit lost made meant met paid put quit read ridden "
    "rung risen run said seen sought sold sent set shaken shed shone shot shown shrunk shut sung sunk sat slain slept "
    "slid slung spoken sped spent spun split spread sprung stood stolen stuck stung struck strung sworn swept swum "
    "swung taken taught torn told thought thrown thrust trodden understood woken worn woven wept won wound written"
).split()
PASSIVE = re.compile(rf"\b{BE}\s+(?:\w+ly\s+)?(\w+ed|{'|'.join(IRREGULAR)})\b", re.IGNORECASE)

NOT_ADVERBS = set(
    "only family early likely lovely holy ugly belly bully fly reply supply apply rely ally italy july jelly "
    "silly hilly chilly daily weekly monthly yearly friendly lonely costly elderly orderly deadly lively curly "
    "ally anomaly assembly butterfly comply imply multiply oily rally sly tally emily molly billy sally holly "
    "kelly lily polly reilly".split()
)
ADVERB = re.compile(r"\b[A-Za-z]{3,}ly\b")

FILLER = [
    "very", "really", "just", "quite", "rather", "somewhat", "actually", "basically", "literally", "totally",
    "simply", "certainly", "definitely", "extremely", "incredibly", "pretty much", "sort of", "kind of",
    "a bit", "a little", "in fact", "of course", "needless to say",
]
WORDY = {
    "in order to": "to",
    "due to the fact that": "because",
    "at this point in time": "now",
    "in the event that": "if",
    "for the purpose of": "for",
    "in spite of the fact that": "although",
    "has the ability to": "can",
    "is able to": "can",
    "a large number of": "many",
    "the majority of": "most",
    "at the present time": "now",
    "in close proximity to": "near",
    "each and every": "each",
    "first and foremost": "first",
    "it is important to note that": "(cut it)",
    "began to": "(often just the verb)",
    "started to": "(often just the verb)",
}
CLICHES = [
    "all of a sudden", "at the end of the day", "avoid it like the plague", "better late than never",
    "dead as a doornail", "easier said than done", "few and far between", "in the nick of time",
    "last but not least", "only time will tell", "read between the lines", "the calm before the storm",
    "time stood still", "without a doubt", "heart skipped a beat", "let out a breath", "a chill ran down",
    "blood ran cold", "in the blink of an eye", "little did", "for all intents and purposes",
]
WEAK_OPENERS = re.compile(r"(?:^|(?<=[.!?]\s))(There (?:is|are|was|were)|It (?:is|was))\b")

RULE_NAMES = {
    "passive": "Passive voice",
    "adverb": "Adverb",
    "filler": "Filler word",
    "wordy": "Wordy phrase",
    "cliche": "Cliche",
    "repeat": "Repeated word",
    "long": "Long sentence",
    "opener": "Weak opener",
    "starts": "Repeated sentence start",
}

SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+[\"')\]]*|\n|$)")
WORDS = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def _phrases(masked: str, phrases, rule: str, message) -> list[Finding]:
    found = []
    for phrase in phrases:
        for m in re.finditer(r"\b" + re.escape(phrase) + r"\b", masked, re.IGNORECASE):
            found.append(Finding(m.start(), m.end(), rule, message(phrase)))
    return found


def check(text: str, *, rules: set[str] | None = None, long_sentence: int = 35) -> list[Finding]:
    masked = mask_non_prose(text)
    # Headings are titles, not sentences.
    masked = re.sub(r"^#{1,6}[^\n]*", lambda m: " " * len(m.group()), masked, flags=re.MULTILINE)
    on = rules or set(RULE_NAMES)
    found: list[Finding] = []
    if "passive" in on:
        for m in PASSIVE.finditer(masked):
            found.append(Finding(m.start(), m.end(), "passive", "Passive: say who acts"))
    if "adverb" in on:
        for m in ADVERB.finditer(masked):
            if m.group().lower() not in NOT_ADVERBS:
                found.append(Finding(m.start(), m.end(), "adverb", "Adverb: is a stronger verb hiding here?"))
    if "filler" in on:
        found += _phrases(masked, FILLER, "filler", lambda p: f"Filler: does {p!r} add anything?")
    if "wordy" in on:
        found += _phrases(masked, WORDY, "wordy", lambda p: f"Wordy: try {WORDY[p]!r}")
    if "cliche" in on:
        found += _phrases(masked, CLICHES, "cliche", lambda p: "Cliche: say it your own way")
    if "repeat" in on:
        for m in re.finditer(r"\b(\w+)\s+(\1)\b", masked, re.IGNORECASE):
            if m.group(1).lower() not in ("had", "that", "is"):
                found.append(Finding(m.start(2), m.end(2), "repeat", f"Repeated word: {m.group(1)!r}"))
    if "opener" in on:
        for m in WEAK_OPENERS.finditer(masked):
            found.append(Finding(m.start(1), m.end(1), "opener", "Weak opener: lead with the subject"))
    sentences = [(m.start(), m.end(), m.group()) for m in SENTENCE.finditer(masked) if WORDS.search(m.group())]
    if "long" in on:
        for start, end, sentence in sentences:
            count = len(WORDS.findall(sentence))
            if count > long_sentence:
                lead = len(sentence) - len(sentence.lstrip())
                found.append(Finding(start + lead, end, "long", f"Long sentence: {count} words"))
    if "starts" in on:
        run: list[tuple[int, str]] = []
        for start, _end, sentence in sentences:
            first = WORDS.search(sentence)
            word = first.group().lower() if first else ""
            if run and run[-1][1] == word:
                run.append((start + first.start(), word))
            else:
                run = [(start + first.start(), word)] if first else []
            if len(run) == 3:
                pos = run[-1][0]
                found.append(Finding(pos, pos + len(word), "starts", f"Three sentences in a row start with {word!r}"))
    return sorted(found, key=lambda f: (f.start, f.rule))


def syllables(word: str) -> int:
    word = word.lower().strip("'")
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", word)))


def readability(text: str) -> dict[str, float]:
    masked = mask_non_prose(text)
    masked = re.sub(r"^#{1,6}[^\n]*", " ", masked, flags=re.MULTILINE)
    words = WORDS.findall(masked)
    sentences = [s for s in SENTENCE.findall(masked) if WORDS.search(s)]
    w, s = len(words), max(1, len(sentences))
    syl = sum(syllables(x) for x in words)
    if not w:
        return {"words": 0, "sentences": 0, "avg_sentence": 0, "ease": 0, "grade": 0, "reading_minutes": 0}
    return {
        "words": w,
        "sentences": len(sentences),
        "avg_sentence": w / s,
        "ease": 206.835 - 1.015 * (w / s) - 84.6 * (syl / w),
        "grade": 0.39 * (w / s) + 11.8 * (syl / w) - 15.59,
        "reading_minutes": w / 238,
    }
