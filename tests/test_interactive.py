"""Interactive proof stepping: state, undo, suggestions, and verification."""
from __future__ import annotations

import json

import pytest

from neuralproof.interactive import ProofSession, format_goals, run_repl
from neuralproof.lean.client import (ExecutionResult, LeanClient, ProofState,
                                     TacticCandidate, VerificationResult)
from neuralproof.models.predictor import StaticPredictor
from neuralproof.search.best_first import SearchResult


class FakeClient:
    """A tiny proof language: `split` opens two goals, `trivial` closes one,
    `exact True.intro` closes all, and `bad` is rejected."""

    def __init__(self, initial_goals=None):
        self.applied = []
        self.verified = []
        self.initial_goals = tuple(initial_goals or ("⊢ True",))

    def initial_state(self, theorem, context="import Lean"):
        return ProofState(theorem, context, (), (), "initial")

    def inspect(self, state):
        goals = state.goals or self.initial_goals
        return ExecutionResult(
            True,
            ProofState(state.theorem, state.context, state.prefix, tuple(goals),
                       repr(state.prefix)),
            False, "", 0.0)

    def apply(self, state, tactic):
        self.applied.append(tactic)
        if tactic == "bad":
            return ExecutionResult(False, None, False, "unknown tactic 'bad'", 0.1)
        prefix = state.prefix + (tactic,)
        if tactic == "split":
            goals = ("⊢ True", "⊢ True")
        elif tactic == "trivial":
            goals = tuple(state.goals[1:])
        elif tactic == "exact True.intro":
            goals = ()
        else:
            goals = state.goals
        return ExecutionResult(
            True,
            ProofState(state.theorem, state.context, prefix, tuple(goals),
                       repr(prefix)),
            not goals, "", 0.1)

    def render_proof(self, state):
        return (state.theorem + " := by\n"
                + "\n".join("  " + tactic for tactic in state.prefix))

    def verify(self, proof, context="import Lean"):
        self.verified.append((proof, context))
        return VerificationResult(True, "demo", "", 0.0, ("propext",))


def _session(**kwargs):
    return ProofSession(FakeClient(), "theorem demo : True",
                        context="import Lean", **kwargs)


def test_initial_session_inspects_the_goal():
    session = _session()
    assert session.state.goals == ("⊢ True",)
    assert not session.completed
    assert session.history == []


def test_a_tactic_advances_the_state_and_history():
    session = _session()
    step = session.apply("split")
    assert step.success and not step.completed
    assert session.history == ["split"]
    assert len(session.state.goals) == 2


def test_a_rejected_tactic_does_not_change_the_proof():
    session = _session()
    step = session.apply("bad")
    assert not step.success
    assert "unknown tactic" in step.error
    assert session.history == []
    assert session.state.goals == ("⊢ True",)


def test_undo_replays_the_remaining_prefix():
    session = _session()
    session.apply("split")
    session.apply("trivial")
    assert len(session.state.goals) == 1
    assert session.undo()
    assert session.history == ["split"]
    assert len(session.state.goals) == 2
    assert session.undo()
    assert session.history == []
    assert session.state.goals == ("⊢ True",)
    assert not session.undo()


def test_verify_refuses_an_incomplete_proof():
    session = _session()
    result = session.verify()
    assert not result.verified
    assert "not complete" in result.output


def test_verify_calls_the_kernel_on_a_completed_proof():
    client = FakeClient()
    session = ProofSession(client, "theorem demo : True", context="import Lean")
    session.apply("exact True.intro")
    assert session.completed
    result = session.verify()
    assert result.verified
    assert result.axioms == ("propext",)
    assert client.verified and "exact True.intro" in client.verified[0][0]


def test_an_empty_tactic_is_not_sent_to_lean():
    client = FakeClient()
    session = ProofSession(client, "theorem demo : True")
    step = session.apply("   ")
    assert not step.success
    assert client.applied == []


def test_suggestions_are_displayed_without_being_applied():
    client = FakeClient()
    session = ProofSession(client, "theorem demo : True",
                           predictor=StaticPredictor(["trivial", "split"]))
    candidates = session.suggest()
    assert [candidate.tactic for candidate in candidates] == ["trivial", "split"]
    assert client.applied == []
    assert session.history == []


