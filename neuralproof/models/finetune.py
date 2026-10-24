"""Optional PEFT LoRA SFT trainer for JSONL `{prompt, target_tactic}` records."""
import argparse,json
from pathlib import Path


def resolve_max_steps(max_steps: int) -> int:
    """Map a step budget onto the value `TrainingArguments` expects.

    `TrainingArguments` reads any `max_steps >= 0` as a hard limit and stops
    the loop as soon as `global_step >= max_steps`.  A budget of `0` therefore
    ends the run after its first step, and `-1` is the value that lets the
    epoch count decide how long the run is.  The caller-facing budget is
    checked here so a silently truncated run cannot be requested again.
    """
    if max_steps == 0:
        raise ValueError("max_steps must be positive or -1 for an unbounded run; "
                         "0 would stop the run after its first step")
    if max_steps < -1:
        raise ValueError("max_steps cannot be less than -1")
    return max_steps


def select_training_rows(rows, goal_scope="proof"):
    """Split the rows into the ones to train on and the ones to drop.

    A focus-local state is not the state the live client reports, so a model
    trained on it is trained on inputs that never occur at inference.  Rows
    without a scope marker come from the narrow extractor, which records
    proof-global states, and are kept.  An empty `goal_scope` keeps every row.
    """
    if not goal_scope:
        return list(rows), 0
    kept=[r for r in rows if r.get("goal_scope",goal_scope)==goal_scope]
    return kept,len(rows)-len(kept)


def train(data,model_id,output,revision=None,epochs=1,seed=17,resume=None,max_steps=-1,goal_scope="proof"):
    max_steps=resolve_max_steps(max_steps)
    try:
        import torch
        from transformers import AutoModelForCausalLM,AutoTokenizer,TrainingArguments,Trainer
        from peft import LoraConfig,TaskType,get_peft_model
    except ImportError as e: raise RuntimeError("Install neuralproof[train] to train a LoRA adapter") from e
    from transformers import set_seed
    from neuralproof.models.prompt import format_tactic_prompt
    set_seed(seed)
    tok=AutoTokenizer.from_pretrained(model_id,revision=revision); tok.pad_token=tok.eos_token
    model=AutoModelForCausalLM.from_pretrained(model_id,revision=revision)
    model=get_peft_model(model,LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,target_modules=["q_proj","v_proj"],task_type=TaskType.CAUSAL_LM))
    rows=[json.loads(x) for x in Path(data).read_text().splitlines() if x.strip()]
    rows,dropped=select_training_rows(rows,goal_scope)
    class DS(torch.utils.data.Dataset):
        def __len__(self): return len(rows)
        def __getitem__(self,i):
            x=rows[i]
            prompt=format_tactic_prompt(x.get("context", ""),x.get("goal_state", ""))
            prefix=tok(prompt,add_special_tokens=True,truncation=True,max_length=1024).input_ids
            target=tok(x["target_tactic"].strip()+tok.eos_token,add_special_tokens=False).input_ids
            target=target[:1023]; prefix=prefix[:max(1,1024-len(target))]
            ids=prefix+target
            return {"input_ids":ids,"attention_mask":[1]*len(ids),"labels":[-100]*len(prefix)+target}
    def collate(items):
        width=max(len(x["input_ids"]) for x in items); batch={"input_ids":[],"attention_mask":[],"labels":[]}
        for x in items:
            n=width-len(x["input_ids"])
            batch["input_ids"].append(x["input_ids"]+[tok.pad_token_id]*n)
            batch["attention_mask"].append(x["attention_mask"]+[0]*n)
            batch["labels"].append(x["labels"]+[-100]*n)
        return {k:torch.tensor(v,dtype=torch.long) for k,v in batch.items()}
    args=TrainingArguments(output_dir=output,num_train_epochs=epochs,max_steps=max_steps,
        per_device_train_batch_size=1,learning_rate=2e-4,logging_steps=5,
        save_strategy="steps" if max_steps > 0 else "epoch",
        save_steps=max_steps if max_steps > 0 else 500,
        report_to=[],seed=seed,data_seed=seed)
    trainer=Trainer(model=model,args=args,train_dataset=DS(),data_collator=collate)
    trainer.train(resume_from_checkpoint=resume); model.save_pretrained(output); tok.save_pretrained(output)
    print(json.dumps({"trained_rows":len(rows),"dropped_rows":dropped,"goal_scope":goal_scope,
                      "output":output}))

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--data",required=True); p.add_argument("--model",default="HuggingFaceTB/SmolLM2-135M"); p.add_argument("--revision"); p.add_argument("--output",default="experiments/smol-lora"); p.add_argument("--epochs",type=int,default=1); p.add_argument("--seed",type=int,default=17); p.add_argument("--resume"); p.add_argument("--max-steps",type=int,default=-1,help="positive step budget, or -1 to train for the full number of epochs"); p.add_argument("--goal-scope",default="proof"); a=p.parse_args(); train(a.data,a.model,a.output,a.revision,a.epochs,a.seed,a.resume,a.max_steps,a.goal_scope)
