"""Interactive proof stepping with Lean as the acceptance authority.

The session is deliberately human-in-the-loop.  Every tactic the user types is
sent to Lean immediately, and a completed proof is only called verified after
`LeanClient.verify` has re-elaborated the declaration and run the axiom check.
Saved sessions are marked `human_in_the_loop`, so an interactive proof can
never be mistaken for an autonomous benchmark result.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from neuralproof.lean.client import ProofState, TacticCandidate, VerificationResult

DEFAULT_SAVE_DIR = Path("experiments/interactive")

_HELP = (
    ("<tactic>", "apply a tactic and print the goals Lean reports"),
    (":goals", "re-inspect and print the current goals"),
    (":suggest [n]", "show ranked predictor suggestions; nothing is applied"),
    (":search", "run bounded best-first search from the current state"),
    (":undo", "remove the last tactic"),
    (":verify", "re-run the kernel and axiom check on the current proof"),
    (":save [path]", "write the proof and a provenance sidecar"),
    (":reset", "return to the initial goal"),
    (":help", "show this list"),
    (":quit", "leave the session"),
)


@dataclass(frozen=True)
class StepResult:
    tactic: str
    success: bool
    completed: bool
    goals: tuple[str, ...]
    error: str = ""
    elapsed_seconds: float = 0.0


class ProofSession:
    """A single proof the user advances one Lean-checked tactic at a time."""

    def __init__(self, client, theorem: str, context: str = "import Lean", *,
                 predictor=None, max_suggestions: int = 5):
        self.client = client
        self.theorem = theorem.strip()
        self.context = context.strip() or "import Lean"
        self.predictor = predictor
        self.max_suggestions = max(1, int(max_suggestions))
        self.history: list[str] = []
        self.verification: VerificationResult | None = None
        self.last_error = ""
        self._initial = self._inspect_initial()
        self.state: ProofState = self._initial

    def _inspect_initial(self) -> ProofState:
        inspected = self.client.inspect(
            self.client.initial_state(self.theorem, self.context))
        if not inspected.success or inspected.state is None:
            raise RuntimeError(
                f"could not inspect the initial goal: {inspected.error}")
        return inspected.state

    @property
    def completed(self) -> bool:
        return not self.state.goals

    @property
    def name(self) -> str:
        match = re.search(r"(?:theorem|lemma)\s+(«[^»]+»|[^\s(:]+)", self.theorem)
        if not match:
            return "interactive"
        return match.group(1).strip("«»")

    def apply(self, tactic: str) -> StepResult:
        """Send one tactic to Lean and advance the state when it is accepted."""
        tactic = tactic.strip()
        if not tactic:
            return StepResult("", False, self.completed, self.state.goals,
                              "empty tactic")
        if self.completed:
            return StepResult(tactic, False, True, (), "proof is already complete")
        result = self.client.apply(self.state, tactic)
        if not result.success or result.state is None:
            self.last_error = result.error
            return StepResult(tactic, False, self.completed, self.state.goals,
                              result.error, result.elapsed_seconds)
        self.history.append(tactic)
        self.state = result.state
        self.last_error = ""
        self.verification = None
        return StepResult(tactic, True, result.completed, self.state.goals,
                          "", result.elapsed_seconds)

    def undo(self) -> bool:
        """Drop the last tactic, replaying the remaining prefix from the start."""
        if not self.history:
            return False
        target = self.history[:-1]
        state = self._initial
        for tactic in target:
            result = self.client.apply(state, tactic)
            if not result.success or result.state is None:
                raise RuntimeError(
                    f"could not replay {tactic!r}: {result.error}")
            state = result.state
        self.history = target
        self.state = state
        self.verification = None
        self.last_error = ""
        return True

    def reset(self) -> None:
        self._initial = self._inspect_initial()
        self.state = self._initial
        self.history = []
        self.verification = None
        self.last_error = ""

    def suggest(self, count: int | None = None) -> list[TacticCandidate]:
        if self.predictor is None or self.completed:
            return []
        limit = int(count) if count is not None else self.max_suggestions
        return list(self.predictor.predict(self.state, max(1, limit)))

    def render(self) -> str:
        return self.client.render_proof(self.state)

    def verify(self) -> VerificationResult:
        """Run the kernel and axiom check; the only path to a verified claim."""
        if not self.completed:
            self.verification = VerificationResult(
                False, "", f"proof is not complete; {len(self.state.goals)} goal(s) remain",
                0.0)
            return self.verification
        self.verification = self.client.verify(self.render(), context=self.context)
        return self.verification

    def search(self, *, max_nodes: int = 20, width: int = 4,
               timeout: float = 30, max_depth: int = 12,
               filter_invalid_lemmas: bool = False,
               lemma_index_path: str | Path | None = None):
        """Run bounded best-first search from the current state."""
        if self.predictor is None:
            raise RuntimeError(
                "no predictor configured; start interact with --tactics, "
                "--model-id, or --adapter")
        if self.completed:
            raise RuntimeError("the proof is already complete")
        from neuralproof.search.best_first import best_first_from_state
        result = best_first_from_state(
            self.client, self.state, self.predictor,
            max_nodes=max_nodes, width=width, timeout=timeout,
            max_depth=max_depth, filter_invalid_lemmas=filter_invalid_lemmas,
            lemma_index_path=lemma_index_path)
        if result.verified and result.state is not None:
            self.state = result.state
            self.history = list(result.state.prefix)
            self.verification = None
            self.last_error = ""
        return result

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else _default_save_path(self)
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.completed and self.verification is None:
            self.verify()
        proof = self.render()
        target.write_text(self.context.rstrip() + "\n" + proof + "\n")
        verification = self.verification
        metadata = {
            "schema_version": 1,
            "mode": "interactive",
            "human_in_the_loop": True,
            "theorem": self.theorem,
            "context": self.context,
            "history": list(self.history),
            "completed": self.completed,
            "verified": bool(verification and verification.verified),
            "declaration": verification.declaration if verification else None,
            "axioms": list(verification.axioms) if verification else [],
            "lean_output": verification.output if verification else "",
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        target.with_suffix(".json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
        return target


def _default_save_path(session: ProofSession) -> Path:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", session.name) or "interactive"
    return DEFAULT_SAVE_DIR / f"{stem}.lean"


def format_goals(goals: tuple[str, ...] | list[str]) -> str:
    if not goals:
        return "(no goals)"
    return "\n".join(f"Goal {index}: {goal}" for index, goal in enumerate(goals, 1))


def _show_state(session: ProofSession, output_fn: Callable[[str], None]) -> None:
    output_fn(f"Goals ({len(session.state.goals)}):")
    output_fn(format_goals(session.state.goals))


def _show_verification(result: VerificationResult,
                       output_fn: Callable[[str], None]) -> None:
    if result.verified:
        axioms = ", ".join(result.axioms) or "none"
        output_fn(f"Kernel: VERIFIED (axioms: {axioms})")
        return
    output_fn("Kernel: NOT VERIFIED")
    text = (result.output or "").strip()
    if text:
        output_fn(text if len(text) <= 2000 else text[:2000] + "\n... (truncated)")


def _show_suggestions(session: ProofSession, output_fn: Callable[[str], None],
                      count: int | None = None) -> None:
    if session.predictor is None:
        output_fn("No predictor configured; start interact with --tactics, "
                  "--model-id, or --adapter.")
        return
    candidates = session.suggest(count)
    if not candidates:
        output_fn("No suggestions.")
        return
    for index, candidate in enumerate(candidates, 1):
        output_fn(f"  {index}. {candidate.tactic:<30} {candidate.score:.2f}")


def run_repl(session: ProofSession, *,
             input_fn: Callable[[str], str] = input,
             output_fn: Callable[[str], None] = print,
             save_dir: str | Path | None = None,
             search_budget: dict | None = None) -> int:
    """Run the interactive loop.  Returns a process exit code."""
    output_fn("NeuralProof interactive — Lean is the authority")
    output_fn(session.theorem)
    output_fn("")
    _show_state(session, output_fn)
    output_fn("Type a tactic, or :help for commands.")

    while True:
        noun = "tactic" if len(session.history) == 1 else "tactics"
        prompt = f"[{len(session.history)} {noun}] > "
        try:
            raw = input_fn(prompt)
        except EOFError:
            output_fn("")
            return 0
        except KeyboardInterrupt:
            output_fn("")
            continue
        line = raw.strip()
        if not line:
            continue

        if line.startswith(":"):
            command, _, rest = line.partition(" ")
            command = command.lower()
            if command in {":quit", ":q", ":exit"}:
                return 0
            if command in {":help", ":h", ":?"}:
                for name, text in _HELP:
                    output_fn(f"  {name:14} {text}")
                continue
            if command in {":goals", ":g", ":state"}:
                _show_state(session, output_fn)
                continue
            if command in {":suggest", ":s"}:
                count = None
                if rest.strip():
                    try:
                        count = int(rest.strip())
                    except ValueError:
                        output_fn("Usage: :suggest [count]")
                        continue
                _show_suggestions(session, output_fn, count)
                continue
            if command in {":undo", ":u"}:
                if session.undo():
                    _show_state(session, output_fn)
                else:
                    output_fn("Nothing to undo.")
                continue
            if command in {":verify", ":v"}:
                _show_verification(session.verify(), output_fn)
                continue
            if command in {":search", ":auto"}:
                output_fn("Searching...")
                try:
                    result = session.search(**(search_budget or {}))
                except RuntimeError as error:
                    output_fn(str(error))
                    continue
                output_fn(f"Search: {result.expanded} node(s), "
                          f"{result.tactic_calls} tactic call(s), "
                          f"verified={result.verified}")
                if result.verified and result.proof:
                    output_fn(result.proof)
                    _show_verification(session.verify(), output_fn)
                continue
            if command in {":save", ":w"}:
                if rest.strip():
                    path = Path(rest.strip())
                elif save_dir is None:
                    path = _default_save_path(session)
                else:
                    path = Path(save_dir) / _default_save_path(session).name
                try:
                    saved = session.save(path)
                except (OSError, RuntimeError) as error:
                    output_fn(f"Could not save: {error}")
                    continue
                output_fn(f"Saved {saved}")
                continue
            if command in {":reset", ":r"}:
                session.reset()
                _show_state(session, output_fn)
                continue
            output_fn(f"Unknown command {command!r}; try :help")
            continue

        step = session.apply(line)
        if not step.success:
            output_fn(f"Lean: rejected — {step.error}")
            continue
        if step.completed:
            output_fn("Lean: accepted — no goals remain")
            _show_verification(session.verify(), output_fn)
            output_fn("Use :save [path] to write the proof.")
        else:
            output_fn(f"Lean: accepted — {len(step.goals)} goal(s) remain")
            _show_state(session, output_fn)
