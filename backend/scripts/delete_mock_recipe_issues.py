"""Removes every RecipeDataIssues row seeded by seed_mock_recipe_issues.py
(anything whose description starts with "[MOCK]").

Run from backend/ with the project venv:
    ..\\.adam\\Scripts\\python.exe scripts\\delete_mock_recipe_issues.py
"""
import sys

sys.path.insert(0, ".")
from core.supabase import get_supabase  # noqa: E402

sb = get_supabase()
resp = sb.table("RecipeDataIssues").select("id").like("description", "[MOCK]%").execute()
ids = [r["id"] for r in (resp.data or [])]
if not ids:
    print("No mock rows found.")
else:
    sb.table("RecipeDataIssues").delete().in_("id", ids).execute()
    print(f"Deleted {len(ids)} mock rows: {ids}")
