"""Run from repo root after placing TV3_revision files under members/TV3."""
import numpy as np
from members.TV3.network_slicing_env import NetworkSlicingEnv, make_action

def test_terminal_transition_and_contract():
    env = NetworkSlicingEnv('members/TV1/configs/stable_load.yaml')
    obs, _ = env.reset(seed=42)
    assert obs.shape == (5,) and np.isfinite(obs).all()
    for _ in range(500):
        obs, reward, done, truncated, info = env.step(2)
        assert np.isfinite(reward)
        assert info['action']['rb_allocation'] == {'embb':25,'urllc':25}
    assert done and not truncated and np.isfinite(obs).all()

def test_action_mapping():
    state={'time_slot':12}
    assert [make_action(i,state,50)['rb_allocation']['embb'] for i in range(5)] == [10,20,25,30,40]
    assert make_action(1,state,50,request_id='tv5-test')['request_id']=='tv5-test'
