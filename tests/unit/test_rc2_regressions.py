"""RC2 trust boundaries and durable phase rollback regressions."""
import json

import pytest
from pydantic import ValidationError

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter, default_investigation, make_blocking_issue
from agent_review.agents.pi import READ_ONLY_TOOLS, _STARTUP_ARGS, RealPiAdapter
from agent_review.config import AgentConfig
from agent_review.models import Decision, IssueCategory, IssueStatus, Phase
from agent_review.orchestrator import Orchestrator
from agent_review.phases.review import ingest_new_issues
from tests.unit.test_m3_human_gate import ScriptedUI, candidate, discovery_with_candidates
from tests.unit.test_m6_recovery import make


@pytest.mark.parametrize('status', list(IssueStatus))
@pytest.mark.parametrize('provenance', ['INITIAL_REVIEW', 'CLOSURE_REVIEW', 'FINAL_REVIEW'])
def test_reviewer_cannot_supply_lifecycle(repo, status, provenance):
    o = make(repo)
    issue = make_blocking_issue(1)
    issue.category = IssueCategory.REGRESSION
    issue.status = status
    issue.addressed_by = 'forged'
    issue.resolution = 'forged'
    ingest_new_issues(o, [issue], provenance)
    saved = o.store.load_issues().issues[0]
    assert saved.status == IssueStatus.OPEN
    assert saved.addressed_by is None and saved.resolution is None


@pytest.mark.parametrize('category', ['REQUIREMENT', 'FACT'])
def test_human_blocker_never_reaches_author_revision(repo, category):
    issue = make_blocking_issue(1).model_dump(mode='json')
    issue.update(category=category, status='RESOLVED')
    pi = FakePiAdapter()
    o = make(repo, pi, FakeCodexAdapter({'initial_review': [json.dumps({'issues': [issue]})]}))
    assert o.run() == 10
    assert o.store.load_issues().issues[0].status == IssueStatus.NEED_HUMAN
    assert not any(c[0] in ('revise', 'ablate') for c in pi.calls)


@pytest.mark.parametrize('patch', [
    {'root_cause': ' '}, {'evidence': []},
    {'evidence': [{'description': ' ', 'location': 'src/a.py:1'}]},
    {'evidence': [{'description': 'observed', 'location': ''}]},
    {'causal_chain': []}, {'causal_chain': [' ']},
    {'unresolved_contradictions': ['trace contradicts hypothesis']},
    {'missing_evidence': ['material runtime fact']},
])
def test_supported_requires_complete_evidence(patch):
    result = default_investigation()
    with pytest.raises(ValidationError):
        type(result).model_validate({**result.model_dump(), **patch})


def test_invalid_supported_repairs_then_fails_without_design(repo):
    invalid = json.dumps({'root_cause_status': 'SUPPORTED'})
    pi = FakePiAdapter({'investigate': [invalid], 'investigate:repair': [invalid]})
    o = Orchestrator.create(repo, 'diagnose', task_kind_explicit='problem', pi=pi, codex=FakeCodexAdapter())
    assert o.run() == 30
    assert not any(c[0] == 'design' for c in pi.calls)
    assert pi.protocol_retries_used == 1


def test_fact_gate_passes_active_decisions_to_reinvestigation(repo):
    class FactPi(FakePiAdapter):
        def investigate(self, state, discovery=None, decisions=None):
            if not decisions:
                return type(default_investigation())(
                    human_candidates=[candidate(category='FACT')],
                    missing_evidence=['pause semantics'],
                )
            assert len(decisions) == 1
            assert decisions[0].answer_text == 'Cooperative pause between steps'
            return default_investigation()

    o = Orchestrator.create(repo, 'diagnose', task_kind_explicit='problem',
                            pi=FactPi(), codex=FakeCodexAdapter(), ui=ScriptedUI(['1']))
    assert o.run() == 0
    assert o.state.task_revision == 2


def test_real_investigation_prompt_contains_human_fact(repo, monkeypatch):
    o = make(repo)
    adapter = RealPiAdapter(AgentConfig(), repo)
    captured = {}
    def capture(phase, prompt, model):
        captured['prompt'] = prompt
        return default_investigation()
    monkeypatch.setattr(adapter, '_call', capture)
    decision = Decision(decision_id='D001', decision_key='fact', gate_id='HG001',
                        question='Which backend?', answer_text='Kafka')
    adapter.investigate(o.state, decisions=[decision])
    assert 'Kafka' in captured['prompt'] and 'Which backend?' in captured['prompt']


def test_final_retains_every_design_and_change_map_field(repo):
    o = make(repo)
    while o.state.phase != Phase.INITIAL_REVIEW:
        o.step()
    proposal = o.store.load_proposal()
    markers = []
    for name in type(proposal).model_fields:
        if name in ('change_map', 'based_on_task_revision'):
            continue
        marker = f'unique-{name}'
        markers.append(marker)
        setattr(proposal, name, [marker] if isinstance(getattr(proposal, name), list) else marker)
    for name in type(proposal.change_map).model_fields:
        marker = f'map-{name}'
        markers.append(marker)
        setattr(proposal.change_map, name, [marker])
    o.store.save_proposal(proposal)
    assert o.run() == 0
    assert all(marker in o.store.read_text('final.md') for marker in markers)


