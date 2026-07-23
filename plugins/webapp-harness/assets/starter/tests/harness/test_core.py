import json, shutil, subprocess
from pathlib import Path
from lifecycle import can_transition
from validate_state import validate
from select_next_task import select
from backlog_status import backlog_status
from update_task_state import transition
from verify_task import verify
from create_task_commit import assert_task_scope
from merge_backlog_proposal import apply as apply_proposal, preview as preview_proposal
from conftest import write_json

def fixture(tmp_path):
    shutil.copytree(Path(__file__).parents[2]/'.harness',tmp_path/'.harness')
    config=json.loads((tmp_path/'.harness/config.json').read_text())
    config['verification_profiles']={'unit':[{'name':'Unit tests','command':['python','-c','print("ok")']}]}
    write_json(tmp_path/'.harness/config.json',config)
    return tmp_path

def task(i,status='ready',priority=1,deps=None):
    return {'id':i,'title':'Task '+i,'description':'A test task','status':status,'priority':priority,'dependencies':deps or [],'type':'backend','acceptance_criteria':[{'id':'AC-1','description':'Works','verification':['unit']}],'verification':{'profiles':[],'requires_browser':False,'requires_e2e':False},'scope':{'allowed_paths':['src/'],'forbidden_paths':[]}}

def proposed_task(i='GAP-001',deps=None):
    proposed=task(i,status='proposed',deps=deps)
    proposed['gap_evidence']=[{'location':'src/example.py:1','observation':'Required behavior is missing.'}]
    proposed['verification']['profiles']=['unit']
    return proposed

def test_lifecycle(): assert can_transition('ready','implementing') and not can_transition('ready','completed')
def test_deterministic_selection(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('Z-002',priority=10),task('A-001',priority=10),task('B-001',priority=5)]}); assert select(r)['task_id']=='A-001'
def test_dependency_blocks_selection(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001',deps=['B-001']),task('B-001')]}); assert select(r)['task_id']=='B-001'
def test_explicit_task_selection_preserves_sequential_eligibility(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001'),task('B-001',priority=10)]}); assert select(r,'A-001')['task_id']=='A-001'
def test_explicit_task_selection_rejects_dependency_stalled_task(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001',deps=['B-001']),task('B-001')]})
    try: select(r,'A-001'); assert False, 'expected eligibility failure'
    except ValueError as exc: assert 'not eligible' in str(exc)
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

def test_backlog_proposal_preview_does_not_write(tmp_path):
    r=fixture(tmp_path); proposal=r/'proposal.json'
    write_json(proposal,{'schema_version':1,'tasks':[proposed_task()]})
    before=(r/'.harness/backlog.json').read_text()
    plan=preview_proposal(r,proposal)
    assert plan['task_count']==1 and len(plan['proposal_sha256'])==64
    assert (r/'.harness/backlog.json').read_text()==before

def test_backlog_proposal_requires_confirmation_and_matching_hash(tmp_path):
    r=fixture(tmp_path); proposal=r/'proposal.json'
    write_json(proposal,{'schema_version':1,'tasks':[proposed_task()]})
    plan=preview_proposal(r,proposal)
    try: apply_proposal(r,proposal,plan['proposal_sha256'],False); assert False, 'expected confirmation failure'
    except ValueError as exc: assert '--confirmed' in str(exc)
    proposal.write_text(proposal.read_text().replace('Required behavior','Observed behavior'))
    try: apply_proposal(r,proposal,plan['proposal_sha256'],True); assert False, 'expected hash failure'
    except ValueError as exc: assert 'changed after preview' in str(exc)

def test_backlog_proposal_appends_only_proposed_tasks(tmp_path):
    r=fixture(tmp_path); proposal=r/'proposal.json'
    write_json(proposal,{'schema_version':1,'tasks':[proposed_task()]})
    plan=preview_proposal(r,proposal)
    result=apply_proposal(r,proposal,plan['proposal_sha256'],True)
    backlog=json.loads((r/'.harness/backlog.json').read_text())
    assert result['appended_task_ids']==['GAP-001']
    assert backlog['tasks'][0]['status']=='proposed'
    assert backlog['tasks'][0]['gap_evidence']

def test_backlog_proposal_rejects_duplicates_and_unknown_profiles(tmp_path):
    r=fixture(tmp_path); proposal=r/'proposal.json'
    first=proposed_task('GAP-001')
    second=proposed_task('GAP-002')
    second['verification']['profiles']=['missing']
    write_json(proposal,{'schema_version':1,'tasks':[first,second,proposed_task('GAP-001')]})
    try: preview_proposal(r,proposal); assert False, 'expected proposal failure'
    except ValueError as exc:
        message=str(exc)
        assert 'repeat' in message and 'unknown verification profiles' in message

def test_backlog_proposal_rejects_dependency_cycle(tmp_path):
    r=fixture(tmp_path); proposal=r/'proposal.json'
    first=proposed_task('GAP-001',deps=['GAP-002'])
    second=proposed_task('GAP-002',deps=['GAP-001'])
    write_json(proposal,{'schema_version':1,'tasks':[first,second]})
    try: preview_proposal(r,proposal); assert False, 'expected proposal failure'
    except ValueError as exc: assert 'cycle' in str(exc)

def test_backlog_proposal_requires_executable_verification_profile(tmp_path):
    r=fixture(tmp_path); proposal=r/'proposal.json'; proposed=proposed_task()
    proposed['verification']['profiles']=[]
    write_json(proposal,{'schema_version':1,'tasks':[proposed]})
    try: preview_proposal(r,proposal); assert False, 'expected proposal failure'
    except ValueError as exc: assert 'at least one verification profile' in str(exc)

def test_backlog_status_orders_eligible_tasks_and_reports_stalls(tmp_path):
    r=fixture(tmp_path)
    tasks=[task('LOW-001',priority=1),task('HIGH-002',priority=10),task('HIGH-001',priority=10),task('WAIT-001',deps=['BLOCK-001']),task('BLOCK-001',status='blocked'),task('IDEA-001',status='proposed')]
    write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':tasks})
    status=backlog_status(r)
    assert status['next_action']=='select_next'
    assert status['eligible_task_ids']==['HIGH-001','HIGH-002','LOW-001']
    assert status['unresolved']=={'proposed':['IDEA-001'],'blocked':['BLOCK-001'],'dependency_stalled':['WAIT-001']}

def test_backlog_status_distinguishes_complete_empty_and_awaiting_approval(tmp_path):
    r=fixture(tmp_path)
    assert backlog_status(r)['next_action']=='empty'
    write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('DONE-001',status='completed')]})
    complete=backlog_status(r)
    assert complete['complete'] is True and complete['next_action']=='complete'
    write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('IDEA-001',status='proposed')]})
    assert backlog_status(r)['next_action']=='awaiting_approval'

def test_schema_files_valid_json():
    for p in (Path(__file__).parents[2]/'.harness/schema').glob('*.json'): json.loads(p.read_text())