def test_suggest_considers_the_whole_static_portfolio_before_truncating():
    client = FakeClient(initial_goals=("a b : Nat\n⊢ a + b = b + a",))
    session = ProofSession(
        client, "theorem demo : True", max_suggestions=2,
        predictor=StaticPredictor(
            ["rfl", "trivial", "assumption", "simp", "omega"]))

    tactics = [candidate.tactic for candidate in session.suggest()]

    assert tactics == ["omega", "simp"]
    assert client.applied == []


def test_rank_suggestions_can_be_turned_off():
    client = FakeClient(initial_goals=("a b : Nat\n⊢ a + b = b + a",))
    session = ProofSession(
        client, "theorem demo : True", rank_suggestions=False,
        predictor=StaticPredictor(["rfl", "omega"]))

    assert [candidate.tactic for candidate in session.suggest()] == ["rfl", "omega"]


def test_save_marks_the_session_human_in_the_loop(tmp_path):
    session = _session()
    session.apply("exact True.intro")
    target = session.save(tmp_path / "demo.lean")
    assert target.read_text().startswith("import Lean\n")
    assert "theorem demo : True := by" in target.read_text()
    metadata = json.loads(target.with_suffix(".json").read_text())
    assert metadata["mode"] == "interactive"
    assert metadata["human_in_the_loop"] is True
    assert metadata["verified"] is True
    assert metadata["history"] == ["exact True.intro"]


def test_repl_steps_to_a_verified_proof(tmp_path):
    lines = iter([":suggest", "split", "trivial", "trivial",
                  f":save {tmp_path / 'demo.lean'}", ":quit"])
    output = []
    session = _session(predictor=StaticPredictor(["trivial"]))
    code = run_repl(session, input_fn=lambda prompt: next(lines),
                    output_fn=output.append)
    text = "\n".join(output)
    assert code == 0
    assert "NeuralProof interactive" in text
    assert "1. trivial" in text
    assert "Lean: accepted — 2 goal(s) remain" in text
    assert "Kernel: VERIFIED (axioms: propext)" in text
    assert (tmp_path / "demo.lean").exists()


def test_repl_reports_an_unknown_command():
    lines = iter([":nonsense", ":quit"])
    output = []
    code = run_repl(_session(), input_fn=lambda prompt: next(lines),
                    output_fn=output.append)
    assert code == 0
    assert any("Unknown command" in line for line in output)


def test_auto_suggest_is_on_by_default():
    lines = iter([":quit"])
    output = []
    session = _session(predictor=StaticPredictor(["trivial"]))
    code = run_repl(session, input_fn=lambda prompt: next(lines),
                    output_fn=output.append)
    text = "\n".join(output)
    assert code == 0
    assert "Suggestions (goal-ranked):" in text
    assert "1. trivial" in text
    assert session.history == []


def test_auto_suggest_can_be_turned_off():
    class CountingPredictor:
        def __init__(self):
            self.calls = 0

        def predict(self, state, k):
            self.calls += 1
            return [TacticCandidate("trivial", 1.0)]

    predictor = CountingPredictor()
    lines = iter([":quit"])
    output = []
    code = run_repl(_session(predictor=predictor),
                    input_fn=lambda prompt: next(lines),
                    output_fn=output.append, auto_suggest=False)
    assert code == 0
    assert predictor.calls == 0
    assert "Suggestions" not in "\n".join(output)


def test_suggestions_are_shown_again_after_a_rejection():
    lines = iter(["bad", ":quit"])
    output = []
    session = _session(predictor=StaticPredictor(["trivial"]))
    run_repl(session, input_fn=lambda prompt: next(lines),
             output_fn=output.append)
    text = "\n".join(output)
    assert "Lean: rejected" in text
    assert "Suggestions (goal-ranked):" in text
    assert "1. trivial" in text
    assert session.history == []


def test_repl_exits_cleanly_on_eof():
    def eof(prompt):
        raise EOFError

    code = run_repl(_session(), input_fn=eof, output_fn=lambda line: None)
    assert code == 0


