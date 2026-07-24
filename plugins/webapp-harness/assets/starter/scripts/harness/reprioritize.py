#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from common import read_json, atomic_write_json, task_map, utc_now
from validate_state import validate

def reprioritize(root: Path, ordered_ids: list[str]) -> dict:
    errors=validate(root)
    if errors: raise ValueError('Harness state invalid:\n'+'\n'.join(errors))
    h=root/'.harness'; backlog=read_json(h/'backlog.json'); tasks=task_map(backlog)
    if not ordered_ids: raise ValueError('Provide at least one task ID')
    if len(set(ordered_ids))!=len(ordered_ids): raise ValueError('Duplicate task IDs in order')
    unknown=[i for i in ordered_ids if i not in tasks]
    if unknown: raise ValueError('Unknown task IDs: '+', '.join(unknown))
    for priority, task_id in enumerate(ordered_ids, start=1):
        tasks[task_id]['priority']=priority
        tasks[task_id]['updated_at']=utc_now()
    atomic_write_json(h/'backlog.json',backlog)
    errors=validate(root)
    if errors: raise ValueError('Harness state invalid after reprioritize:\n'+'\n'.join(errors))
    return {task_id: tasks[task_id]['priority'] for task_id in ordered_ids}

def main():
    p=argparse.ArgumentParser(description='Assign priorities 1..N to task IDs in the given order. Lower values run first; 1 is the highest priority.')
    p.add_argument('task_ids',nargs='+'); p.add_argument('--root',default='.'); a=p.parse_args()
    try: print(json.dumps(reprioritize(Path(a.root),a.task_ids),indent=2))
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
if __name__=='__main__': main()
