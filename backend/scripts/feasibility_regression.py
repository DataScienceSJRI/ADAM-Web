"""Feasibility regression check: runs a fixed set of (user, week, start_date)
cases through the real production plan-generation path and asserts none of
them need more taper relaxation than a documented allow-list. Intended to be
run manually, on demand -- before/after any hard-constraint change to
lp_optimizer.py or routers/plan.py -- not on every test suite run (each case
is a real LP solve against live Supabase data and can take several minutes,
so this deliberately lives outside `tests/` and pytest's testpaths).

No Supabase writes: uses services.dry_run_testing.stub_all_writes.

Usage:
    cd backend && PYTHONPATH=. ./.adam/bin/python3 scripts/feasibility_regression.py

Exit code is 0 if every case is within its allowed taper-stage, 1 otherwise
(so this can be dropped into a pre-change/post-change comparison workflow).
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routers.plan as plan_module
from models.schemas import GeneratePlanRequest
from services.profile_builder import build_profile
from services.dry_run_testing import stub_all_writes, is_usable, taper_stage_from_status

# (user_id, week_no, start_date, max_allowed_taper_stage)
# max_allowed_taper_stage: 0 = must solve on full taper, no relaxation
# allowed; 1/2/3 = that stage of relaxation (see routers/plan.py's
# TAPER_STAGES) is tolerated without failing the regression check. Update
# this list's dates as real weeks roll forward, and revisit the allowed
# stage for a case if a deliberate constraint change is expected to need it.
CASES = [
    ("A001_MAHENDRA", 1, date(2026, 8, 11), 1),
    ("A001_MAHENDRA", 2, date(2026, 8, 18), 1),
    ("A001_MAHENDRA", 3, date(2026, 8, 25), 0),
    ("A002_NASIR", 1, date(2026, 8, 12), 1),
    ("A002_NASIR", 2, date(2026, 8, 19), 1),
    ("A002_NASIR", 3, date(2026, 8, 26), 0),
    ("A003_ANISH", 1, date(2026, 8, 13), 1),
    ("A003_ANISH", 2, date(2026, 8, 20), 1),
    ("A003_ANISH", 3, date(2026, 8, 27), 0),
    ("A004_RAJAT", 1, date(2026, 9, 5), 1),
    ("A004_RAJAT", 2, date(2026, 9, 12), 1),
    ("A004_RAJAT", 3, date(2026, 9, 19), 0),
]


def main() -> int:
    results = []
    for user_id, week_no, start_date, max_allowed_stage in CASES:
        captured = stub_all_writes(plan_module)
        profile = build_profile(user_id)
        body = GeneratePlanRequest(week_no=week_no, onboarding_id=None, target_user_id=user_id)

        print(f"\n{'='*70}\n{user_id} week{week_no} (max_allowed_stage={max_allowed_stage})\n{'='*70}")
        t0 = time.time()
        plan_module._run_plan_background(user_id, body, profile, start_date)
        elapsed = time.time() - t0

        usable = is_usable(captured)
        stage = taper_stage_from_status(captured)
        passed = usable and stage <= max_allowed_stage
        results.append((user_id, week_no, elapsed, usable, stage, max_allowed_stage, passed))
        print(f"elapsed={elapsed:.0f}s usable={usable} taper_stage_used={stage} "
              f"(allowed<={max_allowed_stage}) -> {'PASS' if passed else 'FAIL'}")

    print(f"\n\n{'='*70}\nSUMMARY\n{'='*70}")
    all_passed = True
    for user_id, week_no, elapsed, usable, stage, max_allowed, passed in results:
        all_passed = all_passed and passed
        verdict = "PASS" if passed else "FAIL"
        print(f"{user_id:<14} week{week_no}  elapsed={elapsed:6.0f}s  usable={usable!s:5s}  "
              f"stage={stage} (<= {max_allowed})  -> {verdict}")

    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
