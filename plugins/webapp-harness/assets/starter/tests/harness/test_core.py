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
from record_result import record
from reprioritize import reprioritize
from archive_completed_tasks import archive_completed
from common import priority_sort_key
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
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('Z-001',priority=1),task('A-001',priority=1),task('B-001',priority=5)]}); assert select(r)['task_id']=='A-001'
def test_priority_sort_key_orders_low_values_first():
    assert priority_sort_key({'id':'A-002','priority':1})<priority_sort_key({'id':'A-001','priority':2})
    assert priority_sort_key({'id':'A-001'})>priority_sort_key({'id':'Z-099','priority':999})
def test_dependency_blocks_selection(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001',deps=['B-001']),task('B-001')]}); assert select(r)['task_id']=='B-001'

def test_archived_completion_satisfies_selection_and_preserves_full_record(tmp_path):
    r=fixture(tmp_path)
    completed=task('DONE-001',status='completed')
    dependent=task('NEXT-001',deps=['DONE-001'])
    write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[completed,dependent]})
    run_dir=r/'.harness/runs'/'DONE-001-run'; run_dir.mkdir(parents=True)
    write_json(run_dir/'run.json',{'task_id':'DONE-001','status':'completed','result_commit':'abc123','completed_at':'2026-07-25T00:00:00Z'})
    result=archive_completed(r)
    assert result['archived_task_ids']==['DONE-001']
    backlog=json.loads((r/'.harness/backlog.json').read_text())
    assert [entry['id'] for entry in backlog['tasks']]==['NEXT-001']
    index=json.loads((r/'.harness/completed-tasks.json').read_text())
    assert index['completed_tasks']==[{'task_id':'DONE-001','commit':'abc123','completed_at':'2026-07-25T00:00:00Z'}]
    archive_records=[json.loads(line) for line in (r/'.harness/archive/completed-tasks.jsonl').read_text().splitlines()]
    assert archive_records[0]['task']==completed
    assert archive_records[0]['completion']==index['completed_tasks'][0]
    assert not validate(r)
    assert select(r)['task_id']=='NEXT-001'

def test_archiving_requires_committed_run_evidence_and_dry_run_does_not_write(tmp_path):
    r=fixture(tmp_path); completed=task('DONE-001',status='completed')
    write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[completed]})
    try: archive_completed(r); assert False, 'expected missing committed run failure'
    except ValueError as exc: assert 'result commit' in str(exc)
    run_dir=r/'.harness/runs'/'DONE-001-run'; run_dir.mkdir(parents=True)
    write_json(run_dir/'run.json',{'task_id':'DONE-001','status':'completed','result_commit':'abc123','completed_at':'2026-07-25T00:00:00Z'})
    assert archive_completed(r,dry_run=True)['archived_task_ids']==['DONE-001']
    assert json.loads((r/'.harness/backlog.json').read_text())['tasks'][0]['id']=='DONE-001'
    assert not (r/'.harness/archive/completed-tasks.jsonl').exists()
def test_explicit_task_selection_preserves_sequential_eligibility(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001'),task('B-001',priority=10)]}); assert select(r,'A-001')['task_id']=='A-001'

def test_selection_writes_extracted_current_task_document(tmp_path):
    r=fixture(tmp_path); selected_task=task('A-001')
    write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[selected_task]})
    selected=select(r)
    current=json.loads((r/'.harness/current-task.json').read_text())
    assert current['run_id']==selected['run_id'] and current['task']==selected_task
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

def test_backlog_proposal_respects_archived_task_ids_and_dependencies(tmp_path):
    r=fixture(tmp_path)
    write_json(r/'.harness/completed-tasks.json',{'schema_version':1,'completed_tasks':[{'task_id':'DONE-001','commit':'abc123','completed_at':'2026-07-25T00:00:00Z'}]})
    proposal=r/'proposal.json'; dependent=proposed_task('GAP-001',deps=['DONE-001'])
    write_json(proposal,{'schema_version':1,'tasks':[dependent]})
    assert preview_proposal(r,proposal)['task_count']==1
    duplicate=proposed_task('DONE-001')
    write_json(proposal,{'schema_version':1,'tasks':[duplicate]})
    try: preview_proposal(r,proposal); assert False, 'expected archived ID conflict'
    except ValueError as exc: assert 'already exist' in str(exc)

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
    tasks=[task('LOW-001',priority=10),task('HIGH-002',priority=1),task('HIGH-001',priority=1),task('WAIT-001',deps=['BLOCK-001']),task('BLOCK-001',status='blocked'),task('IDEA-001',status='proposed')]
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

