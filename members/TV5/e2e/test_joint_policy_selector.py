"""Offline synthetic unit tests. NOT real RAN/Core experimental evidence."""
import copy
import unittest
from members.TV5.e2e.joint_policy_selector import select_joint_policy


def make_input():
    base = dict(calibration_scenario="stable_load", calibration_seeds=[101, 102, 103])
    return dict(scenario="stable_load", evaluation_seed=42, g_min_mbps=8.0,
        core_health=dict(r2=True, r3=True), candidates=[
            dict(base, scheduler="static", embb_policy="high_bandwidth", urllc_policy="low_latency", urllc_on_time_rate_est=.96, embb_goodput_mbps_est=9.0, evidence_id="SYNTHETIC_STATIC"),
            dict(base, scheduler="qos_heuristic", embb_policy="low_latency", urllc_policy="low_latency", urllc_on_time_rate_est=.98, embb_goodput_mbps_est=8.5, evidence_id="SYNTHETIC_QOS"),
            dict(base, scheduler="dqn", embb_policy="high_bandwidth", urllc_policy="low_latency", urllc_on_time_rate_est=.99, embb_goodput_mbps_est=6.0, evidence_id="SYNTHETIC_DQN"),
        ])


class JointSelectorTests(unittest.TestCase):
    def test_best_feasible_pair(self):
        d=select_joint_policy(make_input())
        self.assertEqual(d["selected"]["scheduler"], "qos_heuristic")
        self.assertEqual(d["status"], "SELECTED_OFFLINE_NOT_APPLIED")
        self.assertFalse(d["candidate_audit"][2]["feasible"])

    def test_r3_unavailable_is_fail_closed(self):
        x=make_input();x["core_health"]["r3"]=False
        d=select_joint_policy(x)
        self.assertEqual(d["status"], "NO_FEASIBLE_CANDIDATE")
        self.assertIsNone(d["selected"])

    def test_gmin_higher_than_every_candidate(self):
        x=make_input();x["g_min_mbps"]=100
        self.assertIsNone(select_joint_policy(x)["selected"])

    def test_evaluation_seed_leakage_blocked(self):
        x=make_input();x["candidates"][0]["calibration_seeds"].append(42)
        with self.assertRaisesRegex(ValueError,"evaluation-seed leakage"):
            select_joint_policy(x)

    def test_unmatched_candidate_seed_set_blocked(self):
        x=make_input();x["candidates"][1]["calibration_seeds"]=[100, 101, 102]
        with self.assertRaisesRegex(ValueError,"exactly the same"):
            select_joint_policy(x)

    def test_rejected_urllc_route(self):
        x=make_input();x["candidates"][0]["urllc_policy"]="high_bandwidth"
        with self.assertRaisesRegex(ValueError,"must remain low_latency"):
            select_joint_policy(x)

    def test_invalid_estimated_rate(self):
        x=make_input();x["candidates"][0]["urllc_on_time_rate_est"]=1.1
        with self.assertRaisesRegex(ValueError,"invalid QoS"):
            select_joint_policy(x)

    def test_deterministic_and_no_mutation(self):
        x=make_input();snapshot=copy.deepcopy(x)
        self.assertEqual(select_joint_policy(x), select_joint_policy(x))
        self.assertEqual(x,snapshot)


if __name__ == "__main__":
    unittest.main()
