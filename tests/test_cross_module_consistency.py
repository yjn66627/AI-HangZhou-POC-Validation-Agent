import json
from copy import deepcopy
from pathlib import Path

import pytest

from experiment.schemas import SchemaValidationError, validate_linked_inputs

ROOT=Path(__file__).resolve().parents[1]

def load(): return json.loads((ROOT/'examples'/'fx-success_bundle.json').read_text(encoding='utf-8'))

def test_linked_identifiers_consistent():
    b=load(); validate_linked_inputs(b['task'],b['candidate'],b['experiment_spec'])

def test_required_tool_must_exist_in_candidate_and_task():
    b=load(); bad=deepcopy(b['experiment_spec']); bad['required_tools']=['missing_tool']
    with pytest.raises(SchemaValidationError,match='requires_tool'): validate_linked_inputs(b['task'],b['candidate'],bad)
