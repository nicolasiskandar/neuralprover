#!/usr/bin/env python3
"""Analyze lemma usage patterns for failing tactic families.

The lemma extractor is imported from :mod:`neuralproof.lemmas`, so this report
cannot diverge from the pre-filter that search actually applies.  Paths are
explicit; every default names a reproducible artifact under `experiments/`.
"""

import argparse
import json
import re
import collections
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.lemmas import extract_symbol_heads  # noqa: E402

EVAL_PATH = Path("experiments/mathlib-info-tree-lora-200-1epoch-canonical/tactic-eval-full-heldout.json")
EXAMPLES_PATH = Path("data/mathlib-info-tree-200/examples.jsonl")
TRAIN_PATH = Path("data/mathlib-info-tree-200/processed/train.jsonl")
SEARCH_TRACE_PATH = Path("/tmp/search-lora-n100-w8")
OUT_PATH = Path("experiments/mathlib-info-tree-lora-200-1epoch-canonical/lemma_analysis.md")


def extract_lemmas_from_tactic(tactic: str) -> list[str]:
    """Backwards-compatible alias for the shared extractor."""
    return extract_symbol_heads(tactic)


def tactic_head(tactic):
    """Extract the first token/command from a tactic."""
    tactic = tactic.strip()
    if not tactic:
        return "<empty>"
    parts = tactic.split()
    if not parts:
        return "<empty>"
    return parts[0]


def lemma_in_text(lemma, text):
    """Check if lemma appears in text."""
    if not text or not lemma:
        return False
    # Look for the lemma as a word boundary match
    pattern = r'\b' + re.escape(lemma.split('.')[-1]) + r'\b'
    if re.search(pattern, text):
        return True
    pattern = r'\b' + re.escape(lemma) + r'\b'
    if re.search(pattern, text):
        return True
    return False


