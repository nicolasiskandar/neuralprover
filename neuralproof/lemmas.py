"""Heuristic lemma-reference extraction and candidate filtering.

This module is deliberately a *pre-filter*, not a correctness check.  It uses
a name index and the identifiers that occur in the current proof state to
refuse candidates that mention a symbol that cannot be resolved, which saves a
Lean call.  Lean remains the authority for whether a tactic is valid.
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path

# A Lean identifier: one or more dot-separated segments.  This accepts the
# ASCII names used by Mathlib and the unicode letters that occur in Lean
# identifiers; inaccessible names such as ``x✝`` are reduced to ``x``.
_IDENTIFIER = re.compile(r"[^\W\d][\w']*(?:\.[^\W\d][\w']*)*")

# Tactic keywords and Lean syntax words.  They are never lemma references, so
# extracting them only creates false rejections (the old filter treated the
# ``fun`` in ``refine fun x => ...`` as a lemma).
_KEYWORDS = frozenset("""
rw rewrite erw simp simpa simp_rw dsimp unfold fold unfold_projs
apply exact refine refine' eapply eexact erefine fapply
intro intros have let show from using at with only by fun
match if then else do return in this rfl trivial assumption
contradiction decide native_decide compute norm_num norm_cast
push_cast exact_mod_cast ring ring_nf field_simp linarith nlinarith
omega positivity bound aesop done all_goals any_goals first try repeat
case next focus set obtain rcases cases induction subst specialize
generalize clear rename revert constructor left right exists use congr
ext ext1 by_cases by_contra absurd exfalso infer_instance synthInstance
sorry admit change convert convert_to exact? apply? simp? unfold?
""".split())

_KEYWORD_BRACKET = re.compile(
    r"\b(?:rw|rewrite|erw|simp|simp_rw|dsimp|unfold)\b")
_KEYWORD_TERM = re.compile(
    r"\b(?:apply|exact|refine|refine'|eapply|eexact|erefine|fapply|"
    r"simpa|convert|convert_to|simpa?)\b\s+([^\n;]*)")
_USING = re.compile(r"\busing\b\s+([^\n;,]*)")
_UNFOLD = re.compile(r"\bunfold\b\s+([^\n;]*)")


@dataclass(frozen=True)
class FilterResult:
    """Outcome of one pre-filter pass over a tactic string."""

    allowed: bool
    symbols: tuple[str, ...]
    unknown: tuple[str, ...]


def default_index_path() -> Path:
    """The checked-in index, resolved from the package root."""
    return Path(__file__).resolve().parents[1] / "data" / "lemma_index.json.gz"


_INDEX_CACHE: dict[Path, frozenset[str]] = {}


def load_lemma_index(path: str | Path | None = None, *,
                     required: bool = False) -> frozenset[str]:
    """Load the lemma-name index, caching it per path.

    ``required=True`` makes a missing index an explicit error.  A search run
    that asked for filtering must not silently run unfiltered.
    """
    index_path = Path(path) if path is not None else default_index_path()
    index_path = index_path.resolve()
    cached = _INDEX_CACHE.get(index_path)
    if cached is not None:
        return cached
    if not index_path.exists():
        if required:
            raise FileNotFoundError(
                f"lemma index not found: {index_path}; build it with "
                "`python scripts/build_lemma_index.py` or pass an explicit index path")
        return frozenset()
    opener = gzip.open if index_path.suffix == ".gz" else open
    with opener(index_path, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, list):
        raise ValueError(f"lemma index {index_path} must be a JSON array of names")
    index = frozenset(str(name) for name in data)
    _INDEX_CACHE[index_path] = index
    return index


def identifiers_in_text(text: str) -> frozenset[str]:
    """Identifier-like tokens in free text, plus each token's root segment.

    The goal state is pretty-printed Lean, not a parser output, so this is a
    deliberately permissive allowlist: a local binder or projection root that
    appears anywhere in the state is considered known.
    """
    tokens = frozenset(match.group(0) for match in _IDENTIFIER.finditer(text or ""))
    roots = frozenset(token.split(".", 1)[0] for token in tokens)
    return tokens | roots


def symbols_in_state(context: str = "", goal_state: str = "",
                     theorem: str = "") -> frozenset[str]:
    """All identifiers a candidate may legitimately mention."""
    return identifiers_in_text("\n".join((context or "", theorem or "",
                                          goal_state or "")))


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    """Split on a separator that is not inside brackets, braces or a string."""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            buffer.append(char)
            if char == "\\" and index + 1 < len(text):
                buffer.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char == '"':
            quote = char
            buffer.append(char)
        elif char in "([{⟨⦃":
            depth += 1
            buffer.append(char)
        elif char in ")]}⟩⦄":
            depth = max(0, depth - 1)
            buffer.append(char)
        elif char == separator and depth == 0:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
        index += 1
    parts.append("".join(buffer))
    return parts


def _scan_bracket(text: str, start: int) -> tuple[str, int]:
    """Return the content of the balanced ``[...]`` starting at ``start``."""
    depth = 0
    quote: str | None = None
    index = start
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char == '"':
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
        index += 1
    return text[start + 1:], len(text)


def _head_identifier(part: str) -> str | None:
    """The leading identifier of one tactic argument, or ``None``.

    ``rw [← foo]`` yields ``foo``; ``refine ⟨...⟩`` and ``refine fun x => ...``
    yield nothing because the first token is not a lemma name.
    """
    text = part.strip()
    text = re.sub(r"^[←→<>\-@!]+\s*", "", text)
    if not text:
        return None
    if re.match(r"^(?:fun|λ|by|match|if|let|have|show|from)\b", text):
        return None
    match = _IDENTIFIER.match(text)
    if match is None:
        return None
    name = match.group(0)
    # ``reassoc_of% h`` is a term elaborator, not a constant; a trailing ``%``
    # marks syntax that the declaration index will never contain.
    if text[match.end():match.end() + 1] == "%":
        return None
    if name in _KEYWORDS or name.endswith("."):
        return None
    return name


def extract_symbol_heads(tactic: str) -> list[str]:
    """Identifier heads a tactic references as potential lemma names.

    This is intentionally conservative about *where* a name can occur: bracket
    arguments of rewriting/simplification tactics and the leading term of
    ``apply``/``exact``/``refine``/``simpa``.  Binders, terms introduced by
    ``fun``/``by``/``match`` and compound expressions are left to Lean.
    """
    if not tactic or not tactic.strip():
        return []
    text = re.sub(r'"(?:\\.|[^"\\])*"', " ", tactic)
    text = re.sub(r"--[^\n]*", " ", text)
    names: list[str] = []

    for match in _KEYWORD_BRACKET.finditer(text):
        bracket = text.find("[", match.end())
        if bracket == -1:
            continue
        between = text[match.end():bracket]
        if ";" in between or "\n" in between:
            continue
        content, _ = _scan_bracket(text, bracket)
        for part in _split_top_level(content):
            name = _head_identifier(part)
            if name is not None:
                names.append(name)

    for match in _KEYWORD_TERM.finditer(text):
        name = _head_identifier(match.group(1))
        if name is not None:
            names.append(name)

    for match in _USING.finditer(text):
        name = _head_identifier(match.group(1))
        if name is not None:
            names.append(name)

    for match in _UNFOLD.finditer(text):
        for token in _IDENTIFIER.findall(match.group(1)):
            if token not in _KEYWORDS:
                names.append(token)

    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def is_known_symbol(name: str, index: frozenset[str] | set[str],
                    allowed_symbols: frozenset[str] | set[str] = frozenset()) -> bool:
    """Whether a referenced identifier can be resolved heuristically.

    Accepted if it is a local/state identifier, an exact index entry, a suffix
    of a qualified name (``Finset.sum_eq_single`` if ``sum_eq_single`` is in
    the index), or a projection whose root is in the state.
    """
    if name in allowed_symbols:
        return True
    parts = name.split(".")
    root = parts[0]
    if root in allowed_symbols:
        return True
    if name in index:
        return True
    for start in range(1, len(parts)):
        if ".".join(parts[start:]) in index:
            return True
    return False


def filter_tactic(tactic: str, index: frozenset[str] | set[str],
                  allowed_symbols: frozenset[str] | set[str] = frozenset()) -> FilterResult:
    """Refuse a candidate only when it names a symbol nothing can resolve."""
    symbols = extract_symbol_heads(tactic)
    unknown = tuple(name for name in symbols
                    if not is_known_symbol(name, index, allowed_symbols))
    return FilterResult(allowed=not unknown, symbols=tuple(symbols), unknown=unknown)
