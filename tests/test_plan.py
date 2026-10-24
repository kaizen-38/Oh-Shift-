"""Smoke tests for scripts/plan.py. Run from the repo root: python3 -m unittest discover tests"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "scripts" / "plan.py"
ASSETS = ROOT / "assets"


def run(*args, home):
    env = dict(os.environ, HOME=home)
    env.pop("SKILL_DATA_DIR", None)
    p = subprocess.run([sys.executable, str(PLAN), *args], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def setup_week(self):
        self.assertEqual(run("profile", "--file", str(ASSETS / "sample_profile.json"), home=self.home)[0], 0)
        code, out, err = run("plan", "--input", str(ASSETS / "sample_week.json"), home=self.home)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_sample_leaves_home_alone(self):
        code, out, _ = run("plan", "--sample", home=self.home)
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(self.home), [])
        self.assertLess(len(out), 8000)

    def test_radar_finds_storm_and_pulls_work(self):
        plan = self.setup_week()
        statuses = [r["status"] for r in plan["radar"]]
        self.assertEqual(statuses[2], "storm")
        self.assertTrue(plan["radar"][3]["partial"])
        self.assertTrue(plan["pulls"])
        self.assertNotEqual(plan["radar"][2]["after_pull"], "storm")

    def test_floors_and_blocks_are_sane(self):
        plan = self.setup_week()
        blocks = plan["blocks"]
        meals = [b for b in blocks if b["kind"] == "meal"]
        self.assertGreaterEqual(len(meals), 12)
        self.assertTrue(any(b["title"] == "Free evening" for b in blocks))
        for b in blocks:
            self.assertLess(b["start"], b["end"])
            self.assertNotIn(b["start"][11:], ("00:00", "01:00", "02:00"))  # nothing during sleep
        spans = sorted((b["start"], b["end"]) for b in blocks if b["title"] != "Free evening")
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            self.assertLessEqual(e1, s2, f"overlap {s1}-{e1} and {s2}-{e2}")
        self.assertLessEqual(sum(1 for b in blocks if b.get("call")), 7)

    def test_replan_keeps_unaffected_blocks(self):
        self.setup_week()
        run("log", "--block", "calisthenics-1", "--status", "skipped", home=self.home)
        code, out, err = run("replan", "--now", "2026-10-26T12:30:00-07:00", home=self.home)
        self.assertEqual(code, 0, err)
        changes = json.loads(out)["changes"]
        self.assertEqual(changes["moved"], [])
        self.assertLessEqual(len(changes["added"]), 1)
        code, out, _ = run("replan", "--now", "2026-10-26T12:45:00-07:00", home=self.home)
        changes = json.loads(out)["changes"]
        self.assertEqual(changes["moved"] + changes["added"] + changes["removed"], [])

    def test_minimum_mode_keeps_floors(self):
        self.setup_week()
        code, out, _ = run("replan", "--now", "2026-10-27T09:00:00-07:00", "--minimum", home=self.home)
        plan = json.loads(out)
        self.assertEqual(plan["mode"], "minimum")
        self.assertIn("triage", plan)
        cal = [b for b in plan["blocks"] if b.get("goal_id") == "calisthenics"]
        self.assertGreaterEqual(len(cal), 1)

    def test_reality_check_multiplier(self):
        self.setup_week()
        code, out, _ = run("log", "--task", "canvas-502", "--status", "done", "--actual-hours", "2", home=self.home)
        self.assertEqual(code, 0)
        self.assertGreater(json.loads(out)["logged"]["multiplier"], 1.0)

    def test_exit_codes(self):
        self.assertEqual(run("plan", "--input", str(ASSETS / "sample_week.json"), home=self.home)[0], 3)
        self.assertEqual(run("show", home=self.home)[0], 5)
        self.setup_week()
        self.assertEqual(run("log", "--block", "nope", "--status", "done", home=self.home)[0], 4)
        bad = Path(self.home) / "bad.json"
        bad.write_text('{"now": "2026-10-25T19:00:00", "tasks": []}')
        self.assertEqual(run("plan", "--input", str(bad), home=self.home)[0], 2)


if __name__ == "__main__":
    unittest.main()