def test_search_loads_a_verified_proof_into_the_session(monkeypatch):
    def fake_search(client, state, predictor, **kwargs):
        completed = ProofState(state.theorem, state.context,
                               ("exact True.intro",), (), "done")
        return SearchResult("theorem demo : True := by\n  exact True.intro",
                            True, 1, 1, [], 0, 0, completed)

    monkeypatch.setattr("neuralproof.search.best_first.best_first_from_state",
                        fake_search)
    session = _session(predictor=StaticPredictor(["exact True.intro"]))
    result = session.search()
    assert result.verified
    assert session.completed
    assert session.history == ["exact True.intro"]
    assert session.verify().verified


def test_search_uses_goal_ranked_candidates(monkeypatch):
    captured = {}

    def fake_search(client, state, predictor, **kwargs):
        captured["tactics"] = [candidate.tactic
                               for candidate in predictor.predict(state, 2)]
        return SearchResult(None, False, 0, 0, [], 0, 0)

    monkeypatch.setattr("neuralproof.search.best_first.best_first_from_state",
                        fake_search)
    client = FakeClient(initial_goals=("a b : Nat\n⊢ a + b = b + a",))
    session = ProofSession(
        client, "theorem demo : True",
        predictor=StaticPredictor(
            ["rfl", "trivial", "assumption", "simp", "omega"]))

    result = session.search()

    assert not result.verified
    assert captured["tactics"] == ["omega", "simp"]


def test_search_can_keep_the_original_order(monkeypatch):
    captured = {}

    def fake_search(client, state, predictor, **kwargs):
        captured["tactics"] = [candidate.tactic
                               for candidate in predictor.predict(state, 2)]
        return SearchResult(None, False, 0, 0, [], 0, 0)

    monkeypatch.setattr("neuralproof.search.best_first.best_first_from_state",
                        fake_search)
    client = FakeClient(initial_goals=("a b : Nat\n⊢ a + b = b + a",))
    session = ProofSession(
        client, "theorem demo : True", rank_suggestions=False,
        predictor=StaticPredictor(["rfl", "omega"]))

    result = session.search()

    assert not result.verified
    assert captured["tactics"] == ["rfl", "omega"]


def test_search_without_a_predictor_is_an_error():
    session = _session()
    with pytest.raises(RuntimeError, match="no predictor"):
        session.search()


def test_format_goals_numbers_each_goal():
    assert format_goals(("⊢ True", "⊢ False")) == "Goal 1: ⊢ True\nGoal 2: ⊢ False"
    assert format_goals(()) == "(no goals)"


def test_format_goals_hides_inaccessible_name_markers():
    goals = ("α : Type\ninst✝ : AddCommMonoid α\ninst✝¹ : Subsingleton α\n"
             "x✝² : α\nhr✝ : x✝ = x✝\n⊢ x✝ = x✝",)

    text = format_goals(goals)

    assert "✝" not in text
    assert "inst : AddCommMonoid α" in text
    assert "inst : Subsingleton α" in text
    assert "x : α" in text
    assert "hr : x = x" in text
    assert "⊢ x = x" in text


def test_format_goals_keeps_ordinary_hypothesis_names():
    text = format_goals(("n : Nat\nhn : n = n\n⊢ n = n",))

    assert text == "Goal 1: n : Nat\nhn : n = n\n⊢ n = n"


@pytest.mark.lean
def test_interactive_session_proves_a_real_lean_theorem(repo_root):
    client = LeanClient(project_dir=repo_root / "lean", timeout=60)
    session = ProofSession(client, "theorem np_interactive : True",
                           context="import Lean")
    assert not session.completed
    step = session.apply("trivial")
    assert step.success, step.error
    assert session.completed
    result = session.verify()
    assert result.verified, result.output
    assert result.declaration == "np_interactive"
    assert session.undo()
    assert not session.completed


@pytest.mark.lean
def test_search_finds_a_real_proof_from_the_ranked_candidates(repo_root):
    client = LeanClient(project_dir=repo_root / "lean", timeout=60)
    session = ProofSession(
        client, "theorem np_search_ranked (a b : Nat) : a + b = b + a",
        context="import Lean", predictor=StaticPredictor(["rfl", "omega"]),
        max_suggestions=2)

    result = session.search(max_nodes=10, width=2, timeout=60)

    assert result.verified, result.trace
    assert result.proof and "omega" in result.proof
    assert session.completed
    assert session.verify().verified
