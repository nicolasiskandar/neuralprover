# Reproducibility

Lean is pinned at `leanprover/lean4:v4.35.0`. Mathlib is pinned at commit `56a005855ea17e0b0958f73ec801ae140b0a1679`; `lean/lake-manifest.json` locks its transitive dependencies. Set up with `cd lean && lake update && lake build`. Python runtime code currently uses the standard library. Optional training dependencies are version pinned in `pyproject.toml`; installation/model download requires network or a prepopulated cache. For CPU-only training, use the official PyTorch CPU wheel index and explicitly select `torch==2.6.0+cpu` as shown in the README.

Record command, git revision, Lean version, Python version, model ID and immutable revision, dataset hash, random seed, inference settings, search limits, and hardware in each experiment directory. Do not use the smoke sample to make performance claims. Current test invocation: `python3 -m unittest discover -s tests -v`.

The current clean one-row Mathlib pilot JSONL SHA-256 is `7339b56e1477f54367f964cb31d54f1f72f50cb7db081eb1e7820dc4f31800bd`; the Lake manifest SHA-256 is `4edf9b1976ae48624f000401516854e32bab61d2071a9dd3784740f1737ed776`. The 200-file clean corpus selection hash is in `data/mathlib-200/manifest.json`; the rows, per-file stats, and prompt-formatted split files should be archived together. A CPU smoke run used Python 3.11.17, PyTorch 2.6.0+cpu, Transformers 4.49.0, PEFT 0.14.0, seed 17, and the immutable SmolLM2-135M revision `4e53f736cbb20a9a0f56b4c4bf378d9f306ff915`. An earlier five-row pilot training run is superseded because its `import Mathlib` context may have exposed target declarations; see the experiment log for the clean corpus training run and its limitations. Historical trainer artifacts remain under `experiments/smol-lora-smoke/`. The model weights are cached outside the repository at `/tmp/neuralproof-hf-cache` in this environment.

The native InfoTree extraction smoke command is:

```bash
python -m neuralproof.cli data trace \
  --file lean/.lake/packages/mathlib/Mathlib/Algebra/AddConstMap/Basic.lean \
  --output data/traces/addconstmap-basic.json
```

It records raw overlapping InfoTree nodes, not normalized tactic trajectories. The staged replay corpus is resumable with `python -m neuralproof.cli data corpus --files 200 --per-file 5 --output data/mathlib-200`; its `manifest.json` pins the selection by hash and `summary.json` reports actual completed counts. Keep `examples.jsonl`, `file_stats.jsonl`, and the manifest together when archiving a corpus run.

To extract and preprocess native Mathlib InfoTree states, run
`python -m neuralproof.cli data trace-corpus --files 200 --output data/mathlib-info-tree-200`, then `python -m neuralproof.cli preprocess --input data/mathlib-info-tree-200/examples.jsonl --output data/mathlib-info-tree-200/processed`. These normalized examples are observed during whole-file Lean elaboration, but their reconstructed per-example contexts have not been independently replayed.

Bound a CPU LoRA experiment with `--max-steps` to avoid an impractical full-split run. The held-out tactic metric command is:

```bash
neuralproof evaluate-tactics \
  --data data/mathlib-info-tree-200/examples.jsonl \
  --adapter experiments/mathlib-info-tree-lora-200-100steps \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --limit 50 --seed neuralproof-mathlib-info-tree-v1 \
  --output experiments/mathlib-info-tree-lora-200-100steps/tactic-eval-50.json
```
