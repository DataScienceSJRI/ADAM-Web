"""Unit tests for the automated plan generation flow.
"""

import pytest
import pandas as pd
from datetime import date, datetime, timezone, timedelta
from unittest.mock import ANY, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from core.auth import get_current_user
from routers.plan import _schedule_next_week_job
from services.plan_worker import run_auto_next_week_job
from services.recommendation_writer import write_recommendations, write_final_summary

TEST_USER = "user@test.com"
BASE = "/api/v1/plan"


def _sb(data=None):
    """Chainable Supabase mock: every chain method returns self; execute() yields .data."""
    m = MagicMock()
    result = MagicMock()
    result.data = [] if data is None else data
    for meth in ("table", "select", "eq", "limit", "update", "delete", "insert", "is_", "in_", "order"):
        getattr(m, meth).return_value = m
    m.not_ = m  # `.not_` is accessed as a property (not called), so alias it to self
    m.execute.return_value = result
    return m


# ─── routers.plan._schedule_next_week_job ─────────────────────────────────────

class TestScheduleNextWeekJob:
    def test_skips_when_no_onboarding_id(self):
        with patch("routers.plan.get_redis") as mock_get_redis:
            _schedule_next_week_job("user-1", None, week_no=1, start_date=date(2026, 7, 12))
        mock_get_redis.assert_not_called()

    def test_schedules_day6_9pm_ist_trigger_and_persists_job_id(self):
        sb = _sb(data=[])
        fake_queue = MagicMock()
        fake_queue.enqueue_at.return_value = MagicMock(id="job-abc")

        with patch("core.supabase.get_supabase", return_value=sb), \
             patch("routers.plan.get_redis", return_value=MagicMock()), \
             patch("routers.plan.Queue", return_value=fake_queue):
            _schedule_next_week_job("user-1", "ob-1", week_no=1, start_date=date(2026, 7, 12))

        args, kwargs = fake_queue.enqueue_at.call_args
        trigger_at_utc, fn_path, user_id, onboarding_id, next_week_no, next_start_iso = args
        assert fn_path == "services.plan_worker.run_auto_next_week_job"
        assert user_id == "user-1"
        assert onboarding_id == "ob-1"
        assert next_week_no == 2
        assert next_start_iso == "2026-07-19"  # start_date (Day1) + 7 days
        # Day 6 of a plan starting 2026-07-12 is 2026-07-17; 21:00 IST == 15:30 UTC
        assert trigger_at_utc == datetime(2026, 7, 17, 15, 30, tzinfo=timezone.utc)

        sb.update.assert_called_once_with({"next_plan_job_id": "job-abc"})

    def test_cancels_previous_scheduled_job_before_scheduling_new_one(self):
        sb = _sb(data=[{"next_plan_job_id": "old-job-1"}])
        fake_queue = MagicMock()
        fake_queue.enqueue_at.return_value = MagicMock(id="new-job-2")
        fake_old_job = MagicMock()

        with patch("core.supabase.get_supabase", return_value=sb), \
             patch("routers.plan.get_redis", return_value=MagicMock()), \
             patch("routers.plan.Queue", return_value=fake_queue), \
             patch("routers.plan.Job") as mock_job_cls:
            mock_job_cls.fetch.return_value = fake_old_job
            _schedule_next_week_job("user-1", "ob-1", week_no=1, start_date=date(2026, 7, 12))

        mock_job_cls.fetch.assert_called_once_with("old-job-1", connection=ANY)
        fake_old_job.cancel.assert_called_once()

    def test_never_raises_when_redis_unavailable(self):
        with patch("routers.plan.get_redis", side_effect=RuntimeError("redis down")):
            _schedule_next_week_job("user-1", "ob-1", week_no=1, start_date=date(2026, 7, 12))  # must not raise


# ─── services.plan_worker.run_auto_next_week_job ──────────────────────────────

class TestRunAutoNextWeekJob:
    def test_sends_notice_then_delegates_to_run_plan_background(self):
        profile = {"age_group_col": "Women_moderate"}
        with patch("services.push.send_push") as mock_push, \
             patch("services.profile_builder.build_profile", return_value=profile) as mock_build, \
             patch("routers.plan._run_plan_background") as mock_run:
            run_auto_next_week_job("user-1", "ob-1", week_no=2, start_date_iso="2026-07-19")

        mock_push.assert_called_once()
        push_kwargs = mock_push.call_args.kwargs
        assert push_kwargs["user_id"] == "user-1"
        assert "next week" in push_kwargs["body"].lower()

        mock_build.assert_called_once_with("user-1", onboarding_id="ob-1")

        mock_run.assert_called_once()
        run_kwargs = mock_run.call_args.kwargs
        assert run_kwargs["user_id"] == "user-1"
        assert run_kwargs["body"].week_no == 2
        assert run_kwargs["body"].onboarding_id == "ob-1"
        assert run_kwargs["profile"] == profile
        assert run_kwargs["start_date"] == date(2026, 7, 19)

    def test_skips_generation_but_still_notifies_when_profile_missing(self):
        with patch("services.push.send_push") as mock_push, \
             patch("services.profile_builder.build_profile", return_value=None), \
             patch("routers.plan._run_plan_background") as mock_run:
            run_auto_next_week_job("user-1", "ob-1", week_no=2, start_date_iso="2026-07-19")

        mock_push.assert_called_once()
        mock_run.assert_not_called()


