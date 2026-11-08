"""Replay-based Lean compiler client; Lean remains the proof authority."""
from __future__ import annotations
import json, re, shutil, subprocess, tempfile, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neuralproof.goal_state import canonical_goal_state, split_goal_blocks

@dataclass(frozen=True)
class ProofState:
    theorem: str
    context: str = "import Lean"
    prefix: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    state_id: str = ""

    @property
    def goal_state(self) -> str:
        """Canonical rendering of the open goals, as shown to the model.

        The mined corpus stores the same rendering, so a mined prompt and a
        live prompt are identical once both are canonicalized.
        """
        return canonical_goal_state("\n".join(self.goals))

@dataclass(frozen=True)
class TacticCandidate:
    tactic: str
    score: float = 0.0

@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    state: ProofState | None
    completed: bool
    error: str = ""
    elapsed_seconds: float = 0.0

@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    declaration: str
    output: str
    elapsed_seconds: float
    axioms: tuple[str, ...] = ()

@dataclass(frozen=True)
class LeanRun:
    """One Lean invocation, with its `--json` message stream parsed."""

    returncode: int | None
    messages: tuple[dict[str, Any], ...] = ()
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def _parse_messages(stdout: str) -> tuple[dict[str, Any], ...]:
    """Parse the `lean --json` stream: one JSON message object per line.

    Lines that are not JSON are skipped, so a launcher banner or a crash dump
    does not hide the messages that Lean did emit.
    """
    messages = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            messages.append(message)
    return tuple(messages)


def _error_text(run: LeanRun) -> str:
    """Describe a failed Lean run using its error messages, or its raw output."""
    errors = [str(message.get("data", "")) for message in run.messages
              if message.get("severity") == "error"]
    if errors:
        return "\n".join(errors)
    tail = (run.stderr.strip() or run.stdout.strip())
    return tail[-2000:] if tail else "Lean exited with a non-zero status"


def _goal_region(run: LeanRun) -> str:
    """The goal rendering produced by `trace_state`; no other message is included.

    Lean tags `trace_state` output with the `trace` message kind, so linter
    warnings and `sorry` notices cannot leak into the captured goal state.
    """
    return canonical_goal_state("\n".join(str(message.get("data", ""))
                                          for message in run.messages
                                          if message.get("kind") == "trace"))


def _axioms(messages: tuple[dict[str, Any], ...]) -> tuple[tuple[str, ...], bool]:
    """The axioms reported by `#print axioms`, and whether a report was seen.

    The second value is false when no `#print axioms` output is present.  A
    caller must not read an empty axiom tuple as "no dependencies" unless a
    report was actually emitted; otherwise a skipped command would look like a
    constructive proof.
    """
    fallback: tuple[str, ...] | None = None
    reported = False
    for message in messages:
        if message.get("severity") != "information":
            continue
        data = str(message.get("data", ""))
        if "depends on axioms" in data or "depend on any axioms" in data:
            reported = True
        if "axioms" not in data:
            continue
        # "'x' depends on axioms: [a, b]" names the dependencies; "'x' does not
        # depend on any axioms" names none.
        depends = re.search(r"depends on axioms:\s*\[([^\]]*)\]", data)
        if depends:
            return tuple(item.strip() for item in depends.group(1).split(",") if item.strip()), True
        if fallback is None and re.search(r"\[([^\]]*)\]", data):
            fallback = tuple(item.strip() for item in re.search(r"\[([^\]]*)\]", data).group(1).split(",") if item.strip())
    return (fallback if fallback is not None else ()), reported


_DECL_MODIFIERS = frozenset({
    "private", "protected", "noncomputable", "unsafe", "partial", "nonrec",
})


def _strip_declaration_prefix(text: str) -> str:
    """Drop comments, attributes, and modifiers that precede a declaration."""
    rest = text.lstrip()
    while rest:
        if rest.startswith("/--") or rest.startswith("/-"):
            opener = 3 if rest.startswith("/--") else 2
            end = rest.find("-/", opener)
            if end < 0:
                return ""
            rest = rest[end + 2:].lstrip()
            continue
        if rest.startswith("--"):
            end = rest.find("\n")
            if end < 0:
                return ""
            rest = rest[end + 1:].lstrip()
            continue
        if rest.startswith("@["):
            depth = 0
            end = -1
            for index, char in enumerate(rest):
                if char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            if end < 0:
                return ""
            rest = rest[end + 1:].lstrip()
            continue
        modifier = re.match(r"[A-Za-z_]+", rest)
        if modifier and modifier.group(0) in _DECL_MODIFIERS:
            rest = rest[modifier.end():].lstrip()
            continue
        return rest
    return rest


def _declaration_name(text: str) -> str | None:
    """The name `#print axioms` needs, or `None` when the header is unknown.

    Attributes, doc/line comments, and modifiers are skipped so that a
    `private` or `@[simp]` theorem still reaches the axiom check.  A caller may
    also pass a small preamble (for example an `axiom` the proof uses) before
    the theorem, so every line start is a candidate.  Returning `None` is a
    verification failure, never a reason to skip that check.
    """
    candidates = [text]
    candidates.extend(text[newline.end():] for newline in re.finditer(r"\n", text))
    for candidate in candidates:
        rest = _strip_declaration_prefix(candidate)
        match = re.match(r"(?:theorem|lemma)\s+(«[^»]+»|[^\s(:]+)", rest)
        if not match:
            continue
        name = match.group(1)
        if name.startswith("«"):
            return name
        # `foo.{u}` names the same declaration; `#print axioms` takes `foo`.
        name = name.split(".{", 1)[0]
        return name or None
    return None

