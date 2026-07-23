#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
from common import read_json

def git(root,*args):
    p=subprocess.run(['git',*args],cwd=root,text=True,capture_output=True)
    if p.returncode: raise ValueError(p.stderr.strip() or 'git command failed')
    return p.stdout

def check(root:Path,mode:str):
    git(root,'rev-parse','--is-inside-work-tree')
    gd=Path(git(root,'rev-parse','--git-dir').strip()); gd=gd if gd.is_absolute() else root/gd
    for marker in ['MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply']:
        if (gd/marker).exists(): raise ValueError(f'Git operation in progress: {marker}')
    status=git(root,'status','--porcelain=v1').splitlines(); cfg=read_json(root/'.harness/config.json')
    allowed=tuple(cfg.get('repository',{}).get('allowed_dirty_paths',[]))
    unexpected=[]
    for line in status:
        path=line[3:]
        if ' -> ' in path: path=path.split(' -> ',1)[1]
        if not path.startswith(allowed): unexpected.append(line)
    if unexpected: raise ValueError('Unexpected repository changes:\n'+'\n'.join(unexpected))

def main():
    p=argparse.ArgumentParser(); g=p.add_mutually_exclusive_group(required=True); g.add_argument('--before-task',action='store_true'); g.add_argument('--before-next-task',action='store_true'); p.add_argument('--root',default='.'); a=p.parse_args()
    try: check(Path(a.root),'before-task' if a.before_task else 'before-next-task')
    except ValueError as e: print(f'ERROR: {e}',file=sys.stderr); raise SystemExit(1)
    print('Repository state is acceptable.')
if __name__=='__main__': main()
