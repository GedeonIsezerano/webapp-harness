#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys
from pathlib import Path
from jsonschema import Draft202012Validator
from common import read_json, atomic_write_json

def record(root:Path,kind:str,input_path:Path):
    h=root/'.harness'; state=read_json(h/'state.json'); rid=state.get('active_run_id')
    if not rid: raise ValueError('No active run')
    data=read_json(input_path); schema=read_json(h/'schema'/f'{kind}.schema.json')
    errs=list(Draft202012Validator(schema).iter_errors(data))
    if errs: raise ValueError('; '.join(e.message for e in errs))
    run_path=h/'runs'/rid/'run.json'; run=read_json(run_path)
    if data.get('task_id')!=run['task_id'] or data.get('run_id')!=rid: raise ValueError('Result does not belong to active task/run')
    if kind=='review' and data['verdict']=='APPROVED' and any(f['severity']=='blocking' for f in data.get('findings',[])): raise ValueError('APPROVED review cannot contain blocking findings')
    key={'verification':'verification','browser-result':'browser_validation','review':'review','implementation-result':'implementation'}[kind]
    run[key]=data; atomic_write_json(run_path,run); atomic_write_json(h/'runs'/rid/f'{kind}.json',data)

def main():
    p=argparse.ArgumentParser(); p.add_argument('kind',choices=['verification','browser-result','review','implementation-result']); p.add_argument('input'); p.add_argument('--root',default='.'); a=p.parse_args()
    try: record(Path(a.root),a.kind,Path(a.input))
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
    print(f'Recorded {a.kind}.')
if __name__=='__main__': main()
