# Mathlib-derived sample attribution

`mathlib_mined.jsonl` contains one proof trajectory extracted from Mathlib4:

- Source: `Mathlib/Data/Nat/Basic.lean`, declaration `Nat.div_right_comm` (line 58)
- Revision: `56a005855ea17e0b0958f73ec801ae140b0a1679`
- License: Apache-2.0; see `MATHLIB-LICENSE.txt`
- The theorem is renamed in the replay file. Its context uses the source imports and active namespace/open/variable directives, excluding the target theorem itself.
- The candidate tactic replay closed the goal and the final declaration passed Lean kernel verification.

The earlier five-row pilot used `import Mathlib` as reconstructed context. A later leakage audit found that this could expose the source theorem to the candidate proof; that dataset was replaced and its training smoke result is retained only as historical, non-evaluation evidence.
