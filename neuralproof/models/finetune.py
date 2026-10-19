"""Optional PEFT LoRA SFT trainer for JSONL `{prompt, target_tactic}` records."""
import argparse,json
from pathlib import Path

def train(data,model_id,output,revision=None,epochs=1,seed=17,resume=None,max_steps=0):
    if max_steps < 0:
        raise ValueError("max_steps cannot be negative")
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
    class DS(torch.utils.data.Dataset):
        def __len__(self): return len(rows)
        def __getitem__(self,i):
            x=rows[i]
            prompt=format_tactic_prompt(x.get("context", ""),x.get("goal_state", ""))
            prefix=tok(prompt,add_special_tokens=True,truncation=True,max_length=1024).input_ids
            target=tok(x["target_tactic"]+tok.eos_token,add_special_tokens=False).input_ids
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
    trainer=Trainer(model=model,args=args,train_dataset=DS(),data_collator=collate); trainer.train(resume_from_checkpoint=resume); model.save_pretrained(output); tok.save_pretrained(output)

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--data",required=True); p.add_argument("--model",default="HuggingFaceTB/SmolLM2-135M"); p.add_argument("--revision"); p.add_argument("--output",default="experiments/smol-lora"); p.add_argument("--epochs",type=int,default=1); p.add_argument("--seed",type=int,default=17); p.add_argument("--resume"); a=p.parse_args(); train(a.data,a.model,a.output,a.revision,a.epochs,a.seed,a.resume)
