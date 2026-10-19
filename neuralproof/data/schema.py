from dataclasses import asdict,dataclass
import json
@dataclass(frozen=True)
class Example:
    theorem_id:str; theorem:str; context:str; goal_state:str; target_tactic:str; source_file:str; split:str="train"
    def jsonl(self): return json.dumps(asdict(self),ensure_ascii=False)
