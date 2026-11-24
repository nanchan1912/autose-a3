"""JSON schemas for the structured output of each agent (passed to `claude -p --json-schema`).
The hand-off between stages is these documents, never an agent's conversation."""


def _obj(props: dict, required: list | None = None) -> dict:
    return {'type': 'object', 'properties': props, 'required': required or list(props),
            'additionalProperties': False}


S = {'type': 'string'}
SA = {'type': 'array', 'items': S}

SPEC = _obj({
    'status': {'type': 'string', 'enum': ['READY', 'PROVISIONAL', 'BLOCKED']},
    'title': S,
    'summary': S,
    'spec_markdown': S,
    'acceptance_criteria': {'type': 'array', 'items': _obj({
        'id': S, 'requirement': S, 'given': S, 'when': S, 'then': S,
        'evidence': {'type': 'string', 'enum': ['STATED', 'INFERRED', 'ASSUMPTION']},
    })},
    'clarification_questions': {'type': 'array', 'items': _obj({
        'id': S, 'question': S, 'why_it_matters': S, 'options': SA, 'blocks': SA,
    })},
    'untrusted_instructions_seen': SA,
})

DESIGN = _obj({
    'approach': S,
    'files': {'type': 'array', 'items': _obj({
        'path': S,
        'action': {'type': 'string', 'enum': ['modify', 'create']},
        'symbols': {'type': 'array', 'items': _obj({
            'name': S, 'status': {'type': 'string', 'enum': ['existing', 'new']},
        })},
        'change': S,
    })},
    'test_plan': {'type': 'array', 'items': _obj({'ac_id': S, 'test_file': S, 'test_name': S})},
    'architecture_rules': SA,
    'risks': SA,
    'design_markdown': S,
})

IMPLEMENTATION = _obj({
    'summary': S,
    'files_changed': SA,
    'deviations_from_design': SA,
    'test_disputes': {'type': 'array', 'items': _obj({'test': S, 'reason': S})},
})

TESTS = _obj({
    'summary': S,
    'tests': {'type': 'array', 'items': _obj({'ac_id': S, 'test_file': S, 'test_name': S})},
    'spec_problems': SA,
})

REVIEW = _obj({
    'summary': S,
    'issue_requirements': {'type': 'array', 'items': _obj({
        'requirement': S, 'met': {'type': 'string', 'enum': ['yes', 'no', 'unclear']}, 'evidence': S,
    })},
    'checks_run': {'type': 'array', 'items': _obj({'command': S, 'outcome': S})},
    'findings': {'type': 'array', 'items': _obj({
        'id': S,
        'severity': {'type': 'string', 'enum': ['blocking', 'major', 'minor', 'nit']},
        'category': {'type': 'string', 'enum': ['correctness', 'regression', 'tests', 'approach', 'scope',
                                                'security', 'style', 'docs']},
        'route': {'type': 'string', 'enum': ['design', 'implement', 'test']},
        'file': S, 'line': {'type': 'integer'},
        'description': S, 'evidence': S, 'suggested_fix': S,
    })},
    'verdict': {'type': 'string', 'enum': ['approve', 'request_changes']},
})
