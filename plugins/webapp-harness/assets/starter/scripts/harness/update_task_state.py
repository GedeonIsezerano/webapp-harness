#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys
from pathlib import Path
from common import read_json, atomic_write_json, task_map, utc_now
from lifecycle import can_transition, ACTIVE_STATES

def transition(root: Path, task_id: str, target: str, reason: str) -> None:
    h=root/'.harness'; backlog=read_json(h/'backlog.json'); state=read_json(h/'state.json'); tasks=task_map(backlog)
    if task_id not in tasks: raise ValueError(f'Unknown task: {task_id}')
    task=tasks[task_id]; source=task['status']
    if not can_transition(source,target): raise ValueError(f'Illegal transition: {source} -> {target}')
    if target=='reviewing' and task.get('verification',{}).get('requires_browser'):
        run_id=state.get('active_run_id')
        if not run_id: raise ValueError('Cannot enter review without active run')
        if read_json(h/'runs'/run_id/'run.json').get('browser_validation',{}).get('status')!='PASSED':
            raise ValueError('Cannot enter review without passed browser validation')
    if target=='completed':
        run_id=state.get('active_run_id')
        if not run_id: raise ValueError('Cannot complete without active run')
        run=read_json(h/'runs'/run_id/'run.json')
        if run.get('verification',{}).get('status')!='PASSED': raise ValueError('Cannot complete without passed verification')
        if task.get('verification',{}).get('requires_browser') and run.get('browser_validation',{}).get('status')!='PASSED': raise ValueError('Cannot complete without passed browser validation')
        if run.get('review',{}).get('verdict')!='APPROVED': raise ValueError('Cannot complete without approved review')
    task['status']=target; task['updated_at']=utc_now()
    entry={'task_id':task_id,'from':source,'to':target,'reason':reason,'timestamp':utc_now()}
    state.setdefault('transition_history',[]).append(entry)
    run_id=state.get('active_run_id')
    if run_id:
        run_path=h/'runs'/run_id/'run.json'; run=read_json(run_path)
        if run.get('task_id')!=task_id: raise ValueError('Active run belongs to another task')
        run['status']=target
        run.setdefault('transitions',[]).append(entry)
        if target=='completed': run['completed_at']=entry['timestamp']
        atomic_write_json(run_path,run)
    state['active_task_id']=task_id if target in ACTIVE_STATES else None
    if target=='completed': state['last_completed_task_id']=task_id
    state['updated_at']=utc_now()
    atomic_write_json(h/'backlog.json',backlog); atomic_write_json(h/'state.json',state)

def main():
    p=argparse.ArgumentParser(); p.add_argument('task_id'); p.add_argument('target'); p.add_argument('--reason',required=True); p.add_argument('--root',default='.'); a=p.parse_args()
    try: transition(Path(a.root),a.task_id,a.target,a.reason)
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
    print(f'{a.task_id} transitioned to {a.target}.')
if __name__=='__main__': main()
