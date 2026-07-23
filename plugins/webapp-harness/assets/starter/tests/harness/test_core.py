import json, shutil, subprocess
from pathlib import Path
from lifecycle import can_transition
from validate_state import validate
from select_next_task import select
from update_task_state import transition
from verify_task import verify
from create_task_commit import assert_task_scope
from conftest import write_json

def fixture(tmp_path):
    shutil.copytree(Path(__file__).parents[2]/'.harness',tmp_path/'.harness'); return tmp_path

def task(i,status='ready',priority=1,deps=None):
    return {'id':i,'title':'Task '+i,'description':'A test task','status':status,'priority':priority,'dependencies':deps or [],'type':'backend','acceptance_criteria':[{'id':'AC-1','description':'Works','verification':['unit']}],'verification':{'profiles':[],'requires_browser':False,'requires_e2e':False},'scope':{'allowed_paths':['src/'],'forbidden_paths':[]}}

def test_lifecycle(): assert can_transition('ready','implementing') and not can_transition('ready','completed')
def test_deterministic_selection(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('Z-002',priority=10),task('A-001',priority=10),task('B-001',priority=5)]}); assert select(r)['task_id']=='A-001'
def test_dependency_blocks_selection(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001',deps=['B-001']),task('B-001')]}); assert select(r)['task_id']=='B-001'
def test_duplicate_ids_fail(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001'),task('A-001')]}); assert any('unique' in e for e in validate(r))
def test_cycle_fails(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001',deps=['B-001']),task('B-001',deps=['A-001'])]}); assert any('cycle' in e for e in validate(r))
def test_zero_check_verification_is_incomplete(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001')]}); select(r); assert verify(r)['status']=='INCOMPLETE'
def test_transition_updates_active_run(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001')]}); selected=select(r); transition(r,'A-001','verifying','implemented'); run=json.loads((r/'.harness/runs'/selected['run_id']/'run.json').read_text()); assert run['status']=='verifying' and run['transitions'][-1]['to']=='verifying'
def test_validate_rejects_run_status_mismatch(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001')]}); selected=select(r); run_path=r/'.harness/runs'/selected['run_id']/'run.json'; run=json.loads(run_path.read_text()); run['status']='reviewing'; write_json(run_path,run); assert any('run status' in error for error in validate(r))
def test_commit_scope_rejects_unrelated_paths(tmp_path):
    subprocess.run(['git','init','-b','main'],cwd=tmp_path,check=True,capture_output=True)
    subprocess.run(['git','config','user.email','harness@example.test'],cwd=tmp_path,check=True)
    subprocess.run(['git','config','user.name','Harness Test'],cwd=tmp_path,check=True)
    (tmp_path/'baseline.txt').write_text('baseline\n')
    subprocess.run(['git','add','baseline.txt'],cwd=tmp_path,check=True)
    subprocess.run(['git','commit','-m','baseline'],cwd=tmp_path,check=True,capture_output=True)
    scoped=task('A-001'); scoped['scope']={'allowed_paths':['hello.txt'],'forbidden_paths':['secrets/']}
    (tmp_path/'hello.txt').write_text('hello\n'); assert_task_scope(tmp_path,scoped)
    (tmp_path/'other.txt').write_text('other\n')
    try: assert_task_scope(tmp_path,scoped); assert False, 'expected scope violation'
    except ValueError as exc: assert 'other.txt is outside allowed paths' in str(exc)
    (tmp_path/'other.txt').unlink(); (tmp_path/'.harness').mkdir(); (tmp_path/'.harness/config.json').write_text('{}\n')
    try: assert_task_scope(tmp_path,scoped); assert False, 'expected harness scope violation'
    except ValueError as exc: assert '.harness/config.json is outside allowed paths' in str(exc)
def test_schema_files_valid_json():
    for p in (Path(__file__).parents[2]/'.harness/schema').glob('*.json'): json.loads(p.read_text())
