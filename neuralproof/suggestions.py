"""Goal-aware ordering for interactive tactic suggestions.

`StaticPredictor` returns a fixed list whose score is only the candidate's
position, not a confidence.  This module reorders the candidates a predictor
already returned using the rendered goal state.  It never runs Lean, never
applies a tactic, and never invents a candidate that the predictor did not
return; it only decides what to show first.
"""
from __future__ import annotations

import re

from neuralproof.goal_state import CASE_HEADER, GOAL_MARKER, goal_markers
from neuralproof.lean.client import ProofState, TacticCandidate

_ARITHMETIC_TYPES = re.compile(r"\b(?:Nat|Int|ℕ|ℤ)\b")
_COMMUTATIVE_TYPES = re.compile(
    r"\b(?:AddCommMonoid|AddCommGroup|CommMonoid|CommGroup|CommRing|"
    r"CommSemiring|Semiring|Ring|Monoid)\b")
_NUMERAL = re.compile(r"\b\d+\b")
_EQUALITY_HINT = re.compile(r"(?:^|\s)(?:=|≤|<|≥|>)(?:\s|$)")


def goal_targets(state: ProofState) -> tuple[str, ...]:
    """The `⊢ ...` target of every open goal, without the marker."""
    text = "\n".join(state.goals)
    return tuple(GOAL_MARKER.sub("", line).strip() for line in goal_markers(text))


def local_hypotheses(state: ProofState) -> dict[str, str]:
    """Map each local hypothesis name to its rendered type."""
    hypotheses: dict[str, str] = {}
    for block in state.goals:
        for line in block.splitlines():
            if (not line.strip() or CASE_HEADER.match(line)
                    or GOAL_MARKER.match(line) or " : " not in line):
                continue
            names, _, type_ = line.partition(" : ")
            for raw in names.split():
                name = raw.strip("✝")
                if name and not name.startswith("("):
                    hypotheses[name] = _normalize(type_)
    return hypotheses


def candidate_priority(tactic: str, targets: tuple[str, ...],
                       hypotheses: dict[str, str], context: str) -> float:
    """A small, explicit heuristic score for one candidate.

    The score only orders suggestions.  It is not a probability, and a high
    score does not mean Lean will accept the tactic.
    """
    tactic = tactic.strip()
    if not tactic:
        return 0.0

    text = context + "\n" + "\n".join(targets)
    normalized_targets = tuple(_normalize(target) for target in targets)
    hypothesis_types = set(hypotheses.values())
    equalities = [pair for target in targets
                  if (pair := _split_equality(target)) is not None]
    priority = 0.0

    if tactic == "rfl":
        # `rfl` only closes a goal whose sides are definitionally equal.  When
        # the goal is not an equality (or an iff), it is almost certainly wrong,
        # so keep it visible but below plausible candidates.
        for target in targets:
            equality = _split_equality(target)
            iff = _split_iff(target)
            if equality is not None:
                left, right = equality
                priority += 3.0 if _normalize(left) == _normalize(right) else -2.0
            elif iff is not None:
                left, right = iff
                priority += 3.0 if _normalize(left) == _normalize(right) else -2.0
            else:
                priority -= 1.0
        return priority

    if tactic == "trivial":
        if "True" in normalized_targets:
            priority += 3.0
        if any(target in hypothesis_types for target in normalized_targets):
            priority += 1.0
        return priority

    if tactic == "assumption":
        if any(target in hypothesis_types for target in normalized_targets):
            priority += 3.0
        return priority

    if tactic.startswith("exact "):
        term = tactic[len("exact "):].strip().lstrip("@").strip("()")
        if term in hypotheses and hypotheses[term] in normalized_targets:
            priority += 3.0
        if _normalize(term) == "True.intro" and "True" in normalized_targets:
            priority += 2.5
        for left, right in equalities:
            lemma = _commutative_lemma(left, right)
            if lemma and lemma in term:
                priority += 2.5
        return priority

    if tactic == "constructor":
        if any(_is_conjunction(target) for target in targets):
            priority += 2.0
        return priority

    if tactic in {"left", "right", "Or.inl", "Or.inr"}:
        if any(_is_disjunction(target) for target in targets):
            priority += 2.0
        return priority

    if tactic in {"intro", "intros"}:
        if any(_is_implication(target) for target in targets):
            priority += 2.0
        return priority

    if tactic == "use":
        if any(target.startswith("∃ ") for target in targets):
            priority += 2.0
        return priority

    if tactic == "omega":
        if equalities or any(_EQUALITY_HINT.search(target) for target in targets):
            if _ARITHMETIC_TYPES.search(text):
                priority += 2.0
            elif any(_NUMERAL.search(target) for target in targets):
                priority += 1.0
        return priority

    if tactic == "ring" or tactic.startswith("ring_nf"):
        if equalities and (_COMMUTATIVE_TYPES.search(text)
                           or _ARITHMETIC_TYPES.search(text)):
            priority += 1.5
        return priority

    if tactic == "ac_rfl":
        if equalities and (_COMMUTATIVE_TYPES.search(text)
                           or re.search(r"^\s*import\s+Mathlib", context,
                                        re.MULTILINE)):
            priority += 2.0
        return priority

    if tactic == "simp":
        if equalities or any(" ↔ " in target for target in targets):
            priority += 0.5
        return priority

    if tactic == "norm_num":
        if any(_NUMERAL.search(target) for target in targets):
            priority += 1.5
        return priority

    if tactic == "decide":
        if any(_NUMERAL.search(target) or _normalize(target) in {"True", "False"}
               for target in targets):
            priority += 1.0
        return priority

    return priority


