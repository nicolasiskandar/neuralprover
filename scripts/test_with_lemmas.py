#!/usr/bin/env python3
from neuralproof.models.predictor import load_hf_predictor
from neuralproof.lean.client import ProofState
import json

# Load lemma index
with open('data/lemma_index.json') as f:
    lemma_index = set(json.load(f))

predictor = load_hf_predictor(
    "HuggingFaceTB/SmolLM2-135M",
    adapter="experiments/mathlib-info-tree-lora-200-1epoch-canonical",
    revision="4e53f736cbb20a9a0f56b4c4bf378d9f306ff915"
)

# Test with lemma hints in context
ctx = "import Mathlib.Tactic\n\n-- Relevant lemmas: add_comm, mul_comm, fun_injective, Injective.comp\n"
state = ProofState(theorem="example", context=ctx, goals=("f g : α → β\nh : Function.Injective (g ∘ f)\n⊢ Function.Injective f",))
cands = predictor.predict(state, 5)
for c in cands:
    print(repr(c.tactic))
