import heapq,time,json,re
from dataclasses import dataclass,field
from itertools import count
from pathlib import Path
from typing import Protocol
from neuralproof.lean.client import LeanClient,ProofState,TacticCandidate

class Predictor(Protocol):
    def predict(self,state:ProofState,k:int)->list[TacticCandidate]: ...

@dataclass
class SearchResult:
    proof:str|None
    verified:bool
    expanded:int
    tactic_calls:int
    trace:list[dict]=field(default_factory=list)
    rejected_candidates:int=0


# Load lemma index for filtering
_LEMMA_INDEX = None
def _get_lemma_index():
    global _LEMMA_INDEX
    if _LEMMA_INDEX is None:
        try:
            idx_path = Path(__file__).parent.parent.parent / "data" / "lemma_index.json"
            if idx_path.exists():
                with open(idx_path) as f:
                    _LEMMA_INDEX = set(json.load(f))
            else:
                _LEMMA_INDEX = set()
        except Exception:
            _LEMMA_INDEX = set()
    return _LEMMA_INDEX


def _extract_lemmas_from_tactic(tactic: str):
    if not tactic or not tactic.strip():
        return []
    lemmas = []
    tactic = tactic.strip()
    rw_pattern = r'\b(?:rw|rewrite|erw)\b.*?\[(.*?)\]'
    for match in re.finditer(rw_pattern, tactic, re.DOTALL):
        content = match.group(1)
        parts = re.split(r',', content)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            part = re.sub(r'^[←→<\-]+\s*', '', part)
            part = re.sub(r'\s*[←→<\-]+$', '', part)
            part = re.sub(r'^@+\s*', '', part)
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', part):
                lemmas.append(part)
    for tactic_name in ['apply', 'exact', 'refine']:
        pattern = rf'\b{tactic_name}\b\s+(@?[a-zA-Z_][a-zA-Z0-9_.]+)'
        for match in re.finditer(pattern, tactic):
            lemmas.append(match.group(1).lstrip('@'))
    simp_pattern = r'\bsimp\b.*?\[(.*?)\]'
    for match in re.finditer(simp_pattern, tactic, re.DOTALL):
        content = match.group(1)
        parts = re.split(r'[,\s]+', content)
        for part in parts:
            part = part.strip()
            if not part or part in ['only', '-', '*']:
                continue
            part = re.sub(r'^[←→<\-]+\s*', '', part)
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', part) and len(part) > 2:
                lemmas.append(part)
    simpa_pattern = r'\bsimpa\b.*?(?:using|by)\s+([a-zA-Z_][a-zA-Z0-9_.]+)'
    for match in re.finditer(simpa_pattern, tactic):
        lemmas.append(match.group(1))
    seen = set()
    unique_lemmas = []
    for l in lemmas:
        if l not in seen:
            seen.add(l)
            unique_lemmas.append(l)
    return unique_lemmas


def _is_valid_lemma(lemma, lemma_index):
    if lemma in lemma_index:
        return True
    base = lemma.split('.')[-1]
    if base in lemma_index:
        return True
    return False


def _filter_tactic(tactic, lemma_index):
    lemmas = _extract_lemmas_from_tactic(tactic)
    if not lemmas:
        return True
    for lem in lemmas:
        if not _is_valid_lemma(lem, lemma_index):
            return False
    return True


def best_first(client,theorem,predictor,*,context="import Lean",max_nodes=50,width=5,timeout=30,max_depth=12,deduplicate=True,priority="model",filter_invalid_lemmas=True):
    start=time.monotonic(); seq=count(); initial=client.inspect(client.initial_state(theorem,context)); seen=set(); expanded=calls=0; trace=[]; rejected=0
    lemma_index = _get_lemma_index() if filter_invalid_lemmas else set()
    if not initial.success or initial.state is None:
        return SearchResult(None,False,0,0,[{"initial_state_inspection":False,"error":initial.error}])
    trace.append({"initial_state_inspection":True,"goal_state":initial.state.goal_state,"goals":list(initial.state.goals)})
    queue=[(0.,next(seq),0,initial.state)]
    while queue and expanded<max_nodes and time.monotonic()-start<timeout:
        _,_,depth,state=heapq.heappop(queue)
        if deduplicate and state.prefix in seen: continue
        seen.add(state.prefix); expanded+=1
        if depth>=max_depth: continue
        for cand in predictor.predict(state,width):
            # An empty candidate is not a tactic; sending it to Lean would
            # spend a Lean call and a timeout slot on a guaranteed error.
            if not cand.tactic.strip():
                rejected+=1; trace.append({"depth":depth,"tactic":"","rejected":"empty candidate"}); continue
            # Filter out tactics with invalid lemmas
            if filter_invalid_lemmas and lemma_index and not _filter_tactic(cand.tactic, lemma_index):
                rejected+=1
                lemmas = _extract_lemmas_from_tactic(cand.tactic)
                trace.append({"depth":depth,"tactic":cand.tactic,"score":cand.score,"rejected":"invalid lemma", "invalid_lemmas": lemmas})
                continue
            remaining=max(.001,timeout-(time.monotonic()-start)); old_timeout=client.timeout
            client.timeout=min(old_timeout,remaining)
            calls+=1
            try: result=client.apply(state,cand.tactic)
            finally: client.timeout=old_timeout
            trace.append({"depth":depth,"tactic":cand.tactic,"score":cand.score,"success":result.success,"error":result.error})
            if not result.success or result.state is None: continue
            if result.completed:
                proof=client.render_proof(result.state); remaining=max(.001,timeout-(time.monotonic()-start)); old_timeout=client.timeout; client.timeout=min(old_timeout,remaining)
                try: verification=client.verify(proof,context=state.context)
                finally: client.timeout=old_timeout
                if verification.verified:
                    trace.append({"final_verification":True,"axioms":list(verification.axioms)})
                    return SearchResult(proof,True,expanded,calls,trace,rejected)
                trace.append({"final_verification":False,"error":verification.output,"axioms":list(verification.axioms)})
                continue
            key=-cand.score if priority=="model" else float(depth+1)
            heapq.heappush(queue,(key,next(seq),depth+1,result.state))
    return SearchResult(None,False,expanded,calls,trace,rejected)
