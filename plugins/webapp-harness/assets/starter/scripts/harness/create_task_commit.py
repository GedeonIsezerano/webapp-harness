#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
from common import read_json, atomic_write_json, task_map, utc_now

def run(root,*args):
    p=subprocess.run(['git',*args],cwd=root,text=True,capture_output=True)
    if p.returncode: raise ValueError(p.stderr.strip() or p.stdout.strip())
    return p.stdout.strip()
def changed_paths(root:Path) -> set[str]:
    tracked=run(root,'diff','--name-only','HEAD').splitlines()
    staged=run(root,'diff','--cached','--name-only','HEAD').splitlines()
    untracked=run(root,'ls-files','--others','--exclude-standard').splitlines()
    return {path for path in tracked+staged+untracked if path}
def within(path:str,prefix:str) -> bool:
    normalized=prefix.rstrip('/')
    return path==normalized or path.startswith(normalized+'/')
def assert_task_scope(root:Path,task:dict) -> None:
    scope=task.get('scope',{}); allowed=scope.get('allowed_paths',[]); forbidden=scope.get('forbidden_paths',[])
    runtime_paths=['.harness/backlog.json','.harness/state.json','.harness/current-task.json','.harness/runs/']
    violations=[]
    for path in sorted(changed_paths(root)):
        if any(within(path,prefix) for prefix in runtime_paths): continue
        if any(within(path,prefix) for prefix in forbidden):
            violations.append(f'{path} is forbidden'); continue
        if not any(within(path,prefix) for prefix in allowed):
            violations.append(f'{path} is outside allowed paths')
    if violations: raise ValueError('Task scope violation:\n'+'\n'.join(violations))
def create(root:Path):
    h=root/'.harness'; state=read_json(h/'state.json'); rid=state.get('active_run_id'); tid=state.get('last_completed_task_id')
    if not rid or not tid: raise ValueError('A completed task and active run are required')
    backlog=read_json(h/'backlog.json'); task=task_map(backlog)[tid]; run_data=read_json(h/'runs'/rid/'run.json')
    if task['status']!='completed': raise ValueError('Task is not completed')
    assert_task_scope(root,task); run(root,'diff','--check')
    criteria=', '.join(c['id'] for c in task['acceptance_criteria'])
    subject=f"{tid}: {task['title']}"[:72]
    body=f"Task: {tid}\nRun: {rid}\nAcceptance-Criteria: {criteria}\nVerification: passed\nBrowser-Validation: {run_data.get('browser_validation',{}).get('status','not-required').lower()}\nReview: approved"
    run_data['status']='completed'; run_data['stop_reason']='completed'
    state['active_run_id']=None; state['updated_at']=utc_now()
    atomic_write_json(h/'runs'/rid/'run.json',run_data); atomic_write_json(h/'state.json',state)
    run(root,'add','-A'); run(root,'commit','-m',subject,'-m',body); sha=run(root,'rev-parse','HEAD')
    run_data['result_commit']=sha; run_data['committed_at']=utc_now(); atomic_write_json(h/'runs'/rid/'run.json',run_data)
    state['last_completed_commit']=sha; state['updated_at']=utc_now(); atomic_write_json(h/'state.json',state)
    return sha

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',default='.'); a=p.parse_args()
    try: print(create(Path(a.root)))
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
if __name__=='__main__': main()