def main(args=None):
    global EVAL_PATH, EXAMPLES_PATH, TRAIN_PATH, SEARCH_TRACE_PATH, OUT_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", type=Path, default=EVAL_PATH,
                        help="tactic-eval JSON produced by evaluate-tactics")
    parser.add_argument("--examples", type=Path, default=EXAMPLES_PATH,
                        help="JSONL corpus with example_id, context, and goal_state")
    parser.add_argument("--train", type=Path, default=TRAIN_PATH,
                        help="preprocessed JSONL training split")
    parser.add_argument("--search-trace", type=Path, default=SEARCH_TRACE_PATH,
                        help="optional JSONL search trace to summarize")
    parser.add_argument("--output", type=Path, default=OUT_PATH,
                        help="Markdown output path")
    namespace = parser.parse_args(args)
    EVAL_PATH = namespace.eval
    EXAMPLES_PATH = namespace.examples
    TRAIN_PATH = namespace.train
    SEARCH_TRACE_PATH = namespace.search_trace
    OUT_PATH = namespace.output

    print("# Lemma Usage Analysis")
    print()
    
    # Load data
    with open(EVAL_PATH) as f:
        eval_data = json.load(f)
    
    examples = {}
    with open(EXAMPLES_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            example_id = row.get('example_id')
            if example_id:
                examples[example_id] = row
    
    # Load training lemmas
    train_lemmas = collections.Counter()
    with open(TRAIN_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            target = row.get('target_tactic', '')
            lemmas = extract_lemmas_from_tactic(target)
            for lem in lemmas:
                train_lemmas[lem] += 1
    
    print(f"Loaded {len(train_lemmas)} unique lemmas from training data")
    print()
    
    # Merge eval
    base_examples = {ex['example_id']: ex for ex in eval_data['base']['examples']}
    lora_examples = {ex['example_id']: ex for ex in eval_data['lora']['examples']}
    
    merged = []
    for ex_id in base_examples:
        if ex_id not in lora_examples:
            continue
        base_ex = base_examples[ex_id]
        lora_ex = lora_examples[ex_id]
        orig = examples.get(ex_id, {})
        merged.append({
            'example_id': ex_id,
            'goal_state': orig.get('goal_state', ''),
            'context': orig.get('context', ''),
            'target': base_ex['target'],
            'lora_pred': lora_ex['prediction'],
            'lora_match': lora_ex['exact_match'],
            'target_head': tactic_head(base_ex['target']),
            'lora_head': tactic_head(lora_ex['prediction']),
        })
    
    # Focus on failing families
    failing_families = ['rw', 'apply', 'exact', 'simpa', 'simp']
    
    print("## Executive Summary")
    print()
    
    for family in failing_families:
        fam_examples = [m for m in merged if m['target_head'] == family]
        correct = sum(1 for m in fam_examples if m['lora_match'])
        if fam_examples:
            print(f"- **`{family}`**: {correct}/{len(fam_examples)} correct ({correct/len(fam_examples):.1%}), {len(fam_examples)} total attempts")
    print()
    
    # Analyze each failing family
    for family in failing_families:
        print(f"## Analysis: `{family}`")
        print()
        fam_examples = [m for m in merged if m['target_head'] == family]
        
        if not fam_examples:
            continue
        
        # Categories
        correct_examples = []
        wrong_same_family = []
        wrong_different_family = []
        
        for m in fam_examples:
            if m['lora_match']:
                correct_examples.append(m)
            elif m['lora_head'] == family:
                wrong_same_family.append(m)
            else:
                wrong_different_family.append(m)
        
        print(f"**Breakdown:** {len(correct_examples)} correct, {len(wrong_same_family)} wrong (same family), {len(wrong_different_family)} wrong (different family)")
        print()
        
        # Analyze correct examples
        if correct_examples:
            print(f"### Correct `{family}` predictions")
            print()
            print("| Example | Target Lemmas | In Context? | In Training? |")
            print("| :-- | :-- | :-- | :-- |")
            for m in correct_examples[:15]:
                target_lemmas = extract_lemmas_from_tactic(m['target'])
                if not target_lemmas:
                    print(f"| {m['example_id'][:50]} | (no lemmas) | - | - |")
                    continue
                for i, lem in enumerate(target_lemmas):
                    in_ctx = lemma_in_text(lem, m['context'] + '\n' + m['goal_state'])
                    in_train = lem in train_lemmas
                    in_ctx_str = "✓" if in_ctx else "✗"
                    in_train_str = f"✓ ({train_lemmas[lem]}x)" if in_train else "✗"
                    ex_id = m['example_id'][:50] if i == 0 else ""
                    print(f"| {ex_id} | `{lem}` | {in_ctx_str} | {in_train_str} |")
            print()
        
        # Analyze wrong predictions in same family
        if wrong_same_family:
            print(f"### Wrong `{family}` predictions (same family - lemma selection issue)")
            print()
            print("| Example | Target Lemmas | Predicted Lemmas | Target in Ctx? | Pred in Ctx? | Pred in Train? |")
            print("| :-- | :-- | :-- | :-- | :-- | :-- |")
            for m in wrong_same_family[:20]:
                target_lemmas = extract_lemmas_from_tactic(m['target'])
                pred_lemmas = extract_lemmas_from_tactic(m['lora_pred'])
                
                target_lem_str = ', '.join(f'`{l}`' for l in target_lemmas) if target_lemmas else '(none)'
                pred_lem_str = ', '.join(f'`{l}`' for l in pred_lemmas) if pred_lemmas else '(none)'
                
                target_in_ctx = any(lemma_in_text(l, m['context'] + '\n' + m['goal_state']) for l in target_lemmas) if target_lemmas else False
                pred_in_ctx = any(lemma_in_text(l, m['context'] + '\n' + m['goal_state']) for l in pred_lemmas) if pred_lemmas else False
                pred_in_train = any(l in train_lemmas for l in pred_lemmas) if pred_lemmas else False
                
                target_ctx_str = "✓" if target_in_ctx else "✗"
                pred_ctx_str = "✓" if pred_in_ctx else "✗"
                pred_train_str = "✓" if pred_in_train else "✗"
                
                print(f"| {m['example_id'][:40]} | {target_lem_str} | {pred_lem_str} | {target_ctx_str} | {pred_ctx_str} | {pred_train_str} |")
            print()
    
    # Overall hallucination stats
    print("## Hallucination Statistics")
    print()
    
    all_wrong_with_lemmas = []
    for family in failing_families:
        fam_examples = [m for m in merged if m['target_head'] == family and not m['lora_match'] and m['lora_head'] == family]
        for m in fam_examples:
            pred_lemmas = extract_lemmas_from_tactic(m['lora_pred'])
            for lem in pred_lemmas:
                in_ctx = lemma_in_text(lem, m['context'] + '\n' + m['goal_state'])
                in_train = lem in train_lemmas
                all_wrong_with_lemmas.append({
                    'lemma': lem,
                    'in_context': in_ctx,
                    'in_train': in_train,
                    'example': m['example_id']
                })
    
    if all_wrong_with_lemmas:
        copied = sum(1 for x in all_wrong_with_lemmas if x['in_context'])
        seen_train = sum(1 for x in all_wrong_with_lemmas if not x['in_context'] and x['in_train'])
        hallucinated = sum(1 for x in all_wrong_with_lemmas if not x['in_context'] and not x['in_train'])
        total = len(all_wrong_with_lemmas)
        
        print(f"**For wrong predictions in same tactic family (lemma selection errors):**")
        print()
        print(f"- Copied from context: {copied}/{total} ({copied/total:.1%})")
        print(f"- Not in context, but seen in training: {seen_train}/{total} ({seen_train/total:.1%})")
        print(f"- Not in context and not in training (hallucinated): {hallucinated}/{total} ({hallucinated/total:.1%})")
        print()
        
        print("### Hallucinated lemmas (not in context, not in training)")
        print()
        for x in all_wrong_with_lemmas:
            if not x['in_context'] and not x['in_train']:
                print(f"- `{x['lemma']}` (from {x['example'][:60]})")
        print()
    
    # Search trace analysis
    print("## Search Trace Analysis (n=100, w=8)")
    print()
    if SEARCH_TRACE_PATH.exists():
        try:
            with open(SEARCH_TRACE_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    trace = json.loads(line)
                    print(f"### Theorem: {trace['theorem_id']}")
                    print()
                    print(f"- Solved: {trace['verified']}")
                    print(f"- Expanded: {trace['expanded']}, Tactic calls: {trace['tactic_calls']}, Invalid: {trace['invalid_tactics']}, Timeouts: {trace['timeouts']}")
                    print()
                    
                    # Analyze suggestions
                    rw_simp_suggestions = []
                    for entry in trace['search_trace']:
                        if entry.get('depth', -1) == 0 and 'tactic' in entry:
                            tactic = entry['tactic']
                            head = tactic_head(tactic)
                            if head in ['rw', 'simp', 'apply', 'exact', 'simpa']:
                                lemmas = extract_lemmas_from_tactic(tactic)
                                rw_simp_suggestions.append({
                                    'tactic': tactic,
                                    'head': head,
                                    'lemmas': lemmas,
                                    'success': entry.get('success', False)
                                })
                    
                    print(f"**Root-level suggestions ({len(rw_simp_suggestions)}):**")
                    print()
                    for s in rw_simp_suggestions[:15]:
                        status = "✓" if s['success'] else "✗"
                        lem_str = ', '.join(f'`{l}`' for l in s['lemmas']) if s['lemmas'] else '(none)'
                        print(f"- {status} `{s['tactic'][:80]}` - lemmas: {lem_str}")
                    print()
        except Exception as e:
            print(f"Error reading search trace: {e}")
            print()
    else:
        print("Search trace not found")
        print()
    
    # Recommendations
    print("## Recommendations")
    print()
    print("Based on this analysis, and on the retrieval-feasibility measurement:")
    print()
    print("1. **Retrieval is not yet a solution.** Lexical BM25 over theorem names and")
    print("   pretty-printed statements recalled a gold lemma in the top 20 for only")
    print("   34.5% of the 84 applicable held-out rows (name-only: 10.7%). Excluding")
    print("   the target's own module drops that to 9.5%, so the positive result is")
    print("   also partly explained by near-duplicate declarations. See")
    print("   `experiments/retrieval-feasibility/README.md`; do not present these")
    print("   recall numbers as proof-solving performance.")
    print("2. **Constrained decoding is already covered by the pre-filter.** It refuses")
    print("   names that cannot resolve in the current environment and state, but it")
    print("   cannot choose the right lemma. The filter is opt-in and is a budget")
    print("   heuristic, not a correctness check.")
    print("3. **Two-stage prediction is still a candidate, conditional on better")
    print("   retrieval.** The model is comparatively good at lemma-free tactics")
    print("   (`simp`, `ext`, `rfl`), so predicting a skeleton and filling lemma")
    print("   arguments is plausible. The next measurement should be embedding/hybrid")
    print("   retrieval (or a model reranker) on the same 84 rows before any prompt or")
    print("   training change.")
    print("4. **Change the evaluation target too.** Exact match on a source tactic is")
    print("   only a diagnostic. A retrieval or two-stage method should be judged by")
    print("   kernel-verified next-tactic acceptance or bounded proof search, never by")
    print("   retrieval recall alone.")
    print()


if __name__ == '__main__':
    from io import StringIO
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        main()
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    print(output)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(output)
    print(f"\n\nAnalysis written to {OUT_PATH}", file=sys.stderr)
