import heapq,time
from dataclasses import dataclass,field
from itertools import count
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

def best_first(client,theorem,predictor,*,context="import Lean",max_nodes=50,width=5,timeout=30,max_depth=12,deduplicate=True,priority="model"):
    start=time.monotonic(); seq=count(); initial=client.inspect(client.initial_state(theorem,context)); seen=set(); expanded=calls=0; trace=[]
    if not initial.success or initial.state is None:
        return SearchResult(None,False,0,0,[{"initial_state_inspection":False,"error":initial.error}])
    trace.append({"initial_state_inspection":True,"goals":list(initial.state.goals)})
    queue=[(0.,next(seq),0,initial.state)]
    while queue and expanded<max_nodes and time.monotonic()-start<timeout:
        _,_,depth,state=heapq.heappop(queue)
        if deduplicate and state.prefix in seen: continue
        seen.add(state.prefix); expanded+=1
        if depth>=max_depth: continue
        for cand in predictor.predict(state,width):
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
                    return SearchResult(proof,True,expanded,calls,trace)
                trace.append({"final_verification":False,"error":verification.output,"axioms":list(verification.axioms)})
                continue
            key=-cand.score if priority=="model" else float(depth+1)
            heapq.heappush(queue,(key,next(seq),depth+1,result.state))
    return SearchResult(None,False,expanded,calls,trace)
