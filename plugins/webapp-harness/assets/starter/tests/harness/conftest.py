import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[2]/'scripts/harness'))
def write_json(path,data): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,indent=2)+'\n')
