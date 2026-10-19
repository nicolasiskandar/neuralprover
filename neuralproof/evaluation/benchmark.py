"""Evaluate JSONL theorem headers with a predictor and fixed search budget."""
import csv,json,time
from pathlib import Path
from neuralproof.search.best_first import best_first

def run(rows,client,predictor,output,**budget):
    out=[]
    for row in rows:
        t=time.monotonic(); r=best_first(client,row["theorem"],predictor,context=row.get("context","import Lean"),**budget)
        invalid=sum(1 for x in r.trace if x.get("success") is False); timed_out=sum(1 for x in r.trace if "timed out" in x.get("error",""))
        out.append({"theorem_id":row.get("theorem_id"),"verified":r.verified,"proof":r.proof,
            "search_trace":r.trace,"solve_seconds":time.monotonic()-t,"expanded":r.expanded,
            "tactic_calls":r.tactic_calls,"invalid_tactics":invalid,"timeouts":timed_out,
            "inference_tokens":None,"gpu_seconds":None,"gpu_memory_mb":None})
    target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text("".join(json.dumps(x)+"\n" for x in out))
    if out:
        with target.with_suffix(".csv").open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=out[0].keys()); writer.writeheader(); writer.writerows(out)
        from neuralproof.evaluation.metrics import summarize
        target.with_name("summary.json").write_text(json.dumps(summarize(out),indent=2)+"\n")
    return out
