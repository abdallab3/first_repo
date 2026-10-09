"""Work out what the visitor wants, then score pages against it.

No AI service is involved. The score comes from where the visitor's words show up on a
page (link text, title, address, headings, text), how rare those words are on the site,
whether the page covers every word, and whether the year matches.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

# Words in a request that say what to do, not what to find.
STOPWORDS = set(
    """a an the of to on in at for from by with and or but is are was were be been
    i me my we our you your it its this that these those there here
    find finds finding show shows get gets locate look looking search searching go take bring open
    please can could would should will need want wanna like where what which who how
    page pages subpage subpages section sections link links site sites website websites web url
    info information about""".split()
)

# Groups of words that usually mean nearly the same thing on a website.
SYNONYM_GROUPS = [
    ["calendar", "schedule", "date", "event", "holiday", "term"],
    ["parent", "family", "guardian", "caregiver"],
    ["contact", "email", "phone", "reach", "call"],
    ["lunch", "menu", "meal", "cafeteria", "food", "breakfast"],
    ["job", "career", "employment", "vacancy", "opening", "hiring", "position"],
    ["staff", "faculty", "teacher", "employee", "personnel"],
    ["concern", "complaint", "issue", "report", "bullying", "safety", "grievance"],
    ["admission", "enrollment", "enroll", "register", "registration", "apply", "application"],
    ["transport", "transportation", "bus", "route"],
    ["tuition", "fee", "cost", "price", "pricing", "payment", "billing"],
    ["policy", "handbook", "rule", "guideline", "regulation", "code"],
    ["permit", "license", "licence", "form"],
    ["trash", "garbage", "waste", "recycling", "refuse", "sanitation"],
    ["budget", "finance", "financial", "spending", "fiscal"],
    ["meeting", "agenda", "minutes", "board", "council"],
    ["news", "announcement", "update", "press", "bulletin", "newsletter"],
    ["sport", "athletics", "athletic"],
    ["return", "refund", "exchange", "warranty"],
    ["shipping", "delivery"],
    ["faq", "question", "help", "support", "answer"],
    ["login", "portal", "account", "signin"],
]

WORD = re.compile(r"[^\W_]+", re.UNICODE)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
YEAR_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*[-–—/_]\s*((?:19|20)?\d{2})\b")
SPLIT_BOUNDARIES = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")

DOCUMENT_EXTENSIONS = {
    ".pdf": "pdf", ".doc": "document", ".docx": "document", ".xls": "document",
    ".xlsx": "document", ".ppt": "document", ".pptx": "document", ".csv": "document",
    ".ics": "document", ".odt": "document", ".rtf": "document", ".txt": "document",
}


def stem(word):
    """A very small word-shortener so that 'dates' matches 'date' and 'hiring' matches 'hire'."""
    w = word.lower()
    if len(w) <= 3 or w.isdigit():
        return w
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if w.endswith("ing") and len(w) > 5:
        w = w[:-3]
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def _build_synonyms():
    table = {}
    for group in SYNONYM_GROUPS:
        stems = {stem(w) for w in group}
        for s in stems:
            table.setdefault(s, set()).update(stems - {s})
    return table


SYNONYMS = _build_synonyms()


def _expand_range(match):
    first, second = match.group(1), match.group(2)
    if len(second) == 2:
        second = first[:2] + second
    return {int(first), int(second)}


def years_in(text):
    """Every year mentioned in some text. '2026-27' counts as both 2026 and 2027."""
    text = SPLIT_BOUNDARIES.sub(" ", text)
    found = set()
    for m in YEAR_RANGE.finditer(text):
        found |= _expand_range(m)
    found |= {int(y) for y in YEAR.findall(text)}
    return found


def split_words(text):
    """Lowercase words from text, also splitting camelCase and letter/number joins."""
    return WORD.findall(SPLIT_BOUNDARIES.sub(" ", text).lower())


def stems_of(text):
    return {stem(w) for w in split_words(text)}


@dataclass
class Query:
    raw: str
    terms: list  # stems, in the order asked, no repeats
    words: dict  # stem -> the word the visitor typed
    years: set

    def related(self, term):
        return SYNONYMS.get(term, set())


def parse_query(raw):
    """Turn 'find the 2026 school calendar subpage' into terms and years."""
    raw = (raw or "").strip()
    if len(raw) > 300:
        raise ValueError("That request is too long. Keep it under 300 characters.")
    years = set()
    for m in YEAR_RANGE.finditer(raw):
        years |= _expand_range(m)
    text = YEAR_RANGE.sub(" ", raw)
    years |= {int(y) for y in YEAR.findall(text)}
    text = YEAR.sub(" ", text)
    terms, words = [], {}
    for w in WORD.findall(text.lower()):
        if w in STOPWORDS:
            continue
        s = stem(w)
        if s not in words:
            terms.append(s)
            words[s] = w
    if not terms and not years:
        raise ValueError("Tell me what to find, for example: the 2026 school calendar.")
    return Query(raw=raw, terms=terms, words=words, years=years)


@dataclass
class Doc:
    """Everything known about one address on the site."""

    url: str
    depth: int = 0
    anchors: list = field(default_factory=list)  # text of links that point here
    title: str = ""
    headings: list = field(default_factory=list)
    description: str = ""
    body: str = ""
    fetched: bool = False
    kind: str = "page"  # page, pdf, or document

    def add_anchor(self, text):
        text = " ".join((text or "").split())[:200]
        if text and text not in self.anchors and len(self.anchors) < 8:
            self.anchors.append(text)


def kind_of_url(url):
    path = urlsplit(url).path.lower()
    for ext, kind in DOCUMENT_EXTENSIONS.items():
        if path.endswith(ext):
            return kind
    return "page"


def _url_text(url):
    parts = urlsplit(url)
    return unquote(parts.path + " " + parts.query)


@dataclass
class _Prepared:
    url: set
    anchor: set
    title: set
    heading: set
    desc: set
    body: Counter
    strong_years: set
    body_years: set


def _prepare(doc):
    url_text = _url_text(doc.url)
    anchor_text = " ".join(doc.anchors)
    heading_text = " ".join(doc.headings)
    return _Prepared(
        url=stems_of(url_text),
        anchor=stems_of(anchor_text),
        title=stems_of(doc.title),
        heading=stems_of(heading_text),
        desc=stems_of(doc.description),
        body=Counter(stem(w) for w in split_words(doc.body)),
        strong_years=years_in(SPLIT_BOUNDARIES.sub(" ", url_text) + " " + anchor_text + " " + doc.title + " " + heading_text),
        body_years=years_in(doc.description + " " + doc.body[:20000]),
    )


SATURATION = 6.0  # a word already found in several places adds less and less


def _saturate(score):
    """Squash a word's score so that one very strong word cannot hide a missing one."""
    return 10.0 * (1.0 - math.exp(-score / SATURATION))


