#!/usr/bin/env python3
"""Command-line wrapper for the installable NeuralProof corpus extractor."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuralproof.data.corpus import main


if __name__ == "__main__":
    main()