def rank_candidates(state: ProofState,
                    candidates: list[TacticCandidate]) -> list[TacticCandidate]:
    """Order candidates by goal shape, preserving predictor order on ties."""
    targets = goal_targets(state)
    hypotheses = local_hypotheses(state)
    context = state.context + "\n" + "\n".join(state.goals)
    indexed = list(enumerate(candidates))
    indexed.sort(key=lambda item: (
        -candidate_priority(item[1].tactic, targets, hypotheses, context),
        item[0]))
    return [candidate for _, candidate in indexed]


class RankedPredictor:
    """Wrap a predictor so its top-k candidates follow the goal ranking.

    Best-first search reads `TacticCandidate.score` to decide which state to
    expand next, so a ranked candidate receives a rank-based score instead of
    the wrapped predictor's original position score.  With `rank=False` the
    original order and scores pass through unchanged.
    """

    def __init__(self, predictor, rank: bool = True):
        self.predictor = predictor
        self.rank = bool(rank)

    def predict(self, state: ProofState, k: int) -> list[TacticCandidate]:
        k = int(k)
        if k <= 0:
            return []
        portfolio = getattr(self.predictor, "tactics", None)
        # A static predictor exposes its whole portfolio, so ask for all of it
        # before truncating; otherwise a candidate beyond the cut can never be
        # promoted into the search window.
        request = max(k, len(portfolio)) if portfolio else k
        candidates = list(self.predictor.predict(state, request))
        if not self.rank:
            return candidates[:k]
        ranked = rank_candidates(state, candidates)[:k]
        return [TacticCandidate(candidate.tactic, 1 - index * .01)
                for index, candidate in enumerate(ranked)]


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _split_equality(target: str) -> tuple[str, str] | None:
    """Split a top-level `lhs = rhs`, ignoring `=`, `≤`, `≠`, and nested `=`."""
    text = _normalize(target)
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(" = ", index):
            return text[:index].strip(), text[index + 3:].strip()
    return None


def _split_iff(target: str) -> tuple[str, str] | None:
    """Split a top-level `p ↔ q`, which `rfl` can also close when `p == q`."""
    text = _normalize(target)
    marker = " ↔ "
    if marker not in text:
        return None
    left, _, right = text.partition(marker)
    return left.strip(), right.strip()


def _commutative_lemma(left: str, right: str) -> str | None:
    """The `*_comm` lemma for a goal of the form `a op b = b op a`."""
    for operator, lemma in (("+", "add_comm"), ("*", "mul_comm"),
                            ("∪", "union_comm"), ("∩", "inter_comm")):
        marker = f" {operator} "
        if marker not in left:
            continue
        head, _, tail = left.partition(marker)
        if _normalize(right) == _normalize(f"{tail}{marker}{head}"):
            return lemma
    return None


def _is_conjunction(target: str) -> bool:
    return (" ∧ " in target or " ↔ " in target
            or target.startswith("∃ ") or target.startswith("Σ "))


def _is_disjunction(target: str) -> bool:
    return " ∨ " in target


def _is_implication(target: str) -> bool:
    return " → " in target or target.startswith("∀ ")
