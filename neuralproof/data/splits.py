"""Deterministic file-level split assignment to limit theorem leakage."""
import hashlib
def split_for(source_file,seed="neuralproof-v1"):
    x=int(hashlib.sha256((seed+source_file).encode()).hexdigest()[:8],16)%100
    return "train" if x<80 else "validation" if x<90 else "test"