def test_backlog_status_counts_archived_completions(tmp_path):
    r=fixture(tmp_path)
    write_json(r/'.harness/completed-tasks.json',{'schema_version':1,'completed_tasks':[{'task_id':'DONE-001','commit':'abc123','completed_at':'2026-07-25T00:00:00Z'}]})
    status=backlog_status(r)
    assert status['next_action']=='complete'
    assert status['task_count']==1 and status['active_task_count']==0
    assert status['archived_completed_task_count']==1 and status['status_counts']=={'completed':1}

def test_schema_files_valid_json():
    for p in (Path(__file__).parents[2]/'.harness/schema').glob('*.json'): json.loads(p.read_text())

def browser_task(status='ready'):
    t=task('A-001',status=status); t['verification']['requires_browser']=True; return t

def browser_result(rid,criterion='AC-1',screenshots=None):
    return {'task_id':'A-001','run_id':rid,'status':'PASSED','tooling':{'surface':'playwright'},'criteria':[{'criterion_id':criterion,'result':'PASS','steps':['step'],'observed':'o','expected':'e','url':'http://localhost','console_errors':[],'network_errors':[],'screenshots':screenshots or []}]}

def test_reviewing_requires_passed_browser_validation_when_required(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[browser_task()]})
    selected=select(r); transition(r,'A-001','verifying','implemented')
    try: transition(r,'A-001','reviewing','verified'); assert False, 'expected browser gate'
    except ValueError as exc: assert 'browser validation' in str(exc)
    run_path=r/'.harness/runs'/selected['run_id']/'run.json'; run=json.loads(run_path.read_text())
    run['browser_validation']={'status':'PASSED'}; write_json(run_path,run)
    transition(r,'A-001','reviewing','verified')
    assert json.loads((r/'.harness/backlog.json').read_text())['tasks'][0]['status']=='reviewing'

def test_reviewing_skips_browser_gate_when_not_required(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001')]})
    select(r); transition(r,'A-001','verifying','implemented'); transition(r,'A-001','reviewing','verified')
    assert json.loads((r/'.harness/backlog.json').read_text())['tasks'][0]['status']=='reviewing'

def test_record_browser_result_requires_screenshot_files(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[browser_task()]})
    selected=select(r); rid=selected['run_id']; evidence_dir=r/'.harness/runs'/rid/'evidence'; evidence_dir.mkdir(parents=True)
    shot=f'.harness/runs/{rid}/evidence/ac1.png'
    input_path=r/'browser.json'; write_json(input_path,browser_result(rid,screenshots=[shot]))
    try: record(r,'browser-result',input_path); assert False, 'expected missing screenshot failure'
    except ValueError as exc: assert 'Missing screenshot file' in str(exc)
    (evidence_dir/'ac1.png').write_bytes(b'png')
    record(r,'browser-result',input_path)
    recorded=json.loads((r/'.harness/runs'/rid/'browser-result.json').read_text())
    assert recorded['criteria'][0]['screenshots']==[shot]

def test_record_browser_result_rejects_screenshots_outside_run(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[browser_task()]})
    selected=select(r); (r/'outside.png').write_bytes(b'png')
    input_path=r/'browser.json'; write_json(input_path,browser_result(selected['run_id'],screenshots=['outside.png']))
    try: record(r,'browser-result',input_path); assert False, 'expected location failure'
    except ValueError as exc: assert 'under the active run directory' in str(exc)

def test_reprioritize_assigns_order_and_rejects_unknown_ids(tmp_path):
    r=fixture(tmp_path); write_json(r/'.harness/backlog.json',{'schema_version':1,'tasks':[task('A-001',priority=7),task('B-001',priority=3)]})
    assert reprioritize(r,['B-001','A-001'])=={'B-001':1,'A-001':2}
    assert [t['priority'] for t in json.loads((r/'.harness/backlog.json').read_text())['tasks']]==[2,1]
    try: reprioritize(r,['NOPE-1']); assert False, 'expected unknown id failure'
    except ValueError as exc: assert 'Unknown task IDs' in str(exc)
    try: reprioritize(r,['A-001','A-001']); assert False, 'expected duplicate failure'
    except ValueError as exc: assert 'Duplicate task IDs' in str(exc)
