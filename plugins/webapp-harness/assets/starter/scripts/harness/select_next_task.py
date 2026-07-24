#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from common import read_json, atomic_write_json, task_map, utc_now, priority_sort_key
from validate_state import validate
from update_task_state import transition

def select(root: Path, task_id: str | None = None) -> dict:
    errors=validate(root)
    if errors: raise ValueError('Harness state invalid:\n'+'\n'.join(errors))
    h=root/'.harness'; backlog=read_json(h/'backlog.json'); state=read_json(h/'state.json')
    if state.get('active_task_id'): raise ValueError(f"Task already active: {state['active_task_id']}")
    tasks=task_map(backlog)
    eligible=[t for t in tasks.values() if t['status']=='ready' and all(tasks[d]['status']=='completed' for d in t.get('dependencies',[]))]
    if not eligible: raise ValueError('No eligible ready task')
    if task_id:
        if task_id not in tasks: raise ValueError(f'Unknown task: {task_id}')
        chosen=tasks[task_id]
        if chosen not in eligible:
            raise ValueError(f'Task is not eligible and ready: {task_id}')
    else:
        chosen=sorted(eligible,key=priority_sort_key)[0]
    run_id=f"{chosen['id']}-{utc_now().replace(':','').replace('-','')}"
    run_dir=h/'runs'/run_id; run_dir.mkdir(parents=True,exist_ok=False)
    run={'schema_version':1,'run_id':run_id,'task_id':chosen['id'],'attempt':1,'status':'implementing','started_at':utc_now(),'base_commit':None,'transitions':[],'implementation':{},'verification':{},'browser_validation':{},'review':{},'result_commit':None,'stop_reason':None}
    atomic_write_json(run_dir/'run.json',run)
    state['active_run_id']=run_id; atomic_write_json(h/'state.json',state)
    transition(root,chosen['id'],'implementing','task_selected')
    atomic_write_json(h/'current-task.json',{'task_id':chosen['id'],'run_id':run_id})
    return {'task_id':chosen['id'],'run_id':run_id,'title':chosen['title']}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',default='.'); p.add_argument('--task-id'); a=p.parse_args()
    try: print(json.dumps(select(Path(a.root),a.task_id),indent=2))
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
if __name__=='__main__': main()
