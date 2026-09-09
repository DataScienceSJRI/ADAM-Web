"""Tests for services/portion_profile.py. Reads (never writes) the real
Usual_Portion_Size_Answers Supabase table, so results for the "known
user" cases depend on who has actually filled in the questionnaire —
see the note on test_real_users_classify_as_expected. No LP model run."""
from services.portion_profile import (
    classify_portion_class,
    get_taper_overrides_for_week,
    get_user_portion_answers,
    get_user_portion_class,
    PORTION_1_BOUNDS,
    PORTION_2_BOUNDS,
)


def test_get_user_portion_answers_known_user():
    answers = get_user_portion_answers("A001_MAHENDRA")
    assert answers is not None
    assert "Dosa (number)" in answers
    assert "Dal/Sambar/Curry (cups)" in answers


def test_get_user_portion_answers_strips_whitespace_in_stored_user_id():
    # Live rows have been observed with a stray trailing newline on
    # user_id (e.g. "A002_NASIR\n") -- must still match on the clean id.
    assert get_user_portion_answers("A002_NASIR") is not None


def test_get_user_portion_answers_unknown_user():
    assert get_user_portion_answers("NOT_A_REAL_USER") is None


def test_get_user_portion_class_unknown_user_defaults_to_portion_1():
    # No answers on file -> fall back to the original calendar-only taper
    # (week1 most generous -> week2 moderate -> week3+ default), not an
    # assumption-free "no taper needed".
    assert get_user_portion_class("NOT_A_REAL_USER") == "Portion 1"


def test_classify_portion_class_all_target_amounts_is_portion_3():
    answers = {
        "Dosa (number)": 2, "Idli (number)": 2, "Chapati (number)": 2, "Roti (number)": 2,
        "Rice (cups)": "1 cup", "Millet rice (cups)": "1 cup", "Khichdi (cups)": "1 cup",
        "Pongal (cups)": "1 cup", "Upma (cups)": "1 cup",
        "Dal/Sambar/Curry (cups)": "1 cup", "Vegetable side dish (cups)": "1 cup",
    }
    assert classify_portion_class(answers) == "Portion 3"


def test_classify_portion_class_large_portions_is_portion_1():
    answers = {
        "Dosa (number)": 4, "Idli (number)": 5, "Chapati (number)": 4, "Roti (number)": 4,
        "Rice (cups)": "More than 2 cups", "Millet rice (cups)": "2 cups",
        "Khichdi (cups)": "2 cups", "Pongal (cups)": "2 cups", "Upma (cups)": "2 cups",
        "Dal/Sambar/Curry (cups)": "2+ cups", "Vegetable side dish (cups)": "2+ cups",
    }
    assert classify_portion_class(answers) == "Portion 1"


def test_classify_portion_class_ignores_categories_not_eaten():
    # "Do not eat" for rice must not be treated as ratio 0 (which would
    # pull the average toward Portion 3) -- it should be excluded entirely.
    answers = {
        "Dosa (number)": 2, "Idli (number)": 2, "Chapati (number)": 2, "Roti (number)": 2,
        "Rice (cups)": "Do not eat", "Millet rice (cups)": "1 cup", "Khichdi (cups)": "1 cup",
        "Pongal (cups)": "1 cup", "Upma (cups)": "1 cup",
        "Dal/Sambar/Curry (cups)": "1 cup", "Vegetable side dish (cups)": "1 cup",
    }
    assert classify_portion_class(answers) == "Portion 3"


def test_get_taper_overrides_for_week_portion_3_never_tapers():
    assert get_taper_overrides_for_week("Portion 3", 1) == {}
    assert get_taper_overrides_for_week("Portion 3", 2) == {}
    assert get_taper_overrides_for_week("Portion 3", 3) == {}


def test_get_taper_overrides_for_week_portion_2_tapers_weeks_1_and_2_only():
    assert get_taper_overrides_for_week("Portion 2", 1) == PORTION_2_BOUNDS
    assert get_taper_overrides_for_week("Portion 2", 2) == PORTION_2_BOUNDS
    assert get_taper_overrides_for_week("Portion 2", 3) == {}


def test_get_taper_overrides_for_week_portion_1_steps_down_by_week():
    assert get_taper_overrides_for_week("Portion 1", 1) == PORTION_1_BOUNDS
    assert get_taper_overrides_for_week("Portion 1", 2) == PORTION_2_BOUNDS
    assert get_taper_overrides_for_week("Portion 1", 3) == {}


def test_real_users_classify_as_expected():
    # Snapshot of the real Usual_Portion_Size_Answers table as of
    # 2026-09-08: only A001/A002 have answered so far. A003/A004 have no
    # row yet and are expected to hit the Portion 1 fallback -- once they
    # (or anyone new) answer for real, update this snapshot to match.
    expected = {
        "A001_MAHENDRA": "Portion 3",
        "A002_NASIR": "Portion 1",
        "A003_ANISH": "Portion 1",  # fallback: no answers on file yet
        "A004_RAJAT": "Portion 1",  # fallback: no answers on file yet
    }
    for user_id, expected_class in expected.items():
        assert get_user_portion_class(user_id) == expected_class
