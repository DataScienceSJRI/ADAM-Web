"""
Computes Glycemic Load (GL) for every recipe flagged ADAM_Recipes == 1 in Rec_ADAM_yes_no.

Formula (matches Functions_Base.build_recipe_master, the source of truth used by
plan.py / lp_optimizer.py):

    Energy_Kcal = Energy_ENERC_KJ / 4.184
    GL = GI_Avg * Carbohydrate_g / 100

GI_Avg is looked up from SubCategory_foods_GI_GL via Recipe.Recipe_Category == Code
(NOT RecipeTagging.Subcategories — that's a separate code and not what the model joins on).

Output columns: Recipe_Code, Recipe_Name, Energy_Kcal, Portion, Recipe_Weight_g, Description, GL, Ingredients
`Ingredients` is a dict of {ingredient_name: "qty unit"} sourced from Recipes_ingredient.
"""

import pandas as pd
from core.supabase import get_supabase

OUT_CSV = "adam_recipes_gl.csv"
OUT_PICKLE = "adam_recipes_gl.pkl"


def fetch_all(table: str, columns: str = "*") -> pd.DataFrame:
    supabase = get_supabase()
    all_rows = []
    batch_size = 1000
    start = 0
    while True:
        resp = (
            supabase.table(table)
            .select(columns)
            .range(start, start + batch_size - 1)
            .execute()
        )
        data = resp.data
        if not data:
            break
        all_rows.extend(data)
        if len(data) < batch_size:
            break
        start += batch_size
    return pd.DataFrame(all_rows)


def build_ingredient_dicts(ing_df: pd.DataFrame, codes: set[str]) -> dict[str, dict]:
    ing_df = ing_df[ing_df["Recipe_Code"].astype(str).str.strip().isin(codes)].copy()

    def fmt_qty(row) -> str:
        qty = row.get("Qty")
        unit = row.get("Unit")
        qty_str = "" if pd.isna(qty) else str(qty)
        unit_str = "" if pd.isna(unit) or not str(unit).strip() else str(unit).strip()
        return f"{qty_str} {unit_str}".strip()

    ing_df["quantity"] = ing_df.apply(fmt_qty, axis=1)

    result: dict[str, dict] = {}
    for code, group in ing_df.groupby("Recipe_Code"):
        result[code] = dict(zip(group["Ingredients"], group["quantity"]))
    return result


def main() -> None:
    # 1. ADAM-flagged recipe codes
    adam_df = fetch_all("Rec_ADAM_yes_no", "Recipe_Code,ADAM_Recipes")
    adam_df = adam_df[adam_df["ADAM_Recipes"].astype(str) == "1"].copy()
    codes = set(adam_df["Recipe_Code"].astype(str).str.strip())
    print(f"ADAM-flagged recipes: {len(codes)}")

    # 2. Tagging table: Recipe name, Portion, Portion weight (g), Description
    tag_df = fetch_all(
        "RecipeTagging",
        "Recipe_Code,\"Recipe Name\",Portion,\"Portion weight (g)\",Description",
    )
    tag_df = tag_df.rename(
        columns={"Recipe Name": "Recipe_Name", "Portion weight (g)": "Recipe_Weight_g"}
    )
    tag_df = tag_df[tag_df["Recipe_Code"].astype(str).str.strip().isin(codes)].copy()

    # 3. Recipe nutrition table: Energy, Carbs, Fibre, Recipe_Category (join key for GI)
    recipe_df = fetch_all(
        "Recipe",
        "Recipe_Code,Recipe_Category,Energy_ENERC_KJ,Carbohydrate_g,TotalDietaryFibre_FIBTG_g",
    )
    recipe_df = recipe_df[recipe_df["Recipe_Code"].astype(str).str.strip().isin(codes)].copy()
    for col in ["Energy_ENERC_KJ", "Carbohydrate_g", "TotalDietaryFibre_FIBTG_g"]:
        recipe_df[col] = pd.to_numeric(recipe_df[col], errors="coerce")
    recipe_df["TotalDietaryFibre_FIBTG_g"] = recipe_df["TotalDietaryFibre_FIBTG_g"].fillna(0)

    # 4. GI lookup by subcategory code
    gi_df = fetch_all("SubCategory_foods_GI_GL", "Code,GI_Avg")
    gi_df["GI_Avg"] = pd.to_numeric(gi_df["GI_Avg"], errors="coerce")
    gi_df = gi_df.dropna(subset=["Code", "GI_Avg"]).drop_duplicates(subset=["Code"])
    gi_df = gi_df.rename(columns={"Code": "Recipe_Category", "GI_Avg": "GI"})

    recipe_df = recipe_df.merge(gi_df, on="Recipe_Category", how="left")

    # 5. Compute Energy_Kcal and GL
    recipe_df["Energy_Kcal"] = recipe_df["Energy_ENERC_KJ"] / 4.184
    # recipe_df["GL"] = (
    #     recipe_df["GI"] * (recipe_df["Carbohydrate_g"] - recipe_df["TotalDietaryFibre_FIBTG_g"])
    # ) / 100.0
    recipe_df["GL"] = (recipe_df["GI"] * recipe_df["Carbohydrate_g"]) / 100.0

    # 6. Ingredient dicts
    ing_df = fetch_all("Recipes_ingredient", "Recipe_Code,Ingredients,Qty,Unit")
    ing_map = build_ingredient_dicts(ing_df, codes)

    # 7. Assemble final dataframe
    final_df = tag_df.merge(
        recipe_df[["Recipe_Code", "Energy_Kcal", "GL"]], on="Recipe_Code", how="left"
    )
    final_df["Ingredients"] = final_df["Recipe_Code"].map(ing_map)

    final_df = final_df[
        [
            "Recipe_Code",
            "Recipe_Name",
            "Energy_Kcal",
            "Portion",
            "Recipe_Weight_g",
            "Description",
            "GL",
            "Ingredients",
        ]
    ].sort_values("Recipe_Code").reset_index(drop=True)

    print(final_df.head())
    print(f"\nTotal recipes: {len(final_df)}")
    print(f"Recipes with GL computed: {final_df['GL'].notna().sum()}")
    print(f"Recipes missing GL (no GI match): {final_df['GL'].isna().sum()}")

    final_df.to_pickle(OUT_PICKLE)
    final_df.to_csv(OUT_CSV, index=False)
    print(f"\nSaved: {OUT_CSV}, {OUT_PICKLE}")


if __name__ == "__main__":
    main()
