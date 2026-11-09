import argparse,json,re,sys
from pathlib import Path
from neuralproof.lean.client import LeanClient
from neuralproof.models.predictor import StaticPredictor
from neuralproof.search.best_first import best_first

def parse_tactics(value):
    if isinstance(value, list):
        if not all(isinstance(x, str) for x in value):
            raise ValueError("--tactics JSON must be a string array")
        return value
    if value.lstrip().startswith("["):
        parsed=json.loads(value)
        if not isinstance(parsed,list) or not all(isinstance(x,str) for x in parsed): raise ValueError("--tactics JSON must be a string array")
        return parsed
    return value.split(",")


def _interactive_source(args):
    """The theorem header and context an interactive session starts from."""
    if args.theorem:
        return args.theorem.strip(), (args.context or "import Lean").strip() or "import Lean"
    if args.benchmark:
        if not args.theorem_id:
            raise SystemExit("--benchmark requires --theorem-id")
        rows=[json.loads(line) for line in Path(args.benchmark).read_text().splitlines() if line.strip()]
        row=next((r for r in rows if r.get("theorem_id")==args.theorem_id),None)
        if row is None:
            raise SystemExit(f"theorem_id {args.theorem_id!r} not found in {args.benchmark}")
        return row["theorem"], row.get("context","import Lean")
    if args.file:
        lines=Path(args.file).read_text().splitlines()
        start=next((i for i,line in enumerate(lines) if re.match(r"\s*(?:theorem|lemma)\s",line)),None)
        if start is None:
            raise SystemExit("No top-level theorem or lemma header found in file")
        end=start
        while end<len(lines) and ":=" not in lines[end]:
            end+=1
        if end>=len(lines):
            raise SystemExit("theorem header has no ':=' body")
        header="\n".join(lines[start:end+1])
        if ":= by" not in header:
            raise SystemExit("interactive mode needs a ':=' by proof")
        theorem=header.split(":= by",1)[0].rstrip()
        context="\n".join(lines[:start]).strip() or "import Lean"
        return theorem,context
    raise SystemExit("provide --file, --benchmark with --theorem-id, or --theorem")


def _default_interactive_tactics(context):
    """A small default portfolio; add ac_rfl only when Mathlib is imported.

    These are suggestions, not a proof strategy: every one still goes through
    Lean, and the user decides what to apply.
    """
    tactics = ["rfl", "trivial", "assumption", "simp", "omega", "exact True.intro"]
    if re.search(r"^\s*import\s+Mathlib", context, re.MULTILINE):
        tactics.append("ac_rfl")
    return tactics


