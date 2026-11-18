
"""Tests for episode seed separation; run from NSL repo root."""
from members.TV3.network_slicing_env import NetworkSlicingEnv, make_action


def test_training_seed_sequence_ignores_sb3_initial_seed():
    env = NetworkSlicingEnv(episode_seed_base=100000)
    try:
        values = [env.reset(seed=100 if i == 0 else None)[1]["effective_seed"]
                  for i in range(4)]
        assert values == [100000, 100001, 100002, 100003]
        assert env.actual_episode_seeds == values
        assert not set(values) & {42, 43, 44, 200101, 200102, 200103}
    finally:
        env.close()


def test_validation_explicit_seeds_reproduce_same_state():
    env = NetworkSlicingEnv()
    try:
        first = []
        for seed in (200101, 200102, 200103):
            obs, info = env.reset(seed=seed)
            assert info["effective_seed"] == seed
            first.append(obs.copy())
        for seed, previous in zip((200101, 200102, 200103), first):
            obs, info = env.reset(seed=seed)
            assert info["effective_seed"] == seed
            assert (obs == previous).all()
    finally:
        env.close()


def test_optional_cyclic_validation_seed_schedule():
    env = NetworkSlicingEnv(episode_seeds=(200101, 200102, 200103))
    try:
        values = [env.reset()[1]["effective_seed"] for _ in range(6)]
        assert values == [200101, 200102, 200103] * 2
    finally:
        env.close()


def test_legacy_explicit_reset_unchanged():
    env = NetworkSlicingEnv()
    try:
        assert env.reset(seed=42)[1]["effective_seed"] == 42
        assert env.reset(seed=43)[1]["effective_seed"] == 43
    finally:
        env.close()


def test_action_mapping_is_unchanged():
    state = {"time_slot": 12}
    expected = [10, 20, 25, 30, 40]
    for index, rb in enumerate(expected):
        action = make_action(index, state, 50, "seed-safe-test")
        assert action["rb_allocation"]["embb"] == rb
        assert action["rb_allocation"]["urllc"] == 50 - rb
        assert action["request_id"] == "seed-safe-test"