FIELD_WEIGHTS = (("anchor", 4.0), ("title", 4.0), ("url", 3.0), ("heading", 3.0), ("desc", 1.5))
BODY_WEIGHT = 1.0
SYNONYM_FACTOR = 0.5


def _field_score(term, p):
    """Score for one word on one page, and which parts of the page held it."""
    score, where = 0.0, []
    for name, weight in FIELD_WEIGHTS:
        if term in getattr(p, name):
            score += weight
            where.append(name)
    count = p.body.get(term, 0)
    if count:
        score += BODY_WEIGHT * min(1.0, math.log(1 + count) / math.log(6))
        where.append("body")
    return score, where


def _term_score(query, term, p):
    direct, where = _field_score(term, p)
    best_syn, syn_where, syn_word = 0.0, [], None
    for syn in query.related(term):
        s, w = _field_score(syn, p)
        if s > best_syn:
            best_syn, syn_where, syn_word = s, w, syn
    if best_syn * SYNONYM_FACTOR > direct:
        return best_syn * SYNONYM_FACTOR, syn_where, syn_word
    return direct, where, None


def _any_presence(term, p):
    return any(term in getattr(p, name) for name, _ in FIELD_WEIGHTS) or term in p.body


def _matches_in(query, tokens):
    """Which query words (or close synonyms) appear in a set of word stems."""
    hit = set()
    for t in query.terms:
        if t in tokens or (query.related(t) & tokens):
            hit.add(t)
    return hit


