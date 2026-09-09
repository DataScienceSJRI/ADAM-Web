"""Shared no-write test fixture for dry-run scripts that exercise
_run_plan_background (or other plan-generation code paths) against real
Supabase reads without ever writing back. Every ad hoc test script this
project has needed so far has hand-rolled the same four fake_write_* stubs
and relied on a manual `grep -n "\\.insert(\\|\\.update(\\|\\.upsert(\\|\\.delete("`
check before running -- this module removes the "did I forget to stub one"
risk by doing it in exactly one place.

Usage:
    import routers.plan as plan_module
    from services.dry_run_testing import stub_all_writes

    captured = stub_all_writes(plan_module)
    plan_module._run_plan_background(user_id, body, profile, start_date)
    menu = captured["menu"]
    status_calls = captured["status_calls"]

This module itself performs zero Supabase writes -- it only monkeypatches
the target module's write-function references to local no-op/capture
functions. Real production writes are untouched; this only affects whatever
module object is passed in for the lifetime of the test script's process.
"""
from __future__ import annotations

from typing import Any, Dict


def stub_all_writes(plan_module: Any) -> Dict[str, Any]:
    """Monkeypatches plan_module's write-function references (and its
    _write_plan_status helper) with capturing no-ops. Returns the `captured`
    dict the stubs write into:
        captured["status_calls"]: list[str] -- every status string passed to
            _write_plan_status, in order.
        captured["menu"]: pd.DataFrame | None -- the weekly_menu passed to
            write_recommendations, if it was called.
        captured["plan_id"]: str -- the fake plan id returned to the caller.
    Call this once per test script, before invoking any plan-generation
    entrypoint on plan_module.
    """
    captured: Dict[str, Any] = {"status_calls": [], "menu": None, "plan_id": "FAKE-PLAN-ID-NOT-WRITTEN"}

    def fake_write_plan_status(onboarding_id, status, plan_id=None):
        captured["status_calls"].append(status)

    def fake_write_recommendations(user_id, weekly_menu, week_no, onboarding_id, start_date):
        captured["menu"] = weekly_menu.copy()
        return len(weekly_menu), captured["plan_id"]

    def fake_write_final_summary(user_id, plan_id, final_summary_df, start_date):
        return 0

    def fake_write_final_nutrient_summary(user_id, plan_id, nutrient_summary_df):
        return 0

    plan_module._write_plan_status = fake_write_plan_status
    plan_module.write_recommendations = fake_write_recommendations
    plan_module.write_final_summary = fake_write_final_summary
    plan_module.write_final_nutrient_summary = fake_write_final_nutrient_summary

    return captured


def is_usable(captured: Dict[str, Any]) -> bool:
    """True if stub_all_writes' captured dict shows a real, non-empty menu
    was produced (mirrors _run_plan_background's own success path)."""
    menu = captured.get("menu")
    return menu is not None and not menu.empty


def was_retried(captured: Dict[str, Any]) -> bool:
    """True if any captured status string indicates the taper-retry fallback
    fired. Prefer reading summary["taper_dropped"] directly when available
    (see run_lp's summary dict) -- this string-matching fallback exists for
    call sites that only have the status_calls list, not the summary dict."""
    return any("retry" in s for s in captured.get("status_calls", []))


def taper_stage_from_status(captured: Dict[str, Any]) -> int:
    """Extracts the highest graduated taper-relaxation stage reached, by
    parsing _run_plan_background's "optimizing (taper relaxation stage N)"
    status messages (see routers/plan.py). Returns 0 if no relaxation was
    needed (full taper solved on the first attempt). This is a test-only
    convenience -- production code should read
    weekly_optimization_summary["taper_stage_used"] directly instead, since
    that's set unconditionally rather than relying on status-string parsing."""
    import re
    stages = [
        int(m.group(1))
        for s in captured.get("status_calls", [])
        if (m := re.search(r"taper relaxation stage (\d+)", s))
    ]
    return max(stages) if stages else 0
