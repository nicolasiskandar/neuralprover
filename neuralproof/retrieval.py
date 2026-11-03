"""Deterministic lexical retrieval over lemma names and statements.

This is a feasibility tool, not a proof component.  It builds a BM25 inverted
index from a statement corpus and returns ranked constant names.  A returned
name is only a candidate: Lean must still elaborate and accept any tactic that
uses it.
"""
from __future__ import annotations

import gzip
import heapq
import json
import math
import re
from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

# Split camelCase and PascalCase boundaries while keeping snake_case intact
# (the token pattern below treats underscores as separators anyway).
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TOKEN = re.compile(r"[^\W\d_]+|\d+|[^\w\s]", re.UNICODE)

# Tokens that only describe Lean syntax.  Keeping them would add a posting list
# for nearly every document without carrying lemma-specific information.
_SYNTAX_TOKENS = frozenset("()[]{}⟨⟩⦃⦄,;:|.⊢@?!'`")

# Lean/elaboration words that occur in almost every statement.  Semantic words
# such as ``map``, ``add`` or ``comm`` are deliberately not stopped.
_STOPWORDS = frozenset("""
theorem lemma def definition instance structure class inductive axiom opaque
abbrev variable section end namespace open import universe
prop type sort outparam implicit inst auto
by fun let have show from with at
eq iff and or not true false
""".split())

_DEFAULT_MAX_DF_RATIO = 0.10
_DEFAULT_MAX_QUERY_TERMS = 64


def tokenize(text: str) -> list[str]:
    """Tokenize a lemma name, statement, context or goal state.

    Names are split at dots, underscores and camel-case boundaries, so
    ``Finset.sum_comm`` and ``sum_comm`` share the tokens ``sum`` and ``comm``.
    Unicode letters and mathematical symbols are kept.
    """
    if not text:
        return []
    spaced = _CAMEL_BOUNDARY.sub(" ", text)
    tokens = []
    for match in _TOKEN.finditer(spaced):
        token = match.group(0).lower()
        if token in _SYNTAX_TOKENS or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


@dataclass(frozen=True)
class Statement:
    """One row of the statement corpus."""
    name: str
    kind: str
    type: str
    module: str | None = None

    def document(self, *, include_type: bool) -> str:
        """The indexable text: the qualified name plus the optional type."""
        if include_type:
            return f"{self.name} {self.type}"
        return self.name


def read_statement_corpus(path: str | Path) -> list[Statement]:
    """Read a gzip (or plain) JSONL statement corpus."""
    corpus_path = Path(path)
    opener = gzip.open if corpus_path.suffix == ".gz" else open
    statements: list[Statement] = []
    with opener(corpus_path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            try:
                statements.append(Statement(
                    name=raw["name"], kind=raw["kind"], type=raw["type"],
                    module=raw.get("module")))
            except KeyError as error:
                raise ValueError(
                    f"{corpus_path}:{line_number} missing {error.args[0]}") from error
    return statements


class BM25Index:
    """A compact BM25 inverted index over lemma statements.

    Postings use ``array`` rather than Python tuples so a full-Mathlib corpus
    stays within reasonable memory.  Ties are broken by the alphabetically
    earlier name because the corpus is sorted by name before indexing.
    """

    def __init__(self, *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.names: list[str] = []
        self._name_to_id: dict[str, int] = {}
        self.doc_len = array("I")
        self.postings: dict[str, array] = {}
        self.term_freqs: dict[str, array] = {}
        self.total_len = 0
        self.average_len = 0.0

    @property
    def size(self) -> int:
        return len(self.names)

    def add(self, name: str, text: str) -> None:
        doc_id = len(self.names)
        self.names.append(name)
        self._name_to_id[name] = doc_id
        tokens = tokenize(text)
        length = len(tokens)
        self.doc_len.append(length)
        self.total_len += length
        for term, frequency in Counter(tokens).items():
            self.postings.setdefault(term, array("I")).append(doc_id)
            self.term_freqs.setdefault(term, array("H")).append(
                min(frequency, 65535))

    def finalize(self) -> "BM25Index":
        self.average_len = self.total_len / len(self.doc_len) if self.doc_len else 0.0
        return self

    def idf(self, term: str) -> float:
        postings = self.postings.get(term)
        if not postings:
            return 0.0
        df = len(postings)
        return math.log(1.0 + (self.size - df + 0.5) / (df + 0.5))

    def _query_terms(self, query: str, *, max_df_ratio: float,
                     max_terms: int) -> list[str]:
        counts = Counter(tokenize(query))
        if not counts:
            return []
        max_df = max(1, int(self.size * max_df_ratio))
        scored = [(self.idf(term), term) for term in counts
                  if term in self.postings and len(self.postings[term]) <= max_df]
        # Rare terms first; the term itself breaks ties deterministically.
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [term for _, term in scored[:max_terms]]

    def search(self, query: str, k: int = 20, *,
               exclude: Iterable[str] = (),
               max_df_ratio: float = _DEFAULT_MAX_DF_RATIO,
               max_terms: int = _DEFAULT_MAX_QUERY_TERMS) -> list[tuple[str, float]]:
        """Return up to ``k`` ``(name, score)`` pairs, best first."""
        if k <= 0 or not self.names:
            return []
        excluded = {self._name_to_id[name] for name in exclude
                    if name in self._name_to_id}
        query_terms = self._query_terms(query, max_df_ratio=max_df_ratio,
                                        max_terms=max_terms)
        if not query_terms:
            return []
        scores: defaultdict[int, float] = defaultdict(float)
        for term in query_terms:
            postings = self.postings[term]
            frequencies = self.term_freqs[term]
            idf = self.idf(term)
            for doc_id, frequency in zip(postings, frequencies):
                if doc_id in excluded:
                    continue
                length = self.doc_len[doc_id]
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * length / self.average_len)
                scores[doc_id] += idf * frequency * (self.k1 + 1.0) / denominator
        # Higher score first, then alphabetically earlier name (lower doc id).
        best = heapq.nlargest(k, scores.items(), key=lambda item: (item[1], -item[0]))
        return [(self.names[doc_id], score) for doc_id, score in best]


def build_index(statements: Iterable[Statement], *, include_type: bool = True,
                k1: float = 1.5, b: float = 0.75) -> BM25Index:
    """Build a BM25 index from corpus rows."""
    index = BM25Index(k1=k1, b=b)
    for statement in statements:
        index.add(statement.name, statement.document(include_type=include_type))
    return index.finalize()


def iter_statements(path: str | Path) -> Iterator[Statement]:
    """Stream corpus rows without holding the whole list in memory."""
    corpus_path = Path(path)
    opener = gzip.open if corpus_path.suffix == ".gz" else open
    with opener(corpus_path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            try:
                yield Statement(name=raw["name"], kind=raw["kind"],
                                type=raw["type"], module=raw.get("module"))
            except KeyError as error:
                raise ValueError(
                    f"{corpus_path}:{line_number} missing {error.args[0]}") from error
