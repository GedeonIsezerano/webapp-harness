#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, time, sys
from pathlib import Path
from common import read_json, atomic_write_json

def verify(root: Path) -> dict:
    h=root/'.harness'; state=read_json(h/'state.json'); rid=state.get('active_run_id')
    if not rid: raise ValueError('No active run')
    run=read_json(h/'runs'/rid/'run.json'); backlog=read_json(h/'backlog.json')
    task=next((t for t in backlog['tasks'] if t['id']==run['task_id']),None)
    if not task: raise ValueError('Active task not found')
    cfg=read_json(h/'config.json'); checks=[]; failed=False
    for profile in task.get('verification',{}).get('profiles',[]):
        for spec in cfg.get('verification_profiles',{}).get(profile,[]):
            command=spec['command']; start=time.monotonic()
            p=subprocess.run(command,cwd=root,text=True,capture_output=True)
            checks.append({'name':spec.get('name',' '.join(command)),'command':command,'exit_code':p.returncode,'duration_seconds':round(time.monotonic()-start,3),'stdout_summary':p.stdout[-4000:],'stderr_summary':p.stderr[-4000:]})
            failed |= p.returncode != 0
    status='INCOMPLETE' if not checks else ('FAILED' if failed else 'PASSED')
    result={'task_id':task['id'],'run_id':rid,'status':status,'checks':checks}
    atomic_write_json(h/'runs'/rid/'verification.json',result); run['verification']=result; atomic_write_json(h/'runs'/rid/'run.json',run)
    return result

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',default='.'); a=p.parse_args()
    try: result=verify(Path(a.root))
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
    print(result['status']); raise SystemExit(0 if result['status']=='PASSED' else 1)
if __name__=='__main__': main()
