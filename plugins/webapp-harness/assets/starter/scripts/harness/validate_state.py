#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from jsonschema import Draft202012Validator
from common import read_json, task_map, active_tasks, completion_ids
from lifecycle import ALLOWED_TRANSITIONS

REQUIRED=['config.json','backlog.json','completed-tasks.json','state.json']
SCHEMAS={'config.json':'config.schema.json','backlog.json':'backlog.schema.json','completed-tasks.json':'completion-index.schema.json','state.json':'state.schema.json'}

def validate(root: Path) -> list[str]:
    h=root/'.harness'; errors=[]; docs={}
    for name in REQUIRED:
        try: docs[name]=read_json(h/name)
        except ValueError as e: errors.append(str(e))
    if errors: return errors
    for name,schema_name in SCHEMAS.items():
        try:
            schema=read_json(h/'schema'/schema_name)
            for err in Draft202012Validator(schema).iter_errors(docs[name]):
                loc='/'.join(map(str,err.absolute_path)) or '<root>'
                errors.append(f'{name}:{loc}: {err.message}')
        except ValueError as e: errors.append(str(e))
    backlog=docs['backlog.json']; completion_index=docs['completed-tasks.json']; state=docs['state.json']; tasks=backlog.get('tasks',[])
    try:
        task_schema=read_json(h/'schema'/'task.schema.json')
        for idx, task in enumerate(tasks):
            for err in Draft202012Validator(task_schema).iter_errors(task):
                loc='/'.join(map(str,err.absolute_path)) or '<root>'
                errors.append(f'backlog.json:tasks/{idx}/{loc}: {err.message}')
    except ValueError as e: errors.append(str(e))
    ids=[t.get('id') for t in tasks]
    if len(ids)!=len(set(ids)): errors.append('backlog.json: task IDs must be unique')
    completed_ids=completion_ids(completion_index)
    if len(completed_ids) != len(completion_index.get('completed_tasks', [])):
        errors.append('completed-tasks.json: task IDs must be unique')
    overlap=sorted(set(ids).intersection(completed_ids))
    if overlap:
        errors.append('backlog.json and completed-tasks.json repeat task IDs: '+', '.join(overlap))
    known=set(ids).union(completed_ids)
    for t in tasks:
        for dep in t.get('dependencies',[]):
            if dep not in known: errors.append(f"{t.get('id')}: unknown dependency {dep}")
        if t.get('status')=='ready' and not t.get('acceptance_criteria'):
            errors.append(f"{t.get('id')}: ready task has no acceptance criteria")
    graph={t['id']:t.get('dependencies',[]) for t in tasks if 'id' in t}; visiting=set(); visited=set()
    def visit(n,trail):
        if n in visiting:
            errors.append('dependency cycle: '+' -> '.join(trail+[n])); return
        if n in visited:return
        visiting.add(n)
        for d in graph.get(n,[]): visit(d,trail+[n])
        visiting.remove(n); visited.add(n)
    for n in graph: visit(n,[])
    active=active_tasks(backlog)
    if len(active)>1: errors.append('more than one active task')
    active_id=state.get('active_task_id')
    if active_id != (active[0]['id'] if active else None): errors.append('state.active_task_id disagrees with backlog')
    run_id=state.get('active_run_id')
    if run_id:
        try:
            run=read_json(h/'runs'/run_id/'run.json')
        except ValueError:
            errors.append('active run record is missing or invalid')
        else:
            run_task_id=run.get('task_id')
            if run_task_id not in known: errors.append('active run references an unknown task')
            else:
                run_task=tasks[ids.index(run_task_id)]
                if run.get('status')!=run_task.get('status'): errors.append('active run status disagrees with backlog')
    for tr in state.get('transition_history',[]):
        if tr.get('to') not in ALLOWED_TRANSITIONS.get(tr.get('from'),set()):
            errors.append(f"illegal transition history entry: {tr.get('from')} -> {tr.get('to')}")
    return errors

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',default='.'); p.add_argument('--json',action='store_true'); a=p.parse_args()
    errors=validate(Path(a.root))
    if a.json: print(json.dumps({'valid':not errors,'errors':errors},indent=2))
    elif errors:
        for e in errors: print(f'ERROR: {e}',file=sys.stderr)
    else: print('Harness state is valid.')
    raise SystemExit(1 if errors else 0)
if __name__=='__main__': main()
