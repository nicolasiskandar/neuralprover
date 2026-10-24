"""The Lean client: the proof authority behind every number in this project."""
import pytest

from neuralproof.lean.client import LeanClient

pytestmark = pytest.mark.lean


@pytest.fixture(scope="module")
def client():
    return LeanClient(timeout=15)


def test_doctor(client):
    assert "Lean (version 4.35.0" in client.doctor()


def test_verified_end_to_end(client):
    state = client.initial_state("theorem test_true : True")
    result = client.apply(state, "exact True.intro")
    assert result.success
    assert result.completed
    assert client.verify(client.render_proof(result.state)).verified


def test_mathlib_context_and_kernel_verification():
    # `import Mathlib` loads the whole library's oleans; the module-wide
    # 15 s timeout is marginal for that under load, so this case uses a
    # client with its own budget.
    client = LeanClient(timeout=120)
    context = "import Mathlib"
    state = client.initial_state("theorem mathlib_test (n : Nat) : n + 0 = n", context)
    result = client.apply(state, "simp")
    assert result.success, result.error
    assert result.completed, result.error
    verification = client.verify(client.render_proof(result.state), context=context)
    assert verification.verified, verification.output
    assert set(verification.axioms) <= {"propext", "Classical.choice", "Quot.sound"}


def test_invalid_tactic(client):
    assert not client.apply(client.initial_state("theorem bad : True"), "not_a_tactic").success


def test_unknown_identifier_is_reported_as_a_failure(client):
    result = client.apply(client.initial_state("theorem bad : True"), "exact Nat.sorry")
    assert not result.success
    assert result.state is None
    assert not result.completed
    assert "Unknown constant" in result.error


def test_type_mismatch_is_reported_as_a_failure(client):
    result = client.apply(client.initial_state("theorem bad : True"), "exact (5 : Nat)")
    assert not result.success
    assert result.state is None
    assert "Type mismatch" in result.error


def test_a_failing_tactic_leaves_the_previous_goals_untouched(client):
    state = client.inspect(client.initial_state("theorem bad : True")).state
    assert state.goal_state == "⊢ True"
    result = client.apply(state, "exact (5 : Nat)")
    assert not result.success
    assert result.state is None
    assert state.goal_state == "⊢ True"


def test_inspect_rejects_an_ill_typed_declaration(client):
    state = client.initial_state("theorem bad : Nat := by exact True.intro")
    result = client.inspect(state)
    assert not result.success
    assert result.state is None
    assert result.error


def test_linter_notices_do_not_reach_the_goal_state(client):
    # An unused binder makes Lean emit a linter notice; the captured goal
    # state must contain the goal only.
    state = client.initial_state("theorem unused_binder (n : Nat) : True")
    inspected = client.inspect(state)
    assert inspected.success, inspected.error
    assert inspected.state.goal_state == "n : Nat\n⊢ True"


def test_unused_binder_does_not_break_kernel_verification(client):
    # Lean's unused-variable linter prints a bracketed hint; it must not be
    # mistaken for an axiom dependency.
    result = client.verify("theorem np_unused (n : Nat) : True := by trivial")
    assert result.verified, result.output
    assert result.axioms == ()


def test_multiple_goals_and_placeholder_audit(client):
    state = client.initial_state("theorem pair (p q : Prop) (hp : p) (hq : q) : p ∧ q")
    first = client.apply(state, "constructor")
    assert first.success
    assert not first.completed
    second = client.apply(first.state, "exact hp")
    assert second.success
    assert not second.completed
    third = client.apply(second.state, "exact hq")
    assert third.completed
    assert client.verify(client.render_proof(third.state)).verified
    assert not client.verify("theorem invalid : True := by\n  sorry").verified


def test_unexpected_axiom_rejected(client):
    result = client.verify("axiom fabricated : True\ntheorem unsound : True := fabricated")
    assert not result.verified
    assert "fabricated" in result.axioms


def test_subprocess_timeout():
    client = LeanClient(timeout=0.000001)
    result = client.apply(client.initial_state("theorem slow : True"), "trivial")
    assert not result.success
    assert "timed out" in result.error
