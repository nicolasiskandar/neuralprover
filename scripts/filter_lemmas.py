#!/usr/bin/env python3
"""Filter tactic predictions to only use valid lemmas."""

import json
import re
from pathlib import Path

LEMMA_INDEX_PATH = Path("data/lemma_index.json")


def load_lemma_index():
    with open(LEMMA_INDEX_PATH) as f:
        lemmas = json.load(f)
    return set(lemmas)


def extract_lemmas_from_tactic(tactic: str):
    """Extract lemma names from tactic strings."""
    if not tactic or not tactic.strip():
        return []
    
    lemmas = []
    tactic = tactic.strip()
    
    # Pattern 1: rw [lemma1, lemma2, ← lemma3]
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
            # Extract the base lemma name
            # Could be namespaced like Module.lemma or just lemma
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', part):
                # Get the last component for checking
                lemmas.append(part)
    
    # Pattern 2: apply/exact/refine lemma_name
    for tactic_name in ['apply', 'exact', 'refine']:
        pattern = rf'\b{tactic_name}\b\s+(@?[a-zA-Z_][a-zA-Z0-9_.]+)'
        for match in re.finditer(pattern, tactic):
            lemmas.append(match.group(1).lstrip('@'))
    
    # Pattern 3: simp [lemma1, lemma2]
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
    
    # Pattern 4: simpa using/by lemma
    simpa_pattern = r'\bsimpa\b.*?(?:using|by)\s+([a-zA-Z_][a-zA-Z0-9_.]+)'
    for match in re.finditer(simpa_pattern, tactic):
        lemmas.append(match.group(1))
    
    # Deduplicate
    seen = set()
    unique_lemmas = []
    for l in lemmas:
        if l not in seen:
            seen.add(l)
            unique_lemmas.append(l)
    
    return unique_lemmas


def is_valid_lemma(lemma, lemma_index):
    """Check if a lemma exists in the index."""
    # Check full name
    if lemma in lemma_index:
        return True
    # Check just the base name (last component)
    base = lemma.split('.')[-1]
    if base in lemma_index:
        return True
    return False


def filter_tactic(tactic, lemma_index):
    """Check if tactic uses only valid lemmas. Returns (valid, reason)."""
    lemmas = extract_lemmas_from_tactic(tactic)
    if not lemmas:
        return True, "no lemmas"
    
    for lem in lemmas:
        if not is_valid_lemma(lem, lemma_index):
            return False, f"invalid lemma: {lem}"
    
    return True, "all valid"


if __name__ == '__main__':
    idx = load_lemma_index()
    print(f"Loaded {len(idx)} lemmas")
    
    # Test
    test_cases = [
        "rw [List.map_smul_eq]",
        "rw [add_comm]",
        "simp only [List.sum]",
        "apply fun_injective",
        "rfl",
        "simp",
    ]
    for t in test_cases:
        valid, reason = filter_tactic(t, idx)
        print(f"{valid}: {t} - {reason}")
