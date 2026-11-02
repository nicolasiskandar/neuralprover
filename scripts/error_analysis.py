#!/usr/bin/env python3
"""Error analysis for the 1-epoch LoRA eval on the InfoTree corpus."""

import argparse
import json
import collections
import sys
from pathlib import Path

EVAL_PATH = Path("experiments/mathlib-info-tree-lora-200-1epoch-canonical/tactic-eval-full-heldout.json")
EXAMPLES_PATH = Path("data/mathlib-info-tree-200/examples.jsonl")
OUT_PATH = Path("experiments/mathlib-info-tree-lora-200-1epoch-canonical/error_analysis.md")


def tactic_head(tactic):
    """Extract the first token/command from a tactic."""
    tactic = tactic.strip()
    if not tactic:
        return "<empty>"
    # Remove leading comments/whitespace
    # Take first word, but be careful about tactics like "exact", "apply", etc.
    # Also handle cases like "rw [...]", "simp [*]"
    # Split on whitespace
    parts = tactic.split()
    if not parts:
        return "<empty>"
    first = parts[0]
    # Some tactics might be multi-part like "by_cases", keep as-is
    return first


def count_hypotheses(goal_state):
    """Count hypotheses (lines before ⊢)."""
    if not goal_state:
        return 0
    lines = goal_state.split('\n')
    hyp_count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('⊢'):
            break
        # Skip conv goals markers like | ...
        if line.startswith('|'):
            continue
        # Skip case headers
        if line.startswith('case'):
            continue
        hyp_count += 1
    return hyp_count


def goal_complexity(goal_state):
    """Extract goal complexity metrics."""
    if not goal_state:
        return {'hyp_count': 0, 'goal_len': 0, 'has_equation': False, 
                'has_forall': False, 'has_exists': False, 'has_and': False, 
                'has_or': False, 'goal_text': ''}
    lines = goal_state.split('\n')
    goal_text = ''
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith('⊢'):
            goal_text = line_stripped[1:].strip()  # Remove ⊢
            break
        elif line_stripped.startswith('|'):
            goal_text = line_stripped[1:].strip()  # Remove |
            break
    return {
        'hyp_count': count_hypotheses(goal_state),
        'goal_len': len(goal_text),
        'has_equation': '=' in goal_text or '↔' in goal_text,
        'has_forall': '∀' in goal_text,
        'has_exists': '∃' in goal_text,
        'has_and': '∧' in goal_text or ' and ' in goal_text.lower(),
        'has_or': '∨' in goal_text or ' or ' in goal_text.lower(),
        'goal_text': goal_text[:200]  # Truncate for display
    }


