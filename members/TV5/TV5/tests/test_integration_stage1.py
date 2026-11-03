"""Run at NSL root: python -m pytest members/TV5/tests/test_integration_stage1.py -q"""
from members.TV5.integration_runner import make_request_id, run, verify
from pathlib import Path
import csv
import json
import pytest


def test_real_ran_static(tmp_path):
    path=run('static','stable_load',42,5,tmp_path)
    with path.open(encoding='utf-8-sig') as fp: rows=list(csv.DictReader(fp))
    assert len(rows)==10
    assert {r['slice_id'] for r in rows}=={'embb','urllc'}
    assert {r['effective_scheduler'] for r in rows}=={'static'}
    assert {int(r['embb_rb']) for r in rows}=={25}
    assert {r['core_status'] for r in rows}=={'NOT_CONNECTED'}


def test_real_ran_queue(tmp_path):
    path=run('queue_based','urllc_burst',43,6,tmp_path)
    with path.open(encoding='utf-8-sig') as fp: rows=list(csv.DictReader(fp))
    assert len(rows)==12
    assert all(int(row['embb_rb'])+int(row['urllc_rb'])==50 for row in rows)


def test_reproducible(tmp_path):
    a=run('queue_based','stable_load',42,10,tmp_path/'first').read_bytes()
    b=run('queue_based','stable_load',42,10,tmp_path/'second').read_bytes()
    assert a==b


def test_no_unapproved_extra_fields_in_core_handoff():
    value={'schema_version':'1.0.0','request_id':'req-0','seed':42,
       'scenario_id':'stable_load','algorithm':'static','time_slot':0,
       'selected_policy':'low_latency','slice_id':'urllc'}
    with pytest.raises(Exception):
        verify('core_handoff.schema.json',value)