def main():
    p=argparse.ArgumentParser(prog="neuralproof"); s=p.add_subparsers(dest="cmd",required=True); s.add_parser("doctor")
    d=s.add_parser("data"); ds=d.add_subparsers(dest="sub",required=True); e=ds.add_parser("extract"); e.add_argument("--limit",type=int,default=100); e.add_argument("--source",default="lean/NeuralProof/Samples.lean"); e.add_argument("--stats",default="data/raw/extraction_stats.json"); e.add_argument("--output",default="data/raw/sample.jsonl"); e.add_argument("--mathlib",action="store_true"); e.add_argument("--module",default="Mathlib/Data/Nat/Basic.lean"); e.add_argument("--declaration")
    c=ds.add_parser("corpus"); c.add_argument("--mathlib-root",default="lean/.lake/packages/mathlib"); c.add_argument("--files",type=int,default=200); c.add_argument("--per-file",type=int,default=5); c.add_argument("--seed",default="neuralproof-v1"); c.add_argument("--output",default="data/mathlib-200"); c.add_argument("--no-resume",action="store_true")
    tc=ds.add_parser("trace-corpus"); tc.add_argument("--mathlib-root",default="lean/.lake/packages/mathlib"); tc.add_argument("--files",type=int,default=200); tc.add_argument("--per-file",type=int,default=0); tc.add_argument("--seed",default="neuralproof-v1"); tc.add_argument("--timeout",type=float,default=300); tc.add_argument("--output",default="data/mathlib-info-tree-200"); tc.add_argument("--no-resume",action="store_true")
    rc=ds.add_parser("replay-corpus"); rc.add_argument("--input",required=True); rc.add_argument("--mathlib-root",default="lean/.lake/packages/mathlib"); rc.add_argument("--output",default="data/mathlib-info-tree-200-replayed"); rc.add_argument("--files",type=int,default=0); rc.add_argument("--timeout",type=float,default=300); rc.add_argument("--no-resume",action="store_true")
    ti=ds.add_parser("trace"); ti.add_argument("--file",required=True); ti.add_argument("--output",default="data/traces/latest.json"); ti.add_argument("--timeout",type=float,default=300)
    nt=ds.add_parser("normalize-trace"); nt.add_argument("--trace",required=True); nt.add_argument("--source",required=True); nt.add_argument("--output",required=True)
    rt=ds.add_parser("replay-trace"); rt.add_argument("--source",required=True); rt.add_argument("--output",default="data/validated/latest.jsonl"); rt.add_argument("--stats",default="data/validated/latest.stats.json"); rt.add_argument("--timeout",type=float,default=120)
    q=s.add_parser("prove"); q.add_argument("--file",required=True); q.add_argument("--tactics",default="rfl,assumption,exact True.intro"); q.add_argument("--model-id"); q.add_argument("--adapter"); q.add_argument("--revision"); q.add_argument("--filter-invalid-lemmas",action="store_true",help="refuse candidates that name a symbol absent from the lemma index and the goal state (experimental; Lean still checks every tried tactic)")
    tr=s.add_parser("train"); tr.add_argument("--data",required=True); tr.add_argument("--model",default="HuggingFaceTB/SmolLM2-135M"); tr.add_argument("--revision"); tr.add_argument("--output",default="experiments/smol-lora"); tr.add_argument("--epochs",type=int,default=1); tr.add_argument("--max-steps",type=int,default=-1,help="positive step budget, or -1 (the default) to train for the full number of epochs; 0 is rejected because it would stop the run after one step"); tr.add_argument("--seed",type=int,default=17); tr.add_argument("--resume"); tr.add_argument("--goal-scope",default="proof",help="only train on rows whose mined goal state has this scope; 'proof' keeps the states the live client actually reports, '' keeps every row")
    ev=s.add_parser("evaluate"); ev.add_argument("--data",required=True); ev.add_argument("--output",default="experiments/smoke/results.jsonl"); ev.add_argument("--tactics",default="rfl,trivial,assumption,exact True.intro"); ev.add_argument("--nodes",type=int,default=20); ev.add_argument("--width",type=int,default=4); ev.add_argument("--model-id"); ev.add_argument("--adapter"); ev.add_argument("--revision"); ev.add_argument("--priority",choices=["model","bfs"],default="model"); ev.add_argument("--no-deduplicate",action="store_true"); ev.add_argument("--filter-invalid-lemmas",action="store_true",help="refuse candidates that name a symbol absent from the lemma index and the goal state (experimental; Lean still checks every tried tactic)")
    et=s.add_parser("evaluate-tactics"); et.add_argument("--data",required=True); et.add_argument("--output",default="experiments/tactic-prediction/results.json"); et.add_argument("--model",default="HuggingFaceTB/SmolLM2-135M"); et.add_argument("--revision"); et.add_argument("--adapter",required=True); et.add_argument("--limit",type=int,default=100); et.add_argument("--seed",default="neuralproof-next-tactic-v1")
    pp=s.add_parser("preprocess"); pp.add_argument("--input",default="data/raw/sample.jsonl"); pp.add_argument("--output",default="data/processed"); pp.add_argument("--seed",default="neuralproof-v1"); pp.add_argument("--include-unvalidated",action="store_true",help="keep rows whose context was never replayed by Lean; they are stamped validation_status=unreplayed")
    rp=s.add_parser("report"); rp.add_argument("--results-dir",default="experiments")
    ia=s.add_parser("interact",help="step through a proof interactively; Lean checks every tactic and the final kernel result")
    ia.add_argument("--file"); ia.add_argument("--benchmark"); ia.add_argument("--theorem-id"); ia.add_argument("--theorem"); ia.add_argument("--context")
    ia.add_argument("--tactics",default=None,help="comma-separated or JSON list of candidate tactics; defaults to a small portfolio, plus ac_rfl when the context imports Mathlib"); ia.add_argument("--model-id"); ia.add_argument("--adapter"); ia.add_argument("--revision")
    ia.add_argument("--timeout",type=float,default=30); ia.add_argument("--max-suggestions",type=int,default=5)
    ia.add_argument("--auto-suggest",action=argparse.BooleanOptionalAction,default=True,help="show suggestions after every step (they are never applied automatically; default: on)")
    ia.add_argument("--rank-suggestions",action=argparse.BooleanOptionalAction,default=True,help="order suggestions by goal shape instead of predictor order (default: on)")
    ia.add_argument("--nodes",type=int,default=20); ia.add_argument("--width",type=int,default=None,help="candidates tried per search node; defaults to --max-suggestions"); ia.add_argument("--save-dir",default="experiments/interactive")
    a=p.parse_args()
    if a.cmd=="doctor": print(LeanClient().doctor()); print("Python",sys.version.split()[0]); return
    if a.cmd=="data":
        if a.sub=="trace":
            from neuralproof.data.info_tree import write_trace
            result=write_trace(a.file,a.output,timeout=a.timeout)
            print(json.dumps({k:v for k,v in result.items() if k!="traces"},ensure_ascii=False,indent=2)); return
        if a.sub=="normalize-trace":
            from neuralproof.data.normalize_info_tree import normalize_trace_file
            print(json.dumps(normalize_trace_file(a.trace,a.source,a.output),ensure_ascii=False,indent=2)); return
        if a.sub=="replay-trace":
            from neuralproof.data.info_tree import trace_file
            from neuralproof.data.normalize_info_tree import normalize_trace,validate_trace_examples
            trace=trace_file(a.source,timeout=max(a.timeout,300))
            rows,_=normalize_trace(trace,a.source)
            rows,stats=validate_trace_examples(trace,a.source,rows,timeout=a.timeout)
            out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows))
            stats_path=Path(a.stats); stats_path.parent.mkdir(parents=True,exist_ok=True)
            stats_path.write_text(json.dumps(stats,ensure_ascii=False,indent=2)+"\n")
            print(json.dumps({"rows":len(rows),"stats":stats,"output":str(out)},ensure_ascii=False,indent=2)); return
        if a.sub=="corpus":
            from neuralproof.data.corpus import extract_corpus
            result=extract_corpus(Path(a.mathlib_root),Path(a.output),files=a.files,per_file=a.per_file,seed=a.seed,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2)); return
        if a.sub=="trace-corpus":
            from neuralproof.data.info_tree_corpus import extract_info_tree_corpus
            result=extract_info_tree_corpus(Path(a.mathlib_root),Path(a.output),files=a.files,per_file=a.per_file,seed=a.seed,timeout=a.timeout,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2)); return
        if a.sub=="replay-corpus":
            from neuralproof.data.replay_corpus import replay_corpus
            result=replay_corpus(Path(a.input),Path(a.mathlib_root),Path(a.output),files=a.files,timeout=a.timeout,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2)); return
        if a.mathlib:
            from neuralproof.data.extraction import extract_mathlib_file
            root=Path("lean/.lake/packages/mathlib")
            if not (root/"Mathlib.lean").exists(): raise SystemExit("Pinned Mathlib checkout not found; run `cd lean && lake update` first")
            rows,stats=extract_mathlib_file(LeanClient(),root,a.module,a.limit,a.declaration)
            out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows))
            stats_path=Path(a.stats); stats_path.parent.mkdir(parents=True,exist_ok=True); stats_path.write_text(json.dumps(stats,indent=2))
            print(json.dumps({"written":len(rows),"failures":len(stats["failures"]),"source":a.module,"output":str(out),"stats":str(stats_path)})); return
        src=Path(a.source)
        if not src.exists(): raise SystemExit(f"Source unavailable: {src}; full Mathlib extraction needs a local Mathlib checkout")
        txt=src.read_text(); rows=[]; failures=[]; first_theorem=re.search(r"(?m)^theorem\s",txt); prelude=txt[:first_theorem.start()].strip() if first_theorem else "import Lean"; blocks=re.split(r"(?m)(?=^theorem\s)",txt)
        from neuralproof.data.splits import split_for
        client=LeanClient()
        for block in blocks:
            if len(rows)>=a.limit: break
            head=block.splitlines()[0] if block.splitlines() else ""
            if not head.startswith("theorem ") or ":=" not in head or not head.rstrip().endswith("by"): continue
            tactics=[]; unsupported=False
            for line in block.splitlines()[1:]:
                if not line.strip(): continue
                if not line.startswith("  "): break
                t=line.strip()
                if t.startswith(("·","case ","all_goals ","first |","by ")) or t in {"constructor"} and tactics:
                    unsupported=True; break
                tactics.append(t)
            if unsupported or not tactics:
                failures.append({"theorem":head,"reason":"unsupported tactic block (bullets, cases, or nested syntax)"}); continue
            theorem=head.rsplit(":= by",1)[0].rstrip(); state=client.initial_state(theorem,prelude or "import Lean"); inspection=client.inspect(state)
            if not inspection.success:
                failures.append({"theorem":head,"reason":"initial elaboration/state inspection failed","detail":inspection.error}); continue
            state=inspection.state
            for tactic in tactics:
                row=dict(theorem_id=re.search(r"theorem\s+(\S+)",head).group(1),theorem=theorem,context=state.context,goal_state=state.goal_state,target_tactic=tactic,source_file=str(src),split=split_for(str(src)))
                result=client.apply(state,tactic)
                if not result.success:
                    failures.append({"theorem":head,"tactic":tactic,"reason":"tactic replay failed","detail":result.error}); break
                rows.append(row); state=result.state
                if result.completed: break
        o=Path(a.output); o.parent.mkdir(parents=True,exist_ok=True); o.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows)); st=Path(a.stats); st.parent.mkdir(parents=True,exist_ok=True); st.write_text(json.dumps({"written":len(rows),"failures":failures,"source":str(src)},indent=2)); print(json.dumps({"written":len(rows),"failure_count":len(failures),"output":str(o),"stats":str(st)})); return
    if a.cmd=="prove":
        source=Path(a.file).read_text(); lines=source.splitlines(); idx=next((i for i,l in enumerate(lines) if l.startswith("theorem ")),None)
        if idx is None: raise SystemExit("No top-level theorem header found in file")
        context="\n".join(lines[:idx]).strip() or "import Lean"; theorem=lines[idx].split(":= by",1)[0].rstrip()
        predictor=StaticPredictor(parse_tactics(a.tactics))
        if a.model_id:
            from neuralproof.models.predictor import load_hf_predictor
            predictor=load_hf_predictor(a.model_id,a.adapter,a.revision)
        r=best_first(LeanClient(),theorem,predictor,context=context,max_nodes=30,width=3,filter_invalid_lemmas=a.filter_invalid_lemmas)
        print(json.dumps(vars(r),indent=2)); return
    if a.cmd=="preprocess":
        from neuralproof.data.preprocessing import prepare_dataset
        from neuralproof.data.provenance import (code_diff_sha256,code_revision,current_command,sha256_file,working_tree_state,write_manifest)
        dest=Path(a.output); dest.mkdir(parents=True,exist_ok=True)
        source_path=Path(a.input)
        source_rows=[json.loads(ln) for ln in source_path.read_text().splitlines() if ln.strip()]
        result=prepare_dataset(source_rows,seed=a.seed,include_unvalidated=a.include_unvalidated)
        for name,rows in result.groups.items(): (dest/f"{name}.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows))
        manifest={"schema_version":1,"artifact":"processed_tactic_rows","command":current_command(),
                  "code_revision":code_revision(),"code_state":working_tree_state(),
                  "code_diff_sha256":code_diff_sha256(),"split_seed":result.split_seed,
                  "input":{"path":str(source_path),"sha256":sha256_file(source_path),"rows":len(source_rows)},
                  "outputs":{name:{"path":str(dest/f"{name}.jsonl"),"rows":len(rows),"sha256":sha256_file(dest/f"{name}.jsonl")} for name,rows in result.groups.items()},
                  "split_counts":{name:len(rows) for name,rows in result.groups.items()},
                  "excluded_unvalidated":result.excluded_unvalidated,
                  "excluded_non_tactic_targets":result.excluded_non_tactic_targets,
                  "include_unvalidated":result.include_unvalidated,
                  "split_disagreements":result.split_disagreements,
                  "goal_scope_counts":result.goal_scope_counts,
                  "validation_status_counts":result.validation_status_counts,
                  "validation_policy":"rows are included only when validation is replayed, declaration_replayed, or absent; --include-unvalidated keeps the rest and stamps them unreplayed",
                  "goal_scope_policy":"proof = mined state is the proof-global goal list; focus = mined inside a tactic focus; conv = mined conv subgoal",
                  "label_policy":"rows whose target is not a tactic (the `by` of a header, the `where` of a structure instance, a brace, a placeholder) are excluded; no tactic can answer them",
                  "caveats":["rows marked validation_status=unreplayed were never replayed by Lean and are not verified proofs",
                             "rows marked goal_scope=focus were mined inside a tactic focus and do not match the proof-global state the live client reports",
                             "code_diff_sha256 is taken before this manifest is written, and the manifest is itself a tracked file, so the digest identifies the code and inputs that produced the rows and not the tree that includes this manifest"]}
        write_manifest(dest/"manifest.json",manifest)
        print(json.dumps({**{k:len(v) for k,v in result.groups.items()},"excluded_unvalidated":result.excluded_unvalidated,
                          "excluded_non_tactic_targets":result.excluded_non_tactic_targets,
                          "include_unvalidated":result.include_unvalidated,
                          "split_disagreements":result.split_disagreements,"goal_scope_counts":result.goal_scope_counts,
                          "validation_status_counts":result.validation_status_counts,
                          "split_seed":result.split_seed,"input_rows":len(source_rows),"manifest":str(dest/"manifest.json")})); return
    if a.cmd=="train":
        from neuralproof.models.finetune import train
        train(a.data,a.model,a.output,a.revision,a.epochs,a.seed,a.resume,a.max_steps,a.goal_scope); return
    if a.cmd=="evaluate":
        from neuralproof.evaluation.benchmark import run
        from neuralproof.evaluation.metrics import summarize
        rows=[json.loads(x) for x in Path(a.data).read_text().splitlines() if x.strip()]
        predictor=StaticPredictor(parse_tactics(a.tactics))
        if a.model_id:
            from neuralproof.models.predictor import load_hf_predictor
            predictor=load_hf_predictor(a.model_id,a.adapter,a.revision)
        try:
            results=run(rows,LeanClient(),predictor,a.output,max_nodes=a.nodes,width=a.width,priority=a.priority,deduplicate=not a.no_deduplicate,filter_invalid_lemmas=a.filter_invalid_lemmas)
        except ValueError as error:
            raise SystemExit(str(error))
        summary=summarize(results); print(json.dumps(summary)); return
    if a.cmd=="evaluate-tactics":
        from neuralproof.evaluation.tactic_prediction import evaluate_tactic_prediction
        result=evaluate_tactic_prediction(a.data,a.output,base_model=a.model,revision=a.revision,adapter=a.adapter,limit=a.limit,seed=a.seed)
        print(json.dumps({k:{x:v for x,v in value.items() if x!="examples"} if isinstance(value,dict) else value for k,value in result.items()},ensure_ascii=False,indent=2)); return
    if a.cmd=="interact":
        from neuralproof.interactive import ProofSession,run_repl
        theorem,context=_interactive_source(a)
        tactics = a.tactics if a.tactics is not None else _default_interactive_tactics(context)
        predictor=StaticPredictor(parse_tactics(tactics))
        model_id=a.model_id or ("HuggingFaceTB/SmolLM2-135M" if a.adapter else None)
        if model_id:
            from neuralproof.models.predictor import load_hf_predictor
            predictor=load_hf_predictor(model_id,a.adapter,a.revision)
        try:
            session=ProofSession(LeanClient(timeout=a.timeout),theorem,context=context,predictor=predictor,max_suggestions=a.max_suggestions,rank_suggestions=a.rank_suggestions)
        except RuntimeError as error:
            raise SystemExit(str(error))
        width = a.width if a.width is not None else a.max_suggestions
        return run_repl(session,save_dir=a.save_dir,auto_suggest=a.auto_suggest,search_budget={"max_nodes":a.nodes,"width":width,"timeout":a.timeout})
    if a.cmd=="report":
        from neuralproof.evaluation.metrics import summarize
        for f in sorted(Path(a.results_dir).rglob("results.jsonl")):
            rows=[json.loads(x) for x in f.read_text().splitlines() if x.strip()]; print(json.dumps({"file":str(f),**summarize(rows)}))
        return
if __name__=="__main__": main()