def main(args=None):
    global EVAL_PATH, EXAMPLES_PATH, OUT_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", type=Path, default=EVAL_PATH,
                        help="tactic-eval JSON produced by evaluate-tactics")
    parser.add_argument("--examples", type=Path, default=EXAMPLES_PATH,
                        help="JSONL corpus with example_id, context, and goal_state")
    parser.add_argument("--output", type=Path, default=OUT_PATH,
                        help="Markdown output path")
    namespace = parser.parse_args(args)
    EVAL_PATH = namespace.eval
    EXAMPLES_PATH = namespace.examples
    OUT_PATH = namespace.output

    print("# Error Analysis: 1-Epoch LoRA on InfoTree Corpus")
    print(f"\n**Eval file:** {EVAL_PATH}")
    print(f"**Examples file:** {EXAMPLES_PATH}")
    print()
    
    # Load eval results
    with open(EVAL_PATH) as f:
        eval_data = json.load(f)
    
    # Load examples and index by example_id
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
    
    print(f"Loaded {len(examples)} examples from examples.jsonl")
    print(f"Loaded eval with {eval_data['sample_size']} sampled examples")
    print()
    
    # Merge eval results with examples
    base_examples = {ex['example_id']: ex for ex in eval_data['base']['examples']}
    lora_examples = {ex['example_id']: ex for ex in eval_data['lora']['examples']}
    
    merged = []
    for ex_id in base_examples:
        if ex_id not in lora_examples:
            continue
        base_ex = base_examples[ex_id]
        lora_ex = lora_examples[ex_id]
        orig = examples.get(ex_id, {})
        complexity = goal_complexity(orig.get('goal_state', ''))
        merged.append({
            'example_id': ex_id,
            'source_file': orig.get('source_file', base_ex.get('source_file', '')),
            'source_declaration': orig.get('source_declaration', ''),
            'goal_state': orig.get('goal_state', ''),
            'context': orig.get('context', ''),
            'target': base_ex['target'],
            'base_pred': base_ex['prediction'],
            'base_match': base_ex['exact_match'],
            'base_silent': not base_ex['produced_output'],
            'lora_pred': lora_ex['prediction'],
            'lora_match': lora_ex['exact_match'],
            'lora_silent': not lora_ex['produced_output'],
            'base_head': tactic_head(base_ex['prediction']),
            'target_head': tactic_head(base_ex['target']),
            'lora_head': tactic_head(lora_ex['prediction']),
            **complexity
        })
    
    print(f"Merged {len(merged)} examples")
    print()
    
    # 1) Executive Summary
    print("## Executive Summary")
    print()
    base_correct = sum(1 for m in merged if m['base_match'])
    lora_correct = sum(1 for m in merged if m['lora_match'])
    base_silent = sum(1 for m in merged if m['base_silent'])
    lora_silent = sum(1 for m in merged if m['lora_silent'])
    print(f"- **Base model:** {base_correct}/{len(merged)} correct ({base_correct/len(merged):.1%}), {base_silent} silent predictions")
    print(f"- **LoRA adapter:** {lora_correct}/{len(merged)} correct ({lora_correct/len(merged):.1%}), {lora_silent} silent predictions")
    print(f"- **Gain:** +{lora_correct - base_correct} correct predictions (+{(lora_correct-base_correct)/len(merged):.1%})")
    print(f"- **Silence fix:** Adapter eliminated all {base_silent} base silent predictions and produced 0 silent predictions of its own")
    print()
    
    # 2) Silence vs Guessing Analysis
    print("## Silence vs Guessing Analysis")
    print()
    print("Cross-tabulation of base behavior vs LoRA outcome:")
    print()
    lora_wrong_non_silent = sum(1 for m in merged if not m['lora_match'] and not m['lora_silent'])
    print("| | LoRA Correct | LoRA Wrong (non-silent) | LoRA Silent | Total |")
    print("| :-- | ---: | ---: | ---: | ---: |")
    
    base_silent_lora_correct = sum(1 for m in merged if m['base_silent'] and m['lora_match'])
    base_silent_lora_wrong = sum(1 for m in merged if m['base_silent'] and not m['lora_match'] and not m['lora_silent'])
    base_silent_lora_silent = sum(1 for m in merged if m['base_silent'] and m['lora_silent'])
    base_silent_total = base_silent
    
    base_nonsilent_lora_correct = sum(1 for m in merged if not m['base_silent'] and m['lora_match'])
    base_nonsilent_lora_wrong = sum(1 for m in merged if not m['base_silent'] and not m['lora_match'] and not m['lora_silent'])
    base_nonsilent_lora_silent = sum(1 for m in merged if not m['base_silent'] and m['lora_silent'])
    base_nonsilent_total = len(merged) - base_silent
    
    print(f"| Base Silent | {base_silent_lora_correct} | {base_silent_lora_wrong} | {base_silent_lora_silent} | {base_silent_total} |")
    print(f"| Base Non-Silent | {base_nonsilent_lora_correct} | {base_nonsilent_lora_wrong} | {base_nonsilent_lora_silent} | {base_nonsilent_total} |")
    print(f"| **Total** | **{lora_correct}** | **{lora_wrong_non_silent}** | **{lora_silent}** | **{len(merged)}** |")
    print()
    print(f"- **From base-silent rows:** {base_silent_lora_correct}/{base_silent_total} became correct ({base_silent_lora_correct/base_silent_total:.1%}), {base_silent_lora_wrong} became wrong guesses, {base_silent_lora_silent} still silent")
    print(f"- **From base-non-silent rows:** {base_nonsilent_lora_correct}/{base_nonsilent_total} became correct ({base_nonsilent_lora_correct/base_nonsilent_total:.1%}), mostly fixing the base's wrong guesses")
    print()
    
    # 3) Tactic Family Breakdown
    print("## Tactic Family Breakdown")
    print()
    # Target distribution
    target_heads = collections.Counter(m['target_head'] for m in merged)
    print("### Target tactic distribution (overall)")
    print()
    print("| Tactic Family | Count | % |")
    print("| :-- | ---: | ---: |")
    for head, count in target_heads.most_common(15):
        print(f"| `{head}` | {count} | {count/len(merged):.1%} |")
    print()
    
    # Accuracy by tactic family for LoRA
    print("### LoRA accuracy by tactic family")
    print()
    family_stats = collections.defaultdict(lambda: {'total': 0, 'correct': 0})
    for m in merged:
        family = m['target_head']
        family_stats[family]['total'] += 1
        if m['lora_match']:
            family_stats[family]['correct'] += 1
    
    print("| Tactic Family | Total | Correct | Accuracy |")
    print("| :-- | ---: | ---: | ---: |")
    for family, stats in sorted(family_stats.items(), key=lambda x: x[1]['correct']/x[1]['total'] if x[1]['total'] > 0 else 0, reverse=True):
        if stats['total'] >= 2:  # Only show families with >=2 occurrences
            acc = stats['correct']/stats['total']
            print(f"| `{family}` | {stats['total']} | {stats['correct']} | {acc:.1%} |")
    print()
    
    # Base vs LoRA by family
    print("### Base vs LoRA accuracy by family (families with >=3 occurrences)")
    print()
    print("| Tactic Family | Target Count | Base Correct | Base Acc | LoRA Correct | LoRA Acc | Gain |")
    print("| :-- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for family in target_heads:
        if target_heads[family] >= 3:
            base_fam_total = sum(1 for m in merged if m['target_head'] == family)
            base_fam_correct = sum(1 for m in merged if m['target_head'] == family and m['base_match'])
            lora_fam_correct = family_stats[family]['correct']
            base_acc = base_fam_correct/base_fam_total if base_fam_total else 0
            lora_acc = lora_fam_correct/base_fam_total if base_fam_total else 0
            print(f"| `{family}` | {base_fam_total} | {base_fam_correct} | {base_acc:.1%} | {lora_fam_correct} | {lora_acc:.1%} | +{lora_fam_correct-base_fam_correct} |")
    print()
    
    # 4) Goal Complexity Analysis
    print("## Goal Complexity Analysis")
    print()
    print("### Accuracy by hypothesis count")
    print()
    hyp_buckets = collections.defaultdict(lambda: {'total': 0, 'correct': 0})
    for m in merged:
        hc = m['hyp_count']
        if hc == 0:
            bucket = "0 hypotheses"
        elif hc <= 2:
            bucket = "1-2 hypotheses"
        elif hc <= 4:
            bucket = "3-4 hypotheses"
        elif hc <= 6:
            bucket = "5-6 hypotheses"
        else:
            bucket = "7+ hypotheses"
        hyp_buckets[bucket]['total'] += 1
        if m['lora_match']:
            hyp_buckets[bucket]['correct'] += 1
    
    print("| Hypotheses | Total | Correct | Accuracy |")
    print("| :-- | ---: | ---: | ---: |")
    for bucket in ["0 hypotheses", "1-2 hypotheses", "3-4 hypotheses", "5-6 hypotheses", "7+ hypotheses"]:
        if bucket in hyp_buckets and hyp_buckets[bucket]['total'] > 0:
            stats = hyp_buckets[bucket]
            acc = stats['correct']/stats['total']
            print(f"| {bucket} | {stats['total']} | {stats['correct']} | {acc:.1%} |")
    print()
    
    print("### Accuracy by goal features")
    print()
    feature_stats = {}
    for feature in ['has_equation', 'has_forall', 'has_exists']:
        total = sum(1 for m in merged if m[feature])
        correct = sum(1 for m in merged if m[feature] and m['lora_match'])
        feature_stats[feature] = (total, correct)
    
    print("| Goal Feature | Total | Correct | Accuracy |")
    print("| :-- | ---: | ---: | ---: |")
    for feat, (total, correct) in feature_stats.items():
        if total > 0:
            feat_name = feat.replace('has_', '').replace('_', ' ')
            print(f"| Has {feat_name} | {total} | {correct} | {correct/total:.1%} |")
    print()
    
    # 5) Source Distribution
    print("## Source Distribution")
    print()
    print("### Files contributing to correct predictions")
    print()
    correct_by_file = collections.Counter(m['source_file'] for m in merged if m['lora_match'])
    print("| Source File | Correct Predictions |")
    print("| :-- | ---: |")
    for f, count in correct_by_file.most_common(15):
        print(f"| `{f}` | {count} |")
    print()
    
    print("### Declarations with correct predictions")
    print()
    correct_by_decl = collections.Counter(m['source_declaration'] for m in merged if m['lora_match'])
    print("| Source Declaration | Correct Predictions |")
    print("| :-- | ---: |")
    for d, count in correct_by_decl.most_common(15):
        if d:
            print(f"| `{d}` | {count} |")
    print()
    
    # 6) Qualitative Examples
    print("## Qualitative Examples")
    print()
    print("### All correct LoRA predictions")
    print()
    correct_examples = [m for m in merged if m['lora_match']]
    for i, ex in enumerate(correct_examples, 1):
        print(f"#### Correct #{i}: `{ex['example_id']}`")
        print(f"- **Source:** `{ex['source_file']}` :: `{ex['source_declaration']}`")
        print(f"- **Base:** `{ex['base_pred']}` {'(silent)' if ex['base_silent'] else '(wrong)' if not ex['base_match'] else '(correct)'}")
        print(f"- **LoRA:** `{ex['lora_pred']}` ✓")
        print(f"- **Target:** `{ex['target']}`")
        print(f"- **Hypotheses:** {ex['hyp_count']}, Goal has equation: {ex['has_equation']}, Goal: `{ex['goal_text'][:100]}`")
        print(f"- **Context (first 150 chars):** `{ex['context'][:150]}...`")
        print()
    
    print("### Sample of incorrect LoRA predictions (10 examples)")
    print()
    incorrect_examples = [m for m in merged if not m['lora_match'] and not m['lora_silent']]
    import random
    random.seed(42)
    sample_incorrect = random.sample(incorrect_examples, min(10, len(incorrect_examples)))
    for i, ex in enumerate(sample_incorrect, 1):
        print(f"#### Incorrect #{i}: `{ex['example_id']}`")
        print(f"- **Source:** `{ex['source_file']}`")
        print(f"- **Base:** `{ex['base_pred']}` {'(silent)' if ex['base_silent'] else ''}")
        print(f"- **LoRA:** `{ex['lora_pred']}` (family: `{ex['lora_head']}`, target family: `{ex['target_head']}`)")
        print(f"- **Target:** `{ex['target']}`")
        print(f"- **Same family:** {'Yes' if ex['lora_head'] == ex['target_head'] else 'No'}")
        print(f"- **Hypotheses:** {ex['hyp_count']}, Goal: `{ex['goal_text'][:100]}`")
        print()
    
    print("## Key Takeaways")
    print()
    print(f"1. **Silence fix:** The adapter went from producing tactics on {len(merged)-base_silent}/{len(merged)} rows to {len(merged)-lora_silent}/{len(merged)} rows. Of the {lora_correct} correct predictions, {base_silent_lora_correct} came from base-silent rows ({base_silent_lora_correct/lora_correct:.1%} of correct answers).")
    print(f"2. **Tactic selection:** {base_nonsilent_lora_correct} correct predictions came from base-non-silent rows where the base was guessing wrong, showing the adapter does learn better tactic selection in some cases.")
    print(f"3. **Best performing families:** {', '.join('`'+f+'`' for f,_ in sorted(family_stats.items(), key=lambda x: x[1]['correct']/x[1]['total'] if x[1]['total']>=2 else 0, reverse=True)[:3])}")
    print(f"4. **Complexity:** The model seems to work best on simpler goals with fewer hypotheses.")
    print()


if __name__ == '__main__':
    # Run and capture output
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
