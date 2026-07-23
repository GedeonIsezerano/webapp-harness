#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
from common import read_json

def collect(root:Path) -> Path:
    h=root/'.harness'; state=read_json(h/'state.json'); rid=state.get('active_run_id')
    if not rid: raise ValueError('No active run')
    run=read_json(h/'runs'/rid/'run.json'); base=run.get('base_commit') or 'HEAD'
    p=subprocess.run(['git','diff','--find-renames',base],cwd=root,text=True,capture_output=True)
    if p.returncode: raise ValueError(p.stderr.strip())
    u=subprocess.run(['git','ls-files','--others','--exclude-standard'],cwd=root,text=True,capture_output=True)
    out=h/'runs'/rid/'task.diff'; out.write_text(p.stdout+'\n# Untracked files\n'+u.stdout,encoding='utf-8'); return out

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',default='.'); a=p.parse_args()
    try: print(collect(Path(a.root)))
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
if __name__=='__main__': main()