@pytest.mark.parametrize('crash_phase', [Phase.INITIAL_REVIEW, Phase.REVISION, Phase.CLOSURE_REVIEW, Phase.ABLATION, Phase.FINAL_REVIEW])
def test_crash_after_phase_outputs_rolls_back_entire_boundary(repo, monkeypatch, crash_phase):
    issue = make_blocking_issue(1).model_dump(mode='json')
    codex = FakeCodexAdapter({'initial_review': [json.dumps({'issues': [issue]})],
                             'closure_review': [json.dumps({'issue_outcomes': [{'issue_id': 'R001', 'resolution': 'UNRESOLVED'}]})]})
    o = make(repo, codex=codex)
    while o.state.phase != crash_phase:
        o.step()
    before_state = o.state.model_dump(exclude={'updated_at'})
    before_issues = o.store.load_issues()
    before_proposal = o.store.load_proposal()
    original_commit = o.store.commit_phase
    def crash():
        raise SystemExit('simulated process death after state write')
    monkeypatch.setattr(o.store, 'commit_phase', crash)
    with pytest.raises(SystemExit):
        o.step()
    # A fresh process must recover even if rollback itself was interrupted.
    monkeypatch.setattr(o.store, 'commit_phase', original_commit)
    resumed = Orchestrator.resume(repo, o.state.session_id, pi=FakePiAdapter(), codex=FakeCodexAdapter())
    assert resumed.state.model_dump(exclude={'updated_at'}) == before_state
    assert resumed.store.load_issues() == before_issues
    assert resumed.store.load_proposal() == before_proposal
    assert resumed.run() == 0


def test_archive_never_removes_last_valid_proposal(repo):
    o = make(repo)
    while o.state.phase != Phase.INITIAL_REVIEW:
        o.step()
    before = o.store.load_proposal()
    first = o.store.archive_proposal('revision')
    second = o.store.archive_proposal('revision')
    assert first != second
    assert o.store.load_proposal() == before
    assert (o.store.dir / 'proposal.md').exists()


def test_readonly_navigation_allowlist():
    assert READ_ONLY_TOOLS == ['read', 'grep', 'find', 'ls']
    assert _STARTUP_ARGS[_STARTUP_ARGS.index('--tools') + 1] == 'read,grep,find,ls'
    assert '--no-extensions' in _STARTUP_ARGS
    assert '--no-skills' in _STARTUP_ARGS


@pytest.mark.parametrize('artifact', ['proposal.json', 'change-map.json', 'proposal.md', 'issues.json', 'state.json'])
def test_process_death_between_revision_writes(repo, monkeypatch, artifact):
    import agent_review.storage as storage
    issue = make_blocking_issue(1).model_dump(mode='json')
    o = make(repo, codex=FakeCodexAdapter({'initial_review': [json.dumps({'issues': [issue]})]}))
    while o.state.phase != Phase.REVISION:
        o.step()
    old_proposal = o.store.load_proposal()
    old_issues = o.store.load_issues()
    old_state = o.state.model_dump(exclude={'updated_at'})
    o.store.begin_phase()
    write = storage._atomic_write
    def crash_after_write(path, data):
        write(path, data)
        if path.name == artifact:
            raise SystemExit('process died')
    monkeypatch.setattr(storage, '_atomic_write', crash_after_write)
    # Bypass exception handling to model an abrupt process death.
    with pytest.raises(SystemExit):
        o._step()
    monkeypatch.setattr(storage, '_atomic_write', write)
    resumed = Orchestrator.resume(repo, o.state.session_id, pi=FakePiAdapter(), codex=FakeCodexAdapter())
    assert resumed.state.model_dump(exclude={'updated_at'}) == old_state
    assert resumed.store.load_proposal() == old_proposal
    assert resumed.store.load_issues() == old_issues
    assert resumed.run() == 0
    assert resumed.state.budgets.revision_used == 1


@pytest.mark.parametrize('artifact', ['decisions.json', 'issues.json', 'state.json'])
def test_gate_application_crash_preserves_answers_without_duplicate_decisions(repo, monkeypatch, artifact):
    import agent_review.storage as storage
    pi = FakePiAdapter({'discover': [discovery_with_candidates([candidate()])]})
    o = make(repo, pi=pi)
    assert o.run() == 20
    o.ui = ScriptedUI(['1'])
    write = storage._atomic_write
    def crash_after_write(path, data):
        write(path, data)
        if path.name == artifact:
            raise SystemExit('process died')
    monkeypatch.setattr(storage, '_atomic_write', crash_after_write)
    o.store.begin_phase()
    with pytest.raises(SystemExit):
        o._step()
    monkeypatch.setattr(storage, '_atomic_write', write)
    class NoMoreQuestions(ScriptedUI):
        def ask(self, prompt):
            pytest.fail('confirmed answer was asked again')
    resumed = Orchestrator.resume(repo, o.state.session_id, pi=FakePiAdapter(),
                                  codex=FakeCodexAdapter(), ui=NoMoreQuestions())
    assert resumed.run() == 0
    assert len(resumed.store.load_decisions().decisions) == 1
    assert resumed.state.task_revision == 2
    assert resumed.state.budgets.human_interruptions_used == 1


def test_resume_preserves_protocol_retry_usage(repo):
    pi = FakePiAdapter({'discover': ['invalid'], 'design': [KeyboardInterrupt()]})
    o = make(repo, pi=pi)
    assert o.run() == 130
    assert o.state.budgets.protocol_retries_used == 1
    resumed = Orchestrator.resume(repo, o.state.session_id, pi=FakePiAdapter(), codex=FakeCodexAdapter())
    assert resumed.run() == 0
    assert resumed.state.budgets.protocol_retries_used == 1
