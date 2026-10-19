"""Replay-based Lean compiler client; Lean remains the proof authority."""
from __future__ import annotations
import re, shutil, subprocess, tempfile, time
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ProofState:
    theorem: str
    context: str = "import Lean"
    prefix: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    state_id: str = ""

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
    def _script(self,state,tactic=None,inspect=False):
        lines=state.context.splitlines()+[self._header(state.theorem)] + ["  "+x for x in state.prefix]
        if tactic is not None: lines.append("  "+tactic)
        if inspect: lines += ["  all_goals trace_state","  all_goals sorry"]
        return "\n".join(lines)+"\n"
    def apply(self,state,tactic):
        start=time.monotonic()
        with tempfile.TemporaryDirectory(prefix="neuralproof-") as td:
            path=Path(td)/"Candidate.lean"; path.write_text(self._script(state,tactic,True))
            try: p=subprocess.run(([self.lake,"env",self.lean,str(path)] if self.lake else [self.lean,str(path)]),cwd=self.project_dir,capture_output=True,text=True,timeout=self.timeout)
            except subprocess.TimeoutExpired: return ExecutionResult(False,None,False,"Lean execution timed out",time.monotonic()-start)
        output=p.stdout+p.stderr
        errors=[x for x in output.splitlines() if "error:" in x]
        if p.returncode and errors and not any("sorry" in x for x in errors): return ExecutionResult(False,None,False,"\n".join(errors),time.monotonic()-start)
        goals=tuple(x.strip() for x in re.findall(r"(?m)^\s*⊢\s+.*$",output))
        nxt=ProofState(state.theorem,state.context,state.prefix+(tactic,),goals,repr(state.prefix+(tactic,)))
        return ExecutionResult(True,nxt,not goals,"",time.monotonic()-start)
    def inspect(self,state):
        """Ask Lean to print the current goals without accepting them as proof."""
        start=time.monotonic()
        with tempfile.TemporaryDirectory(prefix="neuralproof-inspect-") as td:
            path=Path(td)/"Inspect.lean"
            path.write_text(self._script(state,"trace_state",False)+"  sorry\n")
            try: p=subprocess.run(([self.lake,"env",self.lean,str(path)] if self.lake else [self.lean,str(path)]),cwd=self.project_dir,capture_output=True,text=True,timeout=self.timeout)
            except subprocess.TimeoutExpired: return ExecutionResult(False,None,False,"Lean inspection timed out",time.monotonic()-start)
        out=p.stdout+p.stderr
        goals=tuple(x.strip() for x in re.findall(r"(?m)^\s*⊢\s+.*$",out))
        if not goals and "⊢" not in out: return ExecutionResult(False,None,False,out,time.monotonic()-start)
        return ExecutionResult(True,ProofState(state.theorem,state.context,state.prefix,goals,repr(state.prefix)),False,"",time.monotonic()-start)
    def initial_state(self,theorem,context="import Lean"): return ProofState(theorem,context)
    def render_proof(self,state): return self._header(state.theorem)+"\n"+"\n".join("  "+x for x in state.prefix)
    def verify(self,theorem_with_proof,context="import Lean"):
        start=time.monotonic()
        if re.search(r"\b(sorry|admit)\b",theorem_with_proof): return VerificationResult(False,"","placeholder token rejected",time.monotonic()-start)
        match=re.search(r"(?m)^(?:theorem|lemma)\s+([^\s(:]+)",theorem_with_proof)
        declaration=match.group(1) if match else ""
        source=context.rstrip()+"\n"+theorem_with_proof.rstrip()+ (f"\n#print axioms {declaration}\n" if declaration else "")
        with tempfile.TemporaryDirectory(prefix="neuralproof-verify-") as td:
            path=Path(td)/"Verify.lean"; path.write_text(source+"\n")
            try: p=subprocess.run(([self.lake,"env",self.lean,str(path)] if self.lake else [self.lean,str(path)]),cwd=self.project_dir,capture_output=True,text=True,timeout=self.timeout)
            except subprocess.TimeoutExpired: return VerificationResult(False,"","Lean verification timed out",time.monotonic()-start)
        out=p.stdout+p.stderr
        axiom_match=re.search(r"\[([^]]*)\]",out)
        axioms=tuple(x.strip() for x in axiom_match.group(1).split(",") if x.strip()) if axiom_match else ()
        allowed={"propext","Classical.choice","Quot.sound"}
        unexpected=tuple(x for x in axioms if x not in allowed)
        if unexpected: out += "\nunexpected axiom dependencies: "+", ".join(unexpected)
        return VerificationResult(p.returncode==0 and not unexpected,declaration,out,time.monotonic()-start,axioms)