# ─── services.recommendation_writer start_date anchoring ──────────────────────

class TestWriteRecommendationsStartDate:
    _MENU = pd.DataFrame([
        {"Day": 1, "Recipe_Code": "R1", "Meal_Time": "Breakfast", "Recipe_Name": "Idli", "Serving": 1.0, "Energy_ENERC_Kcal": 150},
        {"Day": 7, "Recipe_Code": "R2", "Meal_Time": "Dinner", "Recipe_Name": "Dal", "Serving": 1.0, "Energy_ENERC_Kcal": 200},
    ])

    def test_day_dates_anchored_to_explicit_start_date(self):
        sb = _sb(data=[])
        with patch("services.recommendation_writer.get_supabase", return_value=sb):
            rows_written, plan_id = write_recommendations(
                user_id="user-1",
                weekly_menu=self._MENU,
                week_no=2,
                onboarding_id="ob-1",
                start_date=date(2026, 7, 19),
            )

        assert rows_written == 2
        assert plan_id
        inserted_rows = sb.insert.call_args.args[0]
        dates = {r["Date"] for r in inserted_rows}
        assert dates == {"2026-07-19", "2026-07-25"}  # Day1 and Day7

    def test_defaults_to_tomorrow_when_start_date_omitted(self):
        sb = _sb(data=[])
        menu = pd.DataFrame([
            {"Day": 1, "Recipe_Code": "R1", "Meal_Time": "Breakfast", "Recipe_Name": "Idli", "Serving": 1.0, "Energy_ENERC_Kcal": 150},
        ])
        with patch("services.recommendation_writer.get_supabase", return_value=sb):
            write_recommendations(user_id="user-1", weekly_menu=menu)

        inserted_rows = sb.insert.call_args.args[0]
        expected = (date.today() + timedelta(days=1)).isoformat()
        assert inserted_rows[0]["Date"] == expected


class TestWriteFinalSummaryStartDate:
    def test_day_dates_anchored_to_explicit_start_date(self):
        sb = _sb(data=[])
        final_summary_df = pd.DataFrame([
            {"Day": 1, "Meal_Time": "Breakfast", "Recipe_Code": "R1"},
            {"Day": 7, "Meal_Time": "Dinner", "Recipe_Code": "R2"},
        ])
        with patch("services.recommendation_writer.get_supabase", return_value=sb):
            rows_written = write_final_summary(
                user_id="user-1",
                plan_id="plan-1",
                final_summary_df=final_summary_df,
                start_date=date(2026, 7, 19),
            )

        assert rows_written == 2
        inserted_rows = sb.insert.call_args.args[0]
        dates = {r["Date"] for r in inserted_rows}
        assert dates == {"2026-07-19", "2026-07-25"}

    def test_matches_write_recommendations_for_same_start_date(self):
        """Both writers must agree on Day 1's date for the same plan, otherwise
        Recommendation and FinalSummary rows for the same plan disagree on dates."""
        start = date(2026, 7, 19)
        sb = _sb(data=[])
        menu = pd.DataFrame([{"Day": 1, "Recipe_Code": "R1", "Meal_Time": "Breakfast", "Recipe_Name": "Idli", "Serving": 1.0, "Energy_ENERC_Kcal": 150}])
        summary_df = pd.DataFrame([{"Day": 1, "Meal_Time": "Breakfast", "Recipe_Code": "R1"}])

        with patch("services.recommendation_writer.get_supabase", return_value=sb):
            write_recommendations(user_id="user-1", weekly_menu=menu, start_date=start)
            reco_date = sb.insert.call_args.args[0][0]["Date"]

            write_final_summary(user_id="user-1", plan_id="plan-1", final_summary_df=summary_df, start_date=start)
            summary_date = sb.insert.call_args.args[0][0]["Date"]

        assert reco_date == summary_date == "2026-07-19"


# ─── DELETE /plan cancels the pending auto-job ────────────────────────────────

@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestDeletePlanCancelsAutoJob:
    def test_cancels_pending_job_and_clears_column(self, client):
        sb = _sb(data=[{"onboarding_id": "ob-1", "next_plan_job_id": "job-99"}])
        fake_job = MagicMock()

        with patch("core.supabase.get_supabase", return_value=sb), \
             patch("routers.plan.get_redis", return_value=MagicMock()), \
             patch("routers.plan.Job") as mock_job_cls:
            mock_job_cls.fetch.return_value = fake_job
            r = client.delete(BASE)

        assert r.status_code == 200
        mock_job_cls.fetch.assert_called_once_with("job-99", connection=ANY)
        fake_job.cancel.assert_called_once()
        sb.update.assert_called_once_with({"next_plan_job_id": None})

    def test_no_pending_job_skips_cancellation(self, client):
        sb = _sb(data=[])
        with patch("core.supabase.get_supabase", return_value=sb), \
             patch("routers.plan.Job") as mock_job_cls:
            r = client.delete(BASE)

        assert r.status_code == 200
        mock_job_cls.fetch.assert_not_called()

    def test_always_deletes_recommendation_rows_for_user(self, client):
        sb = _sb(data=[])
        with patch("core.supabase.get_supabase", return_value=sb):
            r = client.delete(BASE)

        assert r.status_code == 200
        sb.table.assert_any_call("Recommendation")
        sb.delete.assert_called()
