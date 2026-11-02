import heapq,time
from dataclasses import dataclass,field
from itertools import count
from typing import Protocol
from neuralproof.lean.client import LeanClient,ProofState,TacticCandidate
from neuralproof.lemmas import filter_tactic,load_lemma_index,symbols_in_state

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
    rejected_unknown_lemmas:int=0


def best_first(client,theorem,predictor,*,context="import Lean",max_nodes=50,width=5,timeout=30,max_depth=12,deduplicate=True,priority="model",filter_invalid_lemmas=False,lemma_index_path=None):
    """Bounded best-first search.  Lemma filtering is opt-in.

    The filter is a budget saver, not a validity check: it refuses a candidate
    only when it names a symbol that is neither in the lemma index nor in the
    current goal state.  Lean still decides every tactic that is tried.
    """
    start=time.monotonic(); seq=count(); initial=client.inspect(client.initial_state(theorem,context)); seen=set(); expanded=calls=0; trace=[]; rejected=0; rejected_unknown=0
    # A missing index is an error, not a silent no-op: a run that asked for
    # filtering must not look filtered when it was not.
    lemma_index = load_lemma_index(lemma_index_path, required=True) if filter_invalid_lemmas else frozenset()
    if not initial.success or initial.state is None:
        return SearchResult(None,False,0,0,[{"initial_state_inspection":False,"error":initial.error}])
    trace.append({"initial_state_inspection":True,"goal_state":initial.state.goal_state,"goals":list(initial.state.goals)})
    queue=[(0.,next(seq),0,initial.state)]
    while queue and expanded<max_nodes and time.monotonic()-start<timeout:
        _,_,depth,state=heapq.heappop(queue)
        if deduplicate and state.prefix in seen: continue
        seen.add(state.prefix); expanded+=1
        if depth>=max_depth: continue
        allowed_symbols = symbols_in_state(state.context,state.goal_state,state.theorem) if filter_invalid_lemmas else frozenset()
        for cand in predictor.predict(state,width):
            # An empty candidate is not a tactic; sending it to Lean would
            # spend a Lean call and a timeout slot on a guaranteed error.
            if not cand.tactic.strip():
                rejected+=1; trace.append({"depth":depth,"tactic":"","rejected":"empty candidate"}); continue
            # Filter out candidates that name a symbol nothing can resolve.
            if filter_invalid_lemmas:
                filtered=filter_tactic(cand.tactic,lemma_index,allowed_symbols)
                if not filtered.allowed:
                    rejected+=1; rejected_unknown+=1
                    trace.append({"depth":depth,"tactic":cand.tactic,"score":cand.score,
                                  "rejected":"unknown lemma","unknown_lemmas":list(filtered.unknown),
                                  "referenced_symbols":list(filtered.symbols)})
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
                    return SearchResult(proof,True,expanded,calls,trace,rejected,rejected_unknown)
                trace.append({"final_verification":False,"error":verification.output,"axioms":list(verification.axioms)})
                continue
            key=-cand.score if priority=="model" else float(depth+1)
            heapq.heappush(queue,(key,next(seq),depth+1,result.state))
    return SearchResult(None,False,expanded,calls,trace,rejected,rejected_unknown)
