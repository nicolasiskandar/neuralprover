"""Rebuild the small cross-module Mathlib data pilot at the pinned revision."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from neuralproof.data.extraction import MATHLIB_REVISION,extract_mathlib_file
from neuralproof.lean.client import LeanClient

ROOT=Path(__file__).parents[1]
MATHLIB=ROOT/"lean/.lake/packages/mathlib"
SOURCES=[
    ("Mathlib/Data/Nat/Basic.lean",None,3),
    ("Mathlib/Algebra/MvPolynomial/Basic.lean","notMem_support_iff",1),
    ("Mathlib/Algebra/Group/Basic.lean","mul_div_mul_left_eq_div",1),
]

def main():
    client=LeanClient(); rows=[]; module_stats=[]
    for module,declaration,limit in SOURCES:
        found,stats=extract_mathlib_file(client,MATHLIB,module,limit,declaration)
        rows.extend(found); module_stats.append(stats)
    out=ROOT/"data/raw/mathlib_mined.jsonl"; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows))
    stats={"source_revision":MATHLIB_REVISION,"verified_examples":len(rows),"modules":module_stats}
    (ROOT/"data/raw/mathlib_mined_stats.json").write_text(json.dumps(stats,indent=2)+"\n")
    print(json.dumps({"verified_examples":len(rows),"output":str(out),"stats":str(ROOT/"data/raw/mathlib_mined_stats.json")}))

if __name__=="__main__": main()
