"""Unit tests for all recall router endpoints.

Strategy:
  - get_current_user is overridden via FastAPI dependency_overrides → no JWT needed
  - For POST /log and POST /image: log_recall / log_recall_image are patched at
    the router import level so Supabase is never touched.
  - For GET, PUT, DELETE: get_supabase is patched; the _sb() helper returns a
    MagicMock chain where every method returns self and execute() yields .data/.count.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from core.auth import get_current_user

TEST_USER = "user@test.com"
BASE = "/api/v1/recall"


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _auth():
    """Replace JWT auth with a fixed test user for all tests in this module."""
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _sb(data=None, count=None):
    """Return a mock Supabase client where every chain call returns self.

    execute() returns an object with .data and .count set to the supplied values.
    """
    m = MagicMock()
    result = MagicMock()
    result.data = [] if data is None else data
    result.count = count
    for meth in ("table", "select", "eq", "neq", "is_", "in_", "order",
                 "range", "limit", "update", "delete", "insert", "upsert"):
        getattr(m, meth).return_value = m
    m.execute.return_value = result
    return m


# ─── POST /recall/log ─────────────────────────────────────────────────────────

class TestPostRecallLog:
    _BASE_PAYLOAD = {"plan_id": "plan-1", "meal_slot": "breakfast", "did_eat_as_planned": True}

    def test_ate_as_planned_returns_recall_ids(self, client):
        with patch("routers.recall.log_recall", return_value=["id-a", "id-b"]):
            r = client.post(f"{BASE}/log", json=self._BASE_PAYLOAD)
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "recall_ids": ["id-a", "id-b"]}

    def test_changed_multiple_recipes(self, client):
        with patch("routers.recall.log_recall", return_value=["id-c", "id-d"]) as fn:
            r = client.post(f"{BASE}/log", json={
                "plan_id": "plan-1",
                "meal_slot": "lunch",
                "did_eat_as_planned": False,
                "recipe_codes": ["R001", "R002"],
                "actual_quantities": ["0.8", "1.0"],
            })
        assert r.status_code == 200
        kw = fn.call_args.kwargs
        assert kw["recipe_codes"] == ["R001", "R002"]
        assert kw["actual_quantities"] == ["0.8", "1.0"]
        assert kw["did_eat_as_planned"] is False

    def test_skipped_meal_passes_none_codes(self, client):
        with patch("routers.recall.log_recall", return_value=["skip-id"]) as fn:
            r = client.post(f"{BASE}/log", json={
                "plan_id": "plan-1",
                "meal_slot": "dinner",
                "did_eat_as_planned": False,
            })
        assert r.status_code == 200
        kw = fn.call_args.kwargs
        assert kw["recipe_codes"] is None
        assert kw["actual_quantities"] is None

    def test_legacy_single_recipe_field_normalised(self, client):
        with patch("routers.recall.log_recall", return_value=["leg-id"]) as fn:
            client.post(f"{BASE}/log", json={
                "plan_id": "plan-1",
                "meal_slot": "breakfast",
                "did_eat_as_planned": False,
                "recipe_code": "R999",
                "actual_quantity": "1.5",
            })
        kw = fn.call_args.kwargs
        assert kw["recipe_codes"] == ["R999"]
        assert kw["actual_quantities"] == ["1.5"]

    def test_recipe_codes_plural_takes_priority_over_legacy(self, client):
        with patch("routers.recall.log_recall", return_value=["pri-id"]) as fn:
            client.post(f"{BASE}/log", json={
                "plan_id": "plan-1",
                "meal_slot": "breakfast",
                "did_eat_as_planned": False,
                "recipe_code": "OLD",
                "recipe_codes": ["NEW1", "NEW2"],
            })
        assert fn.call_args.kwargs["recipe_codes"] == ["NEW1", "NEW2"]

    def test_user_id_comes_from_token(self, client):
        with patch("routers.recall.log_recall", return_value=["u-id"]) as fn:
            client.post(f"{BASE}/log", json=self._BASE_PAYLOAD)
        assert fn.call_args.kwargs["user_id"] == TEST_USER

    def test_optional_date_forwarded(self, client):
        with patch("routers.recall.log_recall", return_value=["d-id"]) as fn:
            client.post(f"{BASE}/log", json={**self._BASE_PAYLOAD, "date": "2026-06-10"})
        assert fn.call_args.kwargs["date"] == "2026-06-10"

    def test_missing_plan_id_returns_422(self, client):
        r = client.post(f"{BASE}/log", json={"meal_slot": "breakfast", "did_eat_as_planned": True})
        assert r.status_code == 422

    def test_invalid_meal_slot_returns_422(self, client):
        r = client.post(f"{BASE}/log", json={**self._BASE_PAYLOAD, "meal_slot": "brunch"})
        assert r.status_code == 422


# ─── GET /recall ──────────────────────────────────────────────────────────────

class TestGetRecall:
    _ROW = {
        "ID": "r1",
        "Date": "2026-06-01",
        "meal_slot": "breakfast",
        "did_eat_as_planned": True,
        "Food_Name": "Idli",
        "Food_Qty": 1.0,
        "Energy_Kcal": 150,
        "notes": None,
    }

    def test_returns_items_and_total(self, client):
        sb = _sb(data=[self._ROW], count=1)
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.get(BASE)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["food_name"] == "Idli"
        assert body["items"][0]["id"] == "r1"

    def test_empty_results(self, client):
        sb = _sb(data=[], count=0)
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.get(BASE)
        assert r.json() == {"items": [], "total": 0}

    def test_scoped_to_current_user(self, client):
        sb = _sb(data=[], count=0)
        with patch("routers.recall.get_supabase", return_value=sb):
            client.get(BASE)
        eq_calls = [c.args for c in sb.eq.call_args_list]
        assert ("user_id", TEST_USER) in eq_calls

    def test_date_filter_applied(self, client):
        sb = _sb(data=[], count=0)
        with patch("routers.recall.get_supabase", return_value=sb):
            client.get(BASE, params={"date": "2026-06-01"})
        sb.eq.assert_any_call("Date", "2026-06-01")

    def test_meal_slot_filter_applied(self, client):
        sb = _sb(data=[], count=0)
        with patch("routers.recall.get_supabase", return_value=sb):
            client.get(BASE, params={"meal_slot": "lunch"})
        sb.eq.assert_any_call("meal_slot", "lunch")

    def test_default_pagination_range(self, client):
        sb = _sb(data=[], count=0)
        with patch("routers.recall.get_supabase", return_value=sb):
            client.get(BASE)
        # offset=0, limit=20 → range(0, 19)
        sb.range.assert_called_once_with(0, 19)

    def test_custom_pagination_range(self, client):
        sb = _sb(data=[], count=0)
        with patch("routers.recall.get_supabase", return_value=sb):
            client.get(BASE, params={"offset": 10, "limit": 5})
        # offset=10, limit=5 → range(10, 14)
        sb.range.assert_called_once_with(10, 14)

    def test_limit_out_of_bounds_returns_422(self, client):
        r = client.get(BASE, params={"limit": 200})
        assert r.status_code == 422

    def test_negative_offset_returns_422(self, client):
        r = client.get(BASE, params={"offset": -1})
        assert r.status_code == 422


# ─── PUT /recall/{recall_id} ──────────────────────────────────────────────────

class TestPutRecall:
    _ID = "recall-xyz"

    def test_update_notes_returns_ok(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.put(f"{BASE}/{self._ID}", json={"notes": "ate less"})
        assert r.status_code == 200
        assert r.json() == {"status": "updated", "id": self._ID}

    def test_update_food_qty(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.put(f"{BASE}/{self._ID}", json={"food_qty": "0.75"})
        assert r.status_code == 200
        sb.update.assert_called_once_with({"Food_Qty": "0.75"})

    def test_update_did_eat_as_planned(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.put(f"{BASE}/{self._ID}", json={"did_eat_as_planned": False})
        assert r.status_code == 200
        sb.update.assert_called_once_with({"did_eat_as_planned": False})

    def test_multiple_fields_at_once(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.put(f"{BASE}/{self._ID}", json={"notes": "less", "food_qty": "0.5"})
        assert r.status_code == 200
        sb.update.assert_called_once_with({"Food_Qty": "0.5", "notes": "less"})

    def test_no_fields_returns_400(self, client):
        r = client.put(f"{BASE}/{self._ID}", json={})
        assert r.status_code == 400
        assert "No fields" in r.json()["detail"]

    def test_recall_not_found_returns_404(self, client):
        sb = _sb(data=[])
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.put(f"{BASE}/{self._ID}", json={"notes": "x"})
        assert r.status_code == 404

    def test_update_is_user_scoped(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            client.put(f"{BASE}/{self._ID}", json={"notes": "x"})
        eq_calls = [c.args for c in sb.eq.call_args_list]
        assert ("ID", self._ID) in eq_calls
        assert ("user_id", TEST_USER) in eq_calls


# ─── DELETE /recall/{recall_id} ───────────────────────────────────────────────

class TestDeleteRecall:
    _ID = "del-xyz"

    def test_delete_returns_ok(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.delete(f"{BASE}/{self._ID}")
        assert r.status_code == 200
        assert r.json() == {"status": "deleted", "id": self._ID}

    def test_not_found_returns_404(self, client):
        sb = _sb(data=[])
        with patch("routers.recall.get_supabase", return_value=sb):
            r = client.delete(f"{BASE}/{self._ID}")
        assert r.status_code == 404

    def test_delete_is_user_scoped(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            client.delete(f"{BASE}/{self._ID}")
        eq_calls = [c.args for c in sb.eq.call_args_list]
        assert ("ID", self._ID) in eq_calls
        assert ("user_id", TEST_USER) in eq_calls

    def test_delete_calls_delete_not_update(self, client):
        sb = _sb(data=[{"ID": self._ID}])
        with patch("routers.recall.get_supabase", return_value=sb):
            client.delete(f"{BASE}/{self._ID}")
        sb.delete.assert_called_once()
        sb.update.assert_not_called()


# ─── POST /recall/image ───────────────────────────────────────────────────────

class TestPostRecallImage:
    _BASE = {"plan_id": "plan-1", "meal_slot": "breakfast"}

    def test_pre_image_only(self, client):
        with patch("routers.recall.log_recall_image", return_value=("rc-1", "rv-1")) as fn:
            r = client.post(f"{BASE}/image", json={
                **self._BASE,
                "image_url_pre": "https://storage/pre.jpg",
            })
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "recall_id": "rc-1", "review_id": "rv-1"}
        kw = fn.call_args.kwargs
        assert kw["image_url_pre"] == "https://storage/pre.jpg"
        assert kw["image_url_post"] is None

    def test_did_eat_as_planned_forwarded(self, client):
        with patch("routers.recall.log_recall_image", return_value=("rc-p", "rv-p")) as fn:
            r = client.post(f"{BASE}/image", json={
                **self._BASE,
                "image_url_pre": "https://storage/pre.jpg",
                "did_eat_as_planned": True,
            })
        assert r.status_code == 200
        assert fn.call_args.kwargs["did_eat_as_planned"] is True

    def test_did_eat_as_planned_defaults_to_none(self, client):
        with patch("routers.recall.log_recall_image", return_value=("rc-q", "rv-q")) as fn:
            client.post(f"{BASE}/image", json={
                **self._BASE,
                "image_url_pre": "https://storage/pre.jpg",
            })
        assert fn.call_args.kwargs["did_eat_as_planned"] is None

    def test_post_image_only_triggers_upsert_path(self, client):
        with patch("routers.recall.log_recall_image", return_value=("rc-2", "rv-2")) as fn:
            r = client.post(f"{BASE}/image", json={
                **self._BASE,
                "image_url_post": "https://storage/post.jpg",
            })
        assert r.status_code == 200
        kw = fn.call_args.kwargs
        assert kw["image_url_pre"] is None
        assert kw["image_url_post"] == "https://storage/post.jpg"

    def test_both_images_in_one_request(self, client):
        with patch("routers.recall.log_recall_image", return_value=("rc-3", "rv-3")) as fn:
            r = client.post(f"{BASE}/image", json={
                **self._BASE,
                "image_url_pre": "https://storage/pre.jpg",
                "image_url_post": "https://storage/post.jpg",
            })
        assert r.status_code == 200
        kw = fn.call_args.kwargs
        assert kw["image_url_pre"] == "https://storage/pre.jpg"
        assert kw["image_url_post"] == "https://storage/post.jpg"

    def test_user_and_plan_id_forwarded(self, client):
        with patch("routers.recall.log_recall_image", return_value=("rc-4", "rv-4")) as fn:
            client.post(f"{BASE}/image", json={
                **self._BASE,
                "image_url_pre": "https://storage/pre.jpg",
            })
        kw = fn.call_args.kwargs
        assert kw["user_id"] == TEST_USER
        assert kw["plan_id"] == "plan-1"

    def test_meal_slot_snacks_accepted(self, client):
        with patch("routers.recall.log_recall_image", return_value=("rc-5", "rv-5")):
            r = client.post(f"{BASE}/image", json={
                "plan_id": "plan-1",
                "meal_slot": "snacks",
                "image_url_pre": "https://storage/pre.jpg",
            })
        assert r.status_code == 200

    def test_missing_plan_id_returns_422(self, client):
        r = client.post(f"{BASE}/image", json={"meal_slot": "breakfast", "image_url_pre": "url"})
        assert r.status_code == 422

    def test_invalid_meal_slot_returns_422(self, client):
        r = client.post(f"{BASE}/image", json={**self._BASE, "meal_slot": "brunch", "image_url_pre": "url"})
        assert r.status_code == 422
