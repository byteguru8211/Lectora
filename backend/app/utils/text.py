"""Russian text utilities: normalisation, keywords, snippets, punctuation.

Vosk output is lowercase and unpunctuated.  These helpers are deterministic and
cheap, so the transcript looks human even when no LLM is running.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from typing import Iterable

_WORD_RE = re.compile(r"[а-яёa-z0-9]+(?:[-'][а-яёa-z0-9]+)*", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_SPACE_RE = re.compile(r"\s+")
# Atoms keep characters that matter for technology names: C++, C#, .NET, node.js.
_ATOM_RE = re.compile(r"\.?[a-zа-яё0-9][a-zа-яё0-9+#]*(?:\.[a-z0-9]+)*", re.IGNORECASE)

# Speech recognition writes technology names phonetically, so aliases are part
# of matching rather than a nice-to-have: Vosk renders "C++" as "плюс плюс".
_TECH_ALIASES = {
    "c++": r"(?:[cс]\s*\+\s*\+|cpp|си\s+плюс\s+плюс|плюс\s+плюс)",
    "c#": r"(?:[cс]\s*#|си\s+шарп)",
    ".net": r"(?:\.net|дот\s*нет)",
}

# The same aliases, but applied to the query before it is split into atoms.
_QUERY_ALIASES = (
    (re.compile(r"\b(?:си\s+)?плюс\s+плюс\b", re.IGNORECASE), " c++ "),
    (re.compile(r"\bcpp\b", re.IGNORECASE), " c++ "),
    (re.compile(r"\bси\s+шарп\b", re.IGNORECASE), " c# "),
    (re.compile(r"\bдот\s*нет\b", re.IGNORECASE), " .net "),
)

STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если
    уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей
    может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего
    раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь
    этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при
    наконец два об другой хоть после над больше тот через эти нас про всего них какая
    много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя
    такой им более всегда конечно всю между это как-то также который которые которая
    которых которая своего свои своих этом эта эти это очень просто именно даже чтобы
    если когда значит вообще да нет да вот ну вот типа такой такие такая таких
    называется называются равен равна равны равным равно является являются лежащего
    лежит состоит составлен составлены имеется имеют имеет будет будут может могут
    нужно нужен нужна нужны поэтому затем далее теперь этот того этом этих таким
    таких также только лишь можно нельзя надо стоит давайте рассмотрим рассмотрим
    получим получаем найдём найдем найдем видим видно понятно конечно соответственно
    """.split()
)

FILLERS = frozenset({"э", "ээ", "эээ", "мм", "ммм", "аа", "ааа", "ага", "угу"})


def normalize_space(text: str) -> str:
    return _SPACE_RE.sub(" ", text or "").strip()


def strip_fillers(text: str) -> str:
    words = text.split()
    kept = [w for w in words if w.lower().strip(",.") not in FILLERS]
    return " ".join(kept)


def tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if len(t) > 2 and t not in STOPWORDS]


def search_atoms(text: str) -> list[str]:
    """Split a query into units that preserve technical punctuation.

    ``"C++ указатели"`` → ``["c++", "указатели"]``; plain words stay plain.
    Phonetic spellings ("си плюс плюс", "cpp") become the canonical atom.
    """
    normalized = text or ""
    for pattern, replacement in _QUERY_ALIASES:
        normalized = pattern.sub(replacement, normalized)
    return [match.group(0).lower() for match in _ATOM_RE.finditer(normalized)]


def is_technical_atom(atom: str) -> bool:
    """Technical atoms need exact matching: full-text search drops ``+``/``#``/``.``."""
    return any(ch in atom for ch in "+#.") or (len(atom) == 1 and atom.isascii())


@lru_cache(maxsize=256)
def technical_pattern(term: str) -> re.Pattern[str]:
    term = term.lower()
    # "c++11" is still about C++; drop the version suffix when an alias exists.
    base = term if term in _TECH_ALIASES else re.sub(r"\d+$", "", term)
    body = _TECH_ALIASES.get(base)
    if body is None:
        body = re.escape(term).replace(r"\+", r"\s*\+").replace(r"\#", r"\s*#")
    prefix = r"(?<![a-zа-яё0-9])" if term[:1].isalpha() else ""
    return re.compile(rf"{prefix}{body}(?![a-zа-яё])", re.IGNORECASE)


