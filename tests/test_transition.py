"""The transition harness: span selection, substitution, and Lean classification."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from neuralproof.data.info_tree import trace_file
from neuralproof.data.normalize_info_tree import normalize_trace
from neuralproof.lean import transition


def _span(raw: bytes, text: str, *, occurrence: int = 0) -> tuple[int, int]:
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = raw.index(text.encode("utf-8"), cursor)
        cursor = start + 1
    return start, start + len(text.encode("utf-8"))


@pytest.fixture
def sample_source(tmp_path: Path) -> Path:
    raw = (
        "import Lean\n"
        "\n"
        "theorem t (p q : Prop) (hp : p) (hq : q) : p ∧ q := by\n"
        "  constructor\n"
        "  · exact hp\n"
        "  · exact hq\n"
        "\n"
        "theorem u : True := by\n"
        "  simp_rw [foo, bar]\n"
        "  trivial\n"
        "\n"
        "theorem v (M : Nat) : M = M := by rfl\n"
    )
    path = tmp_path / "Sample.lean"
    path.write_text(raw)
    return path


@pytest.fixture
def sample_trace(sample_source: Path) -> dict:
    raw = sample_source.read_bytes()
    by_t = _span(raw, "by", occurrence=0)
    by_u = _span(raw, "by", occurrence=1)
    by_v = _span(raw, "by", occurrence=2)
    proof_t = by_t[0]
    proof_u = by_u[0]
    proof_v = by_v[0]
    constructor = _span(raw, "constructor")
    exact_hp = _span(raw, "exact hp")
    exact_hq = _span(raw, "exact hq")
    simp = _span(raw, "simp_rw [foo, bar]")
    bar = _span(raw, "bar")
    rfl = _span(raw, "rfl")
    return {
        "traces": [
            {"syntax_kind": "Lean.Parser.Term.byTactic", "declaration": "t",
             "source_start": proof_t, "source_end": exact_hq[1]},
            {"syntax_kind": "by", "declaration": "t",
             "source_start": by_t[0], "source_end": by_t[1]},
            {"syntax_kind": "Lean.Parser.Tactic.tacticSeq", "declaration": "t",
             "source_start": constructor[0], "source_end": exact_hq[1]},
            {"syntax_kind": "Lean.Parser.Tactic.constructor", "declaration": "t",
             "source_start": constructor[0], "source_end": constructor[1]},
            {"syntax_kind": "Lean.Parser.Tactic.exact", "declaration": "t",
             "source_start": exact_hp[0], "source_end": exact_hp[1]},
            {"syntax_kind": "Lean.Parser.Tactic.exact", "declaration": "t",
             "source_start": exact_hq[0], "source_end": exact_hq[1]},
            {"syntax_kind": "Lean.Parser.Term.byTactic", "declaration": "u",
             "source_start": proof_u, "source_end": _span(raw, "trivial")[1]},
            {"syntax_kind": "by", "declaration": "u",
             "source_start": by_u[0], "source_end": by_u[1]},
            {"syntax_kind": "Lean.Parser.Tactic.tacticSeq", "declaration": "u",
             "source_start": simp[0], "source_end": _span(raw, "trivial")[1]},
            {"syntax_kind": "Lean.Parser.Tactic.simp", "declaration": "u",
             "source_start": simp[0], "source_end": simp[1]},
            {"syntax_kind": "Lean.Parser.Tactic.simp", "declaration": "u",
             "source_start": bar[0], "source_end": bar[1]},
            {"syntax_kind": "Lean.Parser.Tactic.tacticRfl", "declaration": "u",
             "source_start": _span(raw, "trivial")[0],
             "source_end": _span(raw, "trivial")[1]},
            {"syntax_kind": "Lean.Parser.Term.byTactic", "declaration": "v",
             "source_start": proof_v, "source_end": rfl[1]},
            {"syntax_kind": "by", "declaration": "v",
             "source_start": by_v[0], "source_end": by_v[1]},
            {"syntax_kind": "Lean.Parser.Tactic.tacticSeq", "declaration": "v",
             "source_start": rfl[0], "source_end": rfl[1]},
            {"syntax_kind": "Lean.Parser.Tactic.tacticRfl", "declaration": "v",
             "source_start": rfl[0], "source_end": rfl[1]},
        ]
    }


def test_a_complete_tactic_is_its_own_transition(sample_source, sample_trace):
    start, end = _span(sample_source.read_bytes(), "exact hp")
    span = transition.find_transition_span(sample_trace, "t", start, end)
    assert span.target_kind == "tactic"
    assert not span.is_fragment
    assert (span.container_start, span.container_end) == (start, end)


def test_a_fragment_is_substituted_into_its_enclosing_tactic(sample_source, sample_trace):
    raw = sample_source.read_bytes()
    start, end = _span(raw, "bar")
    span = transition.find_transition_span(sample_trace, "u", start, end)
    assert span.target_kind == "fragment"
    assert span.is_fragment
    assert raw[span.container_start:span.container_end] == b"simp_rw [foo, bar]"


def test_harness_substitutes_inside_the_enclosing_tactic(sample_source, sample_trace):
    raw = sample_source.read_bytes()
    start, end = _span(raw, "bar")
    row = {"source_declaration": "u", "source_start": start, "source_end": end}
    harness = transition.build_harness(sample_trace, sample_source, row, "baz")
    assert b"simp_rw [foo, baz]" in harness.text
    assert b"simp_rw [foo, bar]" not in harness.text
    assert b"trivial" not in harness.text
    # Candidates are never closed with sorry; otherwise a tactic that leaves
    # goals would be misreported as a complete proof.
    assert b"all_goals sorry" not in harness.text
    assert harness.close_remaining is False


def test_self_check_keeps_the_original_fragment_and_closes_goals(sample_source, sample_trace):
    raw = sample_source.read_bytes()
    start, end = _span(raw, "bar")
    row = {"source_declaration": "u", "source_start": start, "source_end": end}
    harness = transition.build_harness(sample_trace, sample_source, row,
                                       close_remaining=True)
    assert b"simp_rw [foo, bar]" in harness.text
    assert harness.inline_by is False
    assert harness.text.endswith(b"all_goals sorry\n")
    assert harness.close_remaining is True


def test_inline_proof_closes_with_a_tactic_sequence(sample_source, sample_trace):
    raw = sample_source.read_bytes()
    start, end = _span(raw, "rfl")
    row = {"source_declaration": "v", "source_start": start, "source_end": end}
    harness = transition.build_harness(sample_trace, sample_source, row,
                                       close_remaining=True)
    assert harness.inline_by is True
    assert harness.text.endswith(b"by rfl; all_goals sorry\n")
    without_closing = transition.build_harness(
        sample_trace, sample_source, row, close_remaining=False)
    assert b"all_goals sorry" not in without_closing.text
    assert without_closing.text.endswith(b"rfl")


def test_a_complete_tactic_is_replaced_whole(sample_source, sample_trace):
    raw = sample_source.read_bytes()
    start, end = _span(raw, "exact hp")
    row = {"source_declaration": "t", "source_start": start, "source_end": end}
    harness = transition.build_harness(sample_trace, sample_source, row, "assumption")
    assert b"\xc2\xb7 assumption" in harness.text
    assert b"exact hp" not in harness.text


def test_container_search_stays_inside_the_innermost_proof():
    trace = {"traces": [
        {"syntax_kind": "Lean.Parser.Tactic.tacticHave__",
         "source_start": 0, "source_end": 50},
        {"syntax_kind": "Lean.Parser.Tactic.change",
         "source_start": 20, "source_end": 30},
    ]}
    unrestricted = transition.find_transition_span(trace, "", 20, 30)
    assert unrestricted.target_kind == "fragment"
    assert unrestricted.container_start == 0
    restricted = transition.find_transition_span(
        trace, "", 20, 30, within=(15, 50))
    assert restricted.target_kind == "tactic"
    assert (restricted.container_start, restricted.container_end) == (20, 30)


def test_harness_preserves_following_structure_fields(tmp_path):
    raw = (
        b"import Lean\n\n"
        b"theorem s : S where\n"
        b"  left := by constructor\n"
        b"  right := by constructor\n"
    )
    path = tmp_path / "S.lean"
    path.write_bytes(raw)
    by_start = raw.index(b"by")
    first = raw.index(b"constructor")
    first_end = first + len(b"constructor")
    second = raw.index(b"constructor", first_end)
    second_end = second + len(b"constructor")
    trace = {
        "traces": [
            {"syntax_kind": "Lean.Parser.Term.byTactic", "declaration": "",
             "source_start": by_start, "source_end": first_end},
            {"syntax_kind": "by", "declaration": "",
             "source_start": by_start, "source_end": by_start + 2},
            {"syntax_kind": "Lean.Parser.Tactic.tacticSeq", "declaration": "",
             "source_start": first, "source_end": first_end},
            {"syntax_kind": "Lean.Parser.Tactic.constructor", "declaration": "",
             "source_start": first, "source_end": first_end},
            {"syntax_kind": "Lean.Parser.Term.byTactic", "declaration": "",
             "source_start": second - 3, "source_end": second_end},
            {"syntax_kind": "Lean.Parser.Tactic.constructor", "declaration": "",
             "source_start": second, "source_end": second_end},
        ],
        "commands": [
            {"declaration": "s", "source_start": 0, "source_end": len(raw)},
        ],
    }
    row = {"source_declaration": "", "source_start": first,
           "source_end": first_end}
    harness = transition.build_harness(trace, path, row)
    assert harness.text.endswith(b"\n  right := by constructor\n")
    assert harness.text.count(b"constructor") == 2
    closed = transition.build_harness(trace, path, row, close_remaining=True)
    assert b"constructor; all_goals sorry\n\n  right := by constructor\n" \
        in closed.text


def test_a_target_outside_the_proof_is_rejected(sample_source, sample_trace):
    raw = sample_source.read_bytes()
    start, end = _span(raw, "import Lean")
    row = {"source_declaration": "t", "source_start": start, "source_end": end}
    with pytest.raises(transition.TransitionError):
        transition.build_harness(sample_trace, sample_source, row)


def test_invalid_span_is_rejected(sample_trace):
    with pytest.raises(transition.TransitionError):
        transition.find_transition_span(sample_trace, "t", 5, 5)


def _run(returncode, *, errors=(), timed_out=False, stderr="", stdout=""):
    messages = tuple({"severity": "error", "data": error} for error in errors)
    return transition.HarnessRun(returncode, messages, stdout, stderr,
                                 timed_out, 0.1)


def test_classify_closed():
    assert transition.classify_output(_run(0)).status == "closed"


def test_classify_accepted_only_for_unsolved_goals():
    classification = transition.classify_output(
        _run(1, errors=("unsolved goals\np q : Prop",)))
    assert classification.status == "accepted"
    assert classification.reason == "unsolved_goals"


@pytest.mark.parametrize("errors", [
    ("unknown tactic",),
    ("unsolved goals", "unknown tactic"),
])
def test_classify_rejected_for_any_other_error(errors):
    assert transition.classify_output(_run(1, errors=errors)).status == "rejected"


def test_classify_accepted_from_unparsed_output():
    assert transition.classify_output(
        _run(1, stderr="error: unsolved goals")).status == "accepted"


def test_classify_timeout():
    assert transition.classify_output(_run(None, timed_out=True)).status == "timeout"


def test_trace_cache_reuses_a_digest_matching_trace(tmp_path, monkeypatch):
    project = tmp_path / "lean"
    project.mkdir()
    (project / "lean-toolchain").write_text("leanprover/lean4:v4.35.0\n")
    mathlib = project / ".lake" / "packages" / "mathlib" / "Mathlib"
    mathlib.mkdir(parents=True)
    source = mathlib / "A.lean"
    source.write_text("import Lean\n")

    calls = []

    def fake_trace(path, *, project_dir=None, timeout=300):
        calls.append((str(path), timeout))
        return {"schema_version": 2, "traces": [], "commands": []}

    monkeypatch.setattr(transition, "trace_file", fake_trace)
    cache = transition.TraceCache(project_dir=project,
                                  cache_dir=tmp_path / "cache")
    first = cache.get("Mathlib/A.lean")
    second = cache.get("Mathlib/A.lean")
    assert first == second
    assert len(calls) == 1
    assert cache.loaded == [str(source.resolve())]
    assert cache.generated == [str(source.resolve())]

    meta = json.loads(next((tmp_path / "cache").glob("*.meta.json")).read_text())
    assert meta["source_file"] == "Mathlib/A.lean"
    assert meta["lean_toolchain"] == "leanprover/lean4:v4.35.0"
    assert meta["mathlib_revision"] == "56a005855ea17e0b0958f73ec801ae140b0a1679"

    source.write_text("import Lean\n-- changed\n")
    cache.get("Mathlib/A.lean")
    assert len(calls) == 2


def test_trace_cache_refresh_regenerates(tmp_path, monkeypatch):
    project = tmp_path / "lean"
    project.mkdir()
    (project / "lean-toolchain").write_text("leanprover/lean4:v4.35.0\n")
    mathlib = project / ".lake" / "packages" / "mathlib" / "Mathlib"
    mathlib.mkdir(parents=True)
    source = mathlib / "A.lean"
    source.write_text("import Lean\n")

    calls = []

    def fake_trace(path, *, project_dir=None, timeout=300):
        calls.append(path)
        return {"schema_version": 2, "traces": [], "commands": []}

    monkeypatch.setattr(transition, "trace_file", fake_trace)
    cache = transition.TraceCache(project_dir=project,
                                  cache_dir=tmp_path / "cache",
                                  refresh=True)
    cache.get("Mathlib/A.lean")
    cache.get("Mathlib/A.lean")
    assert len(calls) == 2


def test_trace_cache_regenerates_corrupt_metadata(tmp_path, monkeypatch):
    project = tmp_path / "lean"
    project.mkdir()
    (project / "lean-toolchain").write_text("leanprover/lean4:v4.35.0\n")
    mathlib = project / ".lake" / "packages" / "mathlib" / "Mathlib"
    mathlib.mkdir(parents=True)
    source = mathlib / "A.lean"
    source.write_text("import Lean\n")

    calls = []

    def fake_trace(path, *, project_dir=None, timeout=300):
        calls.append(path)
        return {"schema_version": 2, "traces": [], "commands": []}

    monkeypatch.setattr(transition, "trace_file", fake_trace)
    cache = transition.TraceCache(project_dir=project,
                                  cache_dir=tmp_path / "cache")
    cache.get("Mathlib/A.lean")
    meta_path = next((tmp_path / "cache").glob("*.meta.json"))
    meta_path.write_text("{not json")
    cache.get("Mathlib/A.lean")
    assert len(calls) == 2


@pytest.mark.lean
def test_real_lean_harness_accepts_and_rejects(repo_root):
    source = repo_root / "lean" / "NeuralProof" / "Samples.lean"
    trace = trace_file(source, timeout=120)
    rows, _ = normalize_trace(trace, source)
    row = next(row for row in rows if row["source_declaration"] == "np_true")

    self_harness = transition.build_harness(trace, source, row,
                                            close_remaining=True)
    self_run = transition.run_harness(
        self_harness.text, project_dir=repo_root / "lean", timeout=120)
    assert transition.classify_output(self_run).status == "closed"

    accepted = transition.build_harness(trace, source, row, "trivial")
    accepted_run = transition.run_harness(
        accepted.text, project_dir=repo_root / "lean", timeout=120)
    assert transition.classify_output(accepted_run).status == "closed"

    rejected = transition.build_harness(trace, source, row, "exact missing_lemma")
    rejected_run = transition.run_harness(
        rejected.text, project_dir=repo_root / "lean", timeout=120)
    assert transition.classify_output(rejected_run).status == "rejected"


@pytest.mark.lean
def test_real_lean_harness_reports_a_partial_tactic_as_accepted(repo_root):
    source = repo_root / "lean" / "NeuralProof" / "Samples.lean"
    trace = trace_file(source, timeout=120)
    rows, _ = normalize_trace(trace, source)
    row = next(row for row in rows
               if row["source_declaration"] == "np_pair"
               and row["target_tactic"] == "constructor")

    self_harness = transition.build_harness(trace, source, row,
                                            close_remaining=True)
    self_run = transition.run_harness(
        self_harness.text, project_dir=repo_root / "lean", timeout=120)
    assert transition.classify_output(self_run).status == "closed"

    # `constructor` applies but leaves the two conjuncts open.  Because the
    # candidate harness has no `all_goals sorry`, Lean must report only
    # unsolved goals, which is the acceptance signal.
    partial = transition.build_harness(trace, source, row, "constructor")
    assert b"all_goals sorry" not in partial.text
    partial_run = transition.run_harness(
        partial.text, project_dir=repo_root / "lean", timeout=120)
    classification = transition.classify_output(partial_run)
    assert classification.status == "accepted"
    assert classification.reason == "unsolved_goals"