def quick_score(query, url, anchors=()):
    """A cheap guess, from the address and link text alone, of how promising a link is."""
    tokens = stems_of(_url_text(url)) | stems_of(" ".join(anchors))
    score = 0.0
    for t in query.terms:
        if t in tokens:
            score += 1.0
        elif query.related(t) & tokens:
            score += SYNONYM_FACTOR
    if query.years:
        seen = years_in(SPLIT_BOUNDARIES.sub(" ", _url_text(url)) + " " + " ".join(anchors))
        if seen & query.years:
            score += 1.0
        elif seen:
            score -= 0.5
    return score


def _display_title(doc):
    if doc.title:
        return doc.title[:160]
    if doc.anchors:
        return doc.anchors[0][:160]
    name = unquote(urlsplit(doc.url).path.rstrip("/").rsplit("/", 1)[-1])
    return name or doc.url


def _best_text(query, texts):
    """The text that contains the most query words."""
    best, best_n = None, 0
    for text in texts:
        n = len(_matches_in(query, stems_of(text))) + (1 if years_in(text) & query.years else 0)
        if n > best_n:
            best, best_n = text, n
    return best


def _reasons(query, doc, p, term_info):
    reasons = []
    anchor = _best_text(query, doc.anchors)
    if anchor:
        reasons.append(f'Link text: "{anchor}"')
    if doc.title and (_matches_in(query, p.title) or years_in(doc.title) & query.years):
        reasons.append(f'Page title: "{doc.title[:120]}"')
    url_words = [query.words[t] for t in query.terms if t in p.url or (query.related(t) & p.url)]
    url_years = sorted(years_in(SPLIT_BOUNDARIES.sub(" ", _url_text(doc.url))) & query.years)
    if url_words or url_years:
        reasons.append("Address contains: " + ", ".join(url_words + [str(y) for y in url_years]))
    heading = _best_text(query, doc.headings)
    if heading:
        reasons.append(f'Heading: "{heading[:120]}"')
    body_only = [
        query.words[t] for t in query.terms
        if term_info[t][1] and set(term_info[t][1]) == {"body"}
    ]
    if body_only:
        reasons.append("Page text mentions: " + ", ".join(body_only))
    if query.years and not (p.strong_years & query.years) and (p.body_years & query.years):
        reasons.append("Page text mentions " + ", ".join(str(y) for y in sorted(query.years & p.body_years)))
    return reasons[:4]


def rank(query, docs, top=4):
    """Score every doc and return the best few, best first, as plain dictionaries."""
    if not docs:
        return []
    prepared = [_prepare(d) for d in docs]
    n = len(docs)
    idf = {}
    for t in query.terms:
        df = sum(1 for p in prepared if _any_presence(t, p))
        idf[t] = 1.0 + math.log((n + 1) / (df + 1))

    scored = []
    for doc, p in zip(docs, prepared):
        base, matched, missing, term_info = 0.0, 0, [], {}
        solid = 0  # words found in link text, title, address or headings (not only body text)
        for t in query.terms:
            s, where, _syn = _term_score(query, t, p)
            term_info[t] = (s, where)
            if s > 0:
                matched += 1
                base += _saturate(s) * idf[t]
                if any(w != "body" for w in where):
                    solid += 1
            else:
                missing.append(query.words[t])
        coverage = matched / len(query.terms) if query.terms else 1.0
        total = base * (coverage ** 2)

        year_ok = True
        if query.years:
            relevant = matched > 0 or not query.terms
            if p.strong_years & query.years:
                total = total * 1.6 + (5 if relevant else 0)
            elif p.body_years & query.years:
                total = total * 1.15 + (1.5 if not query.terms else 0)
                year_ok = False
            elif p.strong_years:
                total *= 0.45
                year_ok = False
            else:
                year_ok = False
        total /= 1 + 0.03 * doc.depth

        if total <= 0:
            continue
        if coverage == 1.0 and year_ok and (solid == len(query.terms)):
            strength = "strong"
        elif coverage >= 0.5:
            strength = "possible"
        else:
            strength = "weak"
        scored.append((total, doc, p, term_info, missing, strength))

    scored.sort(key=lambda row: (-row[0], len(row[1].url)))
    out = []
    for total, doc, p, term_info, missing, strength in scored[:top]:
        out.append(
            {
                "url": doc.url,
                "title": _display_title(doc),
                "kind": doc.kind,
                "score": round(total, 2),
                "strength": strength,
                "reasons": _reasons(query, doc, p, term_info),
                "missing": missing,
                "checked": doc.fetched,
            }
        )
    return out