def split_sentences(text: str) -> list[str]:
    text = normalize_space(text)
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def capitalize_first(text: str) -> str:
    text = text.lstrip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def restore_punctuation(text: str, *, end: str = ".") -> str:
    """Light deterministic clean-up for ASR output.

    * capitalise the first letter (and the pronoun ``я``);
    * add a full stop when the segment obviously ends a thought;
    * insert commas before common subordinate conjunctions.
    """
    text = normalize_space(strip_fillers(text))
    if not text:
        return ""

    text = re.sub(r"\bя\b", "Я", text)

    for conj in ("что", "чтобы", "потому что", "если", "когда", "который",
                 "которая", "которые", "но", "а", "или", "хотя"):
        # "..., но" only when the conjunction is not at the very beginning
        text = re.sub(
            rf"(?<=[а-яёa-z0-9])\s+({conj})\s+",
            lambda m: f", {m.group(1)} ",
            text,
            count=2,
        )

    text = capitalize_first(text)
    if end and text[-1] not in ".!?…":
        text = text.rstrip(",;:—-") + end
    return text


def keywords(texts: Iterable[str], limit: int = 12) -> list[str]:
    """Frequency-based keywords, merged by stem (no extra models needed)."""
    counter: Counter[str] = Counter()
    surfaces: dict[str, Counter[str]] = {}
    for text in texts:
        for token in content_tokens(text):
            if len(token) >= 4:
                stem = _stem(token)
                counter[stem] += 1
                surfaces.setdefault(stem, Counter())[token] += 1

    ranked = sorted(
        counter.items(), key=lambda kv: (kv[1] * (1 + min(len(kv[0]), 12) / 20)), reverse=True
    )
    frequent = [stem for stem, count in ranked if count > 1]
    rare = [stem for stem, count in ranked if count <= 1]
    result: list[str] = []
    for stem in frequent + rare:
        surface = surfaces[stem].most_common(1)[0][0]
        if surface not in result:
            result.append(surface)
        if len(result) >= limit:
            break
    return result


def _stem(token: str) -> str:
    for suffix in ("ами", "ями", "ов", "ев", "ый", "ий", "ая", "яя", "ое", "ее",
                   "ые", "ие", "ой", "ей", "ам", "ям", "ах", "ях", "ом", "ем",
                   "а", "я", "ы", "и", "у", "ю", "е", "о"):
        if len(token) - len(suffix) >= 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def highlight_spans(text: str, terms: list[str], *, radius: int = 160) -> list[dict]:
    """Find query terms in ``text`` and return character spans for <mark>."""
    if not text or not terms:
        return []
    spans: list[dict] = []
    for term in terms:
        if is_technical_atom(term):
            for match in technical_pattern(term).finditer(text):
                spans.append({"start": match.start(), "end": match.end()})
    words = [t for t in terms if not is_technical_atom(t)]
    stems = {_stem(t) for t in words if len(t) > 2}
    for match in _WORD_RE.finditer(text):
        word = match.group(0).lower()
        if len(word) < 3 and word not in words:
            continue
        if word in words or _stem(word) in stems or any(
            word.startswith(s[: max(4, len(s) - 1)]) and len(s) >= 4 for s in stems
        ):
            spans.append({"start": match.start(), "end": match.end()})
    return _merge_spans(spans)[:24]


def _merge_spans(spans: list[dict]) -> list[dict]:
    if not spans:
        return []
    spans.sort(key=lambda s: s["start"])
    merged = [spans[0]]
    for span in spans[1:]:
        if span["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], span["end"])
        else:
            merged.append(span)
    return merged


def snippet(text: str, spans: list[dict], *, limit: int = 320) -> tuple[str, list[dict]]:
    """Cut a readable window around the first match and rebase the spans."""
    if not spans or len(text) <= limit:
        return text, spans
    first = spans[0]["start"]
    start = max(0, first - limit // 3)
    end = min(len(text), start + limit)
    start = max(0, end - limit)
    # snap to word boundaries
    while start > 0 and text[start - 1] not in " \n\t":
        start += 1
    while end < len(text) and text[end] not in " \n\t":
        end -= 1
    window = text[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    rebased = [
        {"start": s["start"] - start + len(prefix), "end": s["end"] - start + len(prefix)}
        for s in spans
        if start <= s["start"] < end
    ]
    return f"{prefix}{window}{suffix}", rebased


def query_terms(query: str) -> list[str]:
    """Meaningful query units: technical atoms survive as-is, plain words drop stopwords."""
    atoms = search_atoms(query)
    words = set(content_tokens(query))
    terms = [atom for atom in atoms if is_technical_atom(atom) or atom in words]
    if not terms:
        terms = [atom for atom in atoms if len(atom) > 2 and atom not in STOPWORDS]
    if not terms:
        terms = tokens(query)
    return list(dict.fromkeys(terms))


def truncate(text: str, limit: int) -> str:
    text = normalize_space(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"
