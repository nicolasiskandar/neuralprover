from neuralproof.lean.client import ProofState,TacticCandidate
from neuralproof.models.prompt import format_tactic_prompt

class StaticPredictor:
    def __init__(self,tactics): self.tactics=list(tactics)
    def predict(self,state:ProofState,k:int): return [TacticCandidate(t,1-i*.01) for i,t in enumerate(self.tactics[:k])]

def load_hf_predictor(model_id,adapter=None,revision=None):
    try:
        from transformers import AutoTokenizer,AutoModelForCausalLM
        import torch
    except ImportError as e: raise RuntimeError("Install neuralproof[train] for model inference") from e
    tok=AutoTokenizer.from_pretrained(model_id,revision=revision); model=AutoModelForCausalLM.from_pretrained(model_id,revision=revision)
    if adapter:
        from peft import PeftModel
        model=PeftModel.from_pretrained(model,adapter)
    model.eval()
    class HF:
        def predict(self,state,k):
            prompt=format_tactic_prompt(state.context,state.goal_state); ids=tok(prompt,return_tensors="pt")
            with torch.no_grad(): out=model.generate(**ids,max_new_tokens=64,num_return_sequences=k,do_sample=k>1,temperature=.8,pad_token_id=tok.eos_token_id)
            return [TacticCandidate(tok.decode(s[ids.input_ids.shape[1]:],skip_special_tokens=True).splitlines()[0].strip()) for s in out]
    return HF()
