"""Conservative replay extractor for simple one-tactic Mathlib declarations."""
from __future__ import annotations
import re
from pathlib import Path
from neuralproof.data.splits import split_for

MATHLIB_REVISION="56a005855ea17e0b0958f73ec801ae140b0a1679"
_HEADER=re.compile(r"^(?:protected\s+)?(?P<kind>theorem|lemma)\s+(?P<name>[\w.']+)(?P<rest>.*):= by\s*$")

def _source_imports(lines, stop):
    imports=[]
    for line in lines[:stop]:
        s=line.strip()
        if s=="prelude" or s=="module" or re.match(r"^(?:public\s+|meta\s+)?import\s+",s):
            imports.append(s)
    return imports

def _active_context(lines, stop, imports=None):
    frames=[]
    for line in lines[:stop]:
        s=line.strip()
        if re.match(r"^(?:namespace|section)(?:\s|$)",s):
            frames.append([s]); continue
        if s=="end" or s.startswith("end "):
            if frames:
                if s=="end": frames.pop()
                else:
                    name=s[4:].strip()
                    for j in range(len(frames)-1,-1,-1):
                        if frames[j][0].startswith("namespace ") and frames[j][0][10:]==name:
                            frames=frames[:j]; break
                        if frames[j][0]=="section" or frames[j][0].startswith("section "):
                            frames=frames[:j]; break
            continue
        if re.match(r"^(?:open(?:\s+scoped)?|variable|set_option|local notation|local instance|attribute \[local)",s):
            if frames: frames[-1].append(s)
            else: frames.append([s])
    active=[x for f in frames for x in f]
    header=imports if imports is not None else ["import Mathlib"]
    return "\n".join(header+active)

def extract_mathlib_file(client, mathlib_root: str | Path, relative_file: str, limit: int = 100, declaration: str | None = None):
    """Replay candidate single-line theorem proofs and retain only kernel-verified rows.

    This intentionally narrow parser reports unsupported candidate blocks. It is a
    usable real-data pilot, not a replacement for syntax/elaboration instrumentation.
    """
    root=Path(mathlib_root); path=root/relative_file; lines=path.read_text().splitlines()
    rows=[]; failures=[]; candidates=0; simple_headers=0
    declaration_headers=sum(1 for line in lines if re.match(r"\s*(?:(?:protected|private)\s+)?(?:theorem|lemma)\b",line))
    for i,line in enumerate(lines):
        match=_HEADER.match(line.strip())
        if not match: continue
        simple_headers+=1
        if declaration is not None and match.group("name")!=declaration: continue
        candidates+=1
        if i+1>=len(lines):
            failures.append({"line":i+1,"reason":"missing tactic body"}); continue
        body=lines[i+1]
        if not body.startswith("  ") or body.startswith(("   ","  ·","  case ")) or not body.strip():
            failures.append({"line":i+1,"name":match.group("name"),"reason":"unsupported tactic block"}); continue
        tactic=body.strip()
        if i+2<len(lines) and lines[i+2].startswith("  "):
            failures.append({"line":i+1,"name":match.group("name"),"reason":"multi-tactic proof not supported by this pilot"}); continue
        original=match.group("name")
        namespaces=re.findall(r"(?m)^namespace\s+([\w.']+)",_active_context(lines,i,[]))
        qualified=".".join(namespaces+[original])
        safe=re.sub(r"[^A-Za-z0-9_]","_",relative_file.replace("/","_").replace(".lean",""))
        safe_qualified=re.sub(r"[^A-Za-z0-9_]","_",qualified)
        new_name=f"np_mined_{safe}_{safe_qualified}"
        theorem=re.sub(r"^(?:protected\s+)?(?:theorem|lemma)\s+[\w.']+",f"{match.group('kind')} {new_name}",line.strip())
        # Use the source module's imports plus active namespace/local context.
        # Importing `Mathlib` here could import the theorem being mined and leak
        # its proof into the candidate environment. Earlier local declarations
        # are intentionally omitted; replay failures are retained in the stats.
        context=_active_context(lines,i,_source_imports(lines,i))
        state=client.initial_state(theorem.removesuffix(":= by").rstrip(),context)
        inspected=client.inspect(state)
        if not inspected.success or inspected.state is None:
            failures.append({"line":i+1,"name":original,"reason":"goal inspection failed","detail":inspected.error}); continue
        result=client.apply(inspected.state,tactic)
        if not result.success or not result.completed or result.state is None:
            failures.append({"line":i+1,"name":original,"reason":"tactic replay did not close goal","detail":result.error}); continue
        verified=client.verify(client.render_proof(result.state),context=context)
        if not verified.verified:
            failures.append({"line":i+1,"name":original,"reason":"final verification failed","detail":verified.output}); continue
        rows.append({"theorem_id":new_name,"theorem":state.theorem,"context":context,
            "goal_state":inspected.state.goal_state,"target_tactic":tactic,
            "source_file":relative_file,"source_line":i+1,"source_declaration":qualified,
            "source_revision":MATHLIB_REVISION,"split":split_for(relative_file)})
        if len(rows)>=limit: break
    stats={"source_file":relative_file,"source_revision":MATHLIB_REVISION,
           "context_policy":"source_imports_and_active_context_excluding_target",
           "declaration_headers_seen":declaration_headers,"recognized_simple_headers":simple_headers,
           "selected_candidates":candidates,"unrecognized_declaration_headers":declaration_headers-simple_headers,
           "verified_examples":len(rows),"failures":failures}
    return rows,stats