class LeanClient:
    def __init__(self, project_dir: str | Path | None = None, timeout: float = 20):
        self.project_dir=Path(project_dir or Path(__file__).parents[2]/"lean").resolve()
        self.timeout=timeout; self.lean=shutil.which("lean"); self.lake=shutil.which("lake")
        if not self.lean: raise RuntimeError("Lean executable not found; install elan and pinned toolchain")
    def doctor(self):
        p=subprocess.run([self.lean,"--version"],cwd=self.project_dir,capture_output=True,text=True,timeout=self.timeout)
        if p.returncode: raise RuntimeError(p.stderr or p.stdout)
        return p.stdout.strip()
    @staticmethod
    def _header(theorem):
        h=theorem.rstrip()
        return h if re.search(r":=\s*by\s*$",h) else h+" := by"
    def _script(self,state,body):
        """Build a Lean file that replays `body` on top of the state's prefix."""
        lines=(state.context.splitlines()+[self._header(state.theorem)]
               +["  "+x for x in state.prefix]+["  "+x for x in body])
        return "\n".join(lines)+"\n"
    def _run(self,script,*,prefix):
        with tempfile.TemporaryDirectory(prefix=prefix) as td:
            path=Path(td)/"Harness.lean"; path.write_text(script)
            command=([self.lake,"env",self.lean,"--json",str(path)] if self.lake else [self.lean,"--json",str(path)])
            try: p=subprocess.run(command,cwd=self.project_dir,capture_output=True,text=True,timeout=self.timeout)
            except subprocess.TimeoutExpired: return LeanRun(None,timed_out=True)
        return LeanRun(p.returncode,_parse_messages(p.stdout),p.stdout,p.stderr)
    def apply(self,state,tactic):
        started=time.monotonic()
        run=self._run(self._script(state,[tactic,"all_goals trace_state","all_goals sorry"]),prefix="neuralproof-")
        elapsed=time.monotonic()-started
        if run.timed_out: return ExecutionResult(False,None,False,"Lean execution timed out",elapsed)
        # Lean reports every failure with a non-zero exit status; the message
        # format varies (`error:` and `error(code):` both occur), so the exit
        # status is the only reliable failure signal.
        if run.returncode: return ExecutionResult(False,None,False,_error_text(run),elapsed)
        region=_goal_region(run)
        goals=split_goal_blocks(region)
        nxt=ProofState(state.theorem,state.context,state.prefix+(tactic,),goals,repr(state.prefix+(tactic,)))
        return ExecutionResult(True,nxt,not region,"",elapsed)
    def inspect(self,state):
        """Ask Lean to print the current goals without accepting them as proof."""
        started=time.monotonic()
        # `all_goals trace_state` renders exactly like the mined corpus; a plain
        # `trace_state` prints every goal in one message and inserts a blank line
        # between goals, which no mined row contains.
        run=self._run(self._script(state,["all_goals trace_state","all_goals sorry"]),prefix="neuralproof-inspect-")
        elapsed=time.monotonic()-started
        if run.timed_out: return ExecutionResult(False,None,False,"Lean inspection timed out",elapsed)
        if run.returncode: return ExecutionResult(False,None,False,_error_text(run),elapsed)
        region=_goal_region(run)
        if not region: return ExecutionResult(False,None,False,"Lean reported no goal state",elapsed)
        return ExecutionResult(True,ProofState(state.theorem,state.context,state.prefix,split_goal_blocks(region),repr(state.prefix)),False,"",elapsed)
    def initial_state(self,theorem,context="import Lean"): return ProofState(theorem,context)
    def render_proof(self,state): return self._header(state.theorem)+"\n"+"\n".join("  "+x for x in state.prefix)
    def verify(self,theorem_with_proof,context="import Lean"):
        started=time.monotonic()
        if re.search(r"\b(sorry|admit)\b",theorem_with_proof): return VerificationResult(False,"","placeholder token rejected",time.monotonic()-started)
        declaration=_declaration_name(theorem_with_proof)
        if declaration is None:
            return VerificationResult(False,"","could not determine the declaration name; refusing to skip the axiom check",time.monotonic()-started)
        source=context.rstrip()+"\n"+theorem_with_proof.rstrip()+f"\n#print axioms {declaration}\n"
        run=self._run(source+"\n",prefix="neuralproof-verify-")
        elapsed=time.monotonic()-started
        if run.timed_out: return VerificationResult(False,declaration,"Lean verification timed out",elapsed)
        axioms,reported=_axioms(run.messages)
        allowed={"propext","Classical.choice","Quot.sound"}
        unexpected=tuple(x for x in axioms if x not in allowed)
        output="\n".join(f"{m.get('severity')}: {m.get('data')}" for m in run.messages) or (run.stdout+run.stderr)
        if unexpected: output+="\nunexpected axiom dependencies: "+", ".join(unexpected)
        if run.returncode==0 and not reported:
            output+="\nno #print axioms report found"
            return VerificationResult(False,declaration,output,elapsed,axioms)
        return VerificationResult(run.returncode==0 and not unexpected,declaration,output,elapsed,axioms)
