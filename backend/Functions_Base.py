from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List
import argparse
import json

import numpy as np
import pandas as pd
import math


@dataclass
class PersonalizationConfig:
	workspace_dir: Path
	data_dir_name: str = "Datasets"
	outputs_dir_name: str = "base_outputs"

	@property
	def data_dir(self) -> Path:
		return self.workspace_dir / self.data_dir_name

	@property
	def outputs_dir(self) -> Path:
		return self.workspace_dir / self.outputs_dir_name


class ADAMPersonalizationModel:

	def __init__(self, workspace=None):
		self.workspace = workspace
		self.config = PersonalizationConfig(workspace_dir=Path(workspace or '.'))

	# def load_data(self, profile: Optional[dict] = None) -> dict:
	# 	"""
	# 	Load all required CSVs from the workspace directory into a dictionary of DataFrames.
	# 	Overridden by ModelOptimiser in routers/plan.py → services/data_loader.py (Supabase).
	# 	"""
	# 	# ── Overridden in the web backend ────────────────────────────────────────
	# 	# The ModelOptimiser subclass (routers/plan.py) replaces this with
	# 	# load_data_from_supabase(), which fetches all tables from Supabase instead
	# 	# of local CSV files. The CSV-loading body below is retained for reference
	# 	# and for standalone / local-CSV usage only.
	# 	# ─────────────────────────────────────────────────────────────────────────
	# 	pass
# 		import os
# 		data_dir = os.path.join(self.workspace or '.', 'Datasets')
# 		files = {
# 			'preferences': 'Preference_onboarding.csv',
# 			'subcategories': 'SubCategory.csv',
# 			'recipes': 'Recipes_All_ADAM.csv',
# 			'main1_main2_mapping': 'Main1_Main2_Mapping.csv',
# 			'recipe_tag': 'RecipeTagging_Format_verification_All_ADAM.csv',
# 			'user_recipes': 'USER_Recipes_name_changed.csv',
# 			'ear_100': 'BASE_EAR_100percent.csv',
# 			'tul': 'BASE_TUL.csv',
# 			'sub_category':'SubCategory.csv',
# 			'sub_category_gi_gl': 'SubCategory_foods_GI_GL.xlsx',	
# 			'model': "Data_for_modelling_V1.csv"
# 		}
# 		ds = {}
# 		for key, fname in files.items():
# 			fpath = os.path.join(data_dir, fname)
# 			if os.path.exists(fpath):
# 				# Try utf-8 first, fall back to latin-1 if necessary
# 				try:
# 					if fname.endswith(".csv"):
# 						ds[key] = pd.read_csv(fpath)
# 					elif fname.endswith(".xlsx"):
# 						ds[key] = pd.read_excel(fpath)
# 				except UnicodeDecodeError:
# 					try:
# 						ds[key] = pd.read_csv(fpath, encoding="latin1")
# 					except Exception as exc:
# 						print(f"[WARN] Failed to read {fpath} with latin1: {exc}")
# 						ds[key] = pd.DataFrame()
# 				except Exception as exc:
# 					print(f"[WARN] Failed to read {fpath}: {exc}")
# 					ds[key] = pd.DataFrame()
# 			else:
# 				ds[key] = pd.DataFrame()
#
# 		### do the subset here
# 		# If a user-supplied recipe list exists, subset recipes and recipe_tag to those codes
# 		user_df = ds.get("user_recipes", pd.DataFrame())
# 		user_df = user_df[user_df["Oota recipes"]==1]
# 		if not user_df.empty:
# 			# detect likely code column
# 			code_col = next((c for c in ["Recipe_Code"] if c in user_df.columns), None)
# 			if code_col:
# 				user_codes = set(user_df[code_col].astype(str).str.strip().str.upper())
# 				if user_codes:
# 					# subset recipes
# 					if "Recipe_Code" in ds.get("recipes", pd.DataFrame()).columns:
# 						ds["recipes"] = ds["recipes"][ds["recipes"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(user_codes)].copy()
# 					else:
# 						for rc in ["Recipe code", "RecipeCode"]:
# 							if rc in ds.get("recipes", pd.DataFrame()).columns:
# 								ds["recipes"] = ds["recipes"][ds["recipes"][rc].astype(str).str.strip().str.upper().isin(user_codes)].copy()
# 								break
# 					# subset recipe_tag
# 					if "Recipe_Code" in ds.get("recipe_tag", pd.DataFrame()).columns:
# 						ds["recipe_tag"] = ds["recipe_tag"][ds["recipe_tag"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(user_codes)].copy()
# 					elif "Recipe code" in ds.get("recipe_tag", pd.DataFrame()).columns:
# 						ds["recipe_tag"] = ds["recipe_tag"][ds["recipe_tag"]["Recipe code"].astype(str).str.strip().str.upper().isin(user_codes)].copy()
#
# 		# If profile indicates vegetarian diet, subset recipe_tag and recipes
# 		try:
# 			if profile and isinstance(profile, dict) and str(profile.get("diet_type", "")).strip().lower() == "veg":
# 				rt = ds.get("recipe_tag", pd.DataFrame()).copy()
# 				# Use exact column names per request: 'Vegetarian' and 'Recipe code'
# 				if not rt.empty and "Vegetarian" in rt.columns and "Recipe code" in rt.columns:
# 					# Vegetarian column uses 1/0 values
# 					mask = pd.to_numeric(rt["Vegetarian"], errors="coerce") == 1
# 					rt_sub = rt[mask].copy()
# 					if not rt_sub.empty:
# 						ds["recipe_tag"] = rt_sub
# 						# Subset recipes using exact code columns: 'Recipe code' in tag and 'Recipe_Code' in recipes
# 						if "Recipe code" in rt_sub.columns:
# 							codes = set(rt_sub["Recipe code"].astype(str).str.strip().str.upper().dropna().unique())
# 							if codes:
# 								rec_df = ds.get("recipes", pd.DataFrame())
# 								if not rec_df.empty and "Recipe_Code" in rec_df.columns:
# 									ds["recipes"] = rec_df[rec_df["Recipe_Code"].astype(str).str.strip().str.upper().isin(codes)].copy()
#
# 		except Exception:
# 			# non-fatal: if anything goes wrong leave ds as-is
# 				pass
#
# 		return ds

	def merge_preferences_with_subcategory(self, preferences: pd.DataFrame, subcategories: pd.DataFrame) -> pd.DataFrame:
		"""
		Merge user preferences with subcategory codes and set codeoccurance as MainCategoryCode.
		Ensures sub_category_code is always filled and used for downstream filtering.
		Args:
			preferences: DataFrame from Preference_onboarding.csv (column 'sub_category')
			subcategories: DataFrame from SubCategory.csv (columns 'Code', 'SubCategory', 'MainCategoryCode')
		Returns:
			DataFrame with all original preference columns plus 'sub_category_code' and 'codeoccurance' (MainCategoryCode).
		"""
		preferences = preferences.copy()
		subcategories = subcategories.copy()
		# Normalize sub_category for better matching
		preferences['sub_category_norm'] = preferences['sub_category'].map(self._normalize_text)
		subcategories['SubCategory_norm'] = subcategories['SubCategory'].map(self._normalize_text)
		merged = preferences.merge(
			subcategories[['Code', 'SubCategory', 'SubCategory_norm', 'MainCategoryCode']],
			left_on='sub_category_norm',
			right_on='SubCategory_norm',
			how='left'
		)
		# If still missing, try fuzzy match by removing punctuation and extra spaces
		import re
		def fuzzy_norm(x):
			return re.sub(r'[^a-z0-9]+', '', str(x).lower())
		mask_missing = merged['Code'].isna()
		if mask_missing.any():
			preferences['sub_category_fuzzy'] = preferences['sub_category'].map(fuzzy_norm)
			subcategories['SubCategory_fuzzy'] = subcategories['SubCategory'].map(fuzzy_norm)
			fuzzy_merged = preferences[mask_missing].merge(
				subcategories[['Code', 'SubCategory', 'SubCategory_fuzzy', 'MainCategoryCode']],
				left_on='sub_category_fuzzy',
				right_on='SubCategory_fuzzy',
				how='left'
			)
			for col in ['Code', 'SubCategory', 'MainCategoryCode', 'SubCategory_fuzzy']:
				merged.loc[mask_missing, col] = fuzzy_merged[col].values
		merged['sub_category_code'] = merged['Code']
		merged['codeoccurance'] = merged['MainCategoryCode']
		merged.drop(['Code', 'SubCategory_norm', 'MainCategoryCode', 'SubCategory', 'sub_category_fuzzy'], axis=1, errors='ignore')
		return merged

	@staticmethod
	def _normalize_text(value: object) -> str:
		return " ".join(str(value).strip().lower().split())

	def _infer_dish_bucket(self, row: pd.Series) -> str:
		text = " ".join([
			self._normalize_text(row.get("SubCategory", "")),
			self._normalize_text(row.get("Category", "")),
			self._normalize_text(row.get("Description", "")),
		])
		if any(k in text for k in ["coffee", "tea", "juice", "milk", "smoothie", "buttermilk", "beverage", "soda"]):
			return "Beverage"
		if any(k in text for k in ["chutney", "pickle", "raita", "dal", "sambar", "rasam", "papad", "sauce", "dip", "side"]):
			return "Side"
		if any(k in text for k in ["snack", "chips", "chaat", "nuts", "popcorn", "cookie", "cake", "dessert"]):
			return "Snacks"
		return "Main"

	def _get_main1_main2_map(self, ds: Dict[str, pd.DataFrame]):
		mapping_df = ds.get("main1_main2_mapping", pd.DataFrame()).copy()
		if mapping_df.empty:
			return {}, {}

		normalized_cols = {str(c).strip().lower().replace(" ", "_"): c for c in mapping_df.columns}
		main1_col = normalized_cols.get("main1_code") or normalized_cols.get("main1")
		main2_col = normalized_cols.get("main2_code") or normalized_cols.get("main2")
		optional_col = normalized_cols.get("optional_code") or normalized_cols.get("optional")

		main1_to_main2 = {}
		main1_to_optional = {}
		if main1_col and main2_col:
			df = mapping_df.dropna(subset=[main1_col, main2_col])
			for m1, m2 in zip(df[main1_col], df[main2_col]):
				key = str(m1).strip().upper()
				val = str(m2).strip().upper()
				if key and val:
					main1_to_main2.setdefault(key, set()).add(val)
		if main1_col and optional_col:
			df_opt = mapping_df.dropna(subset=[main1_col, optional_col])
			for m1, opt in zip(df_opt[main1_col], df_opt[optional_col]):
				key = str(m1).strip().upper()
				val = str(opt).strip().upper()
				if key and val:
					main1_to_optional.setdefault(key, set()).add(val)
		return main1_to_main2, main1_to_optional

	def build_recipe_master(self, ds: Dict[str, pd.DataFrame]) -> pd.DataFrame:
		recipes = ds["recipes"].copy()
		tag = ds["recipe_tag"].copy().rename(
			columns={
				"Recipe code": "Recipe_Code",
				"Recipe Name": "Recipe_Name",
			}
		)
		sub = ds["subcategories"].copy()
		sub_gi_gl = ds.get("sub_category_gi_gl", pd.DataFrame()).copy()
		model = ds.get("model", pd.DataFrame()).copy()
		print(sub)
		print(sub_gi_gl)
		keep_tag_cols = [
			"Recipe_Code",
			"Recipe_Name",
			"Code_cooccurence",
			"Subcategories",
			"Breakfast",
			"Lunch",
			"Dinner",
			"Snack",
			"Vegetarian",
			"Non vegetarian",
			"Portion",
			"Description",
		]
		keep_tag_cols = [col for col in keep_tag_cols if col in tag.columns]
		tag = tag[keep_tag_cols].copy()

		recipe_master = recipes.merge(tag, on="Recipe_Code", how="left")
		if "Recipe_Name" not in recipe_master.columns:
			name_x = recipe_master.get("Recipe_Name_x")
			name_y = recipe_master.get("Recipe_Name_y")
			if name_x is not None and name_y is not None:
				recipe_master["Recipe_Name"] = name_x.fillna(name_y)
			elif name_x is not None:
				recipe_master["Recipe_Name"] = name_x
			elif name_y is not None:
				recipe_master["Recipe_Name"] = name_y

		sub = sub.rename(columns={"Code": "Subcategories"})
		if {"Subcategories", "SubCategory", "MainCategoryCode"}.issubset(set(sub.columns)):
			recipe_master = recipe_master.merge(
				sub[["Subcategories", "SubCategory", "MainCategoryCode"]],
				on="Subcategories",
				how="left",
			)

		main_code_raw = recipe_master["MainCategoryCode"] if "MainCategoryCode" in recipe_master.columns else pd.Series(np.nan, index=recipe_master.index)
		fallback_code_raw = recipe_master["Code_cooccurence"] if "Code_cooccurence" in recipe_master.columns else pd.Series(np.nan, index=recipe_master.index)
		main_code = main_code_raw.astype(str).str.strip().replace({"": np.nan, "NAN": np.nan, "nan": np.nan})
		fallback_code = fallback_code_raw.astype(str).str.strip().str.upper().replace({"": np.nan, "NAN": np.nan, "nan": np.nan})
		recipe_master["MainCategoryCode"] = main_code.fillna(fallback_code)

		gi_frames = []
		if not sub_gi_gl.empty:
			sub_gi_gl = sub_gi_gl.rename(columns={"Code": "Recipe_Category"}).copy()
			if "GI_Avg" in sub_gi_gl.columns and "Recipe_Category" in sub_gi_gl.columns:
				gi_by_code = sub_gi_gl[["Recipe_Category", "GI_Avg"]].copy()
				gi_by_code["GI_Avg"] = pd.to_numeric(gi_by_code["GI_Avg"], errors="coerce")
				gi_by_code = gi_by_code.dropna(subset=["Recipe_Category", "GI_Avg"]).drop_duplicates(subset=["Recipe_Category"])
				gi_frames.append(gi_by_code.rename(columns={"GI_Avg": "GI"}))

		if gi_frames:
			gi_final = pd.concat(gi_frames, ignore_index=True)
			gi_final["GI"] = pd.to_numeric(gi_final["GI"], errors="coerce")
			gi_final = gi_final.dropna(subset=["Recipe_Category", "GI"]).groupby("Recipe_Category", as_index=False)["GI"].mean()
			recipe_master = recipe_master.merge(gi_final, on="Recipe_Category", how="left")
		else:
			recipe_master["GI"] = np.nan

		recipe_master["GI"] = pd.to_numeric(recipe_master["GI"], errors="coerce")
		carb_raw = recipe_master["Carbohydrate_g"] if "Carbohydrate_g" in recipe_master.columns else pd.Series(np.nan, index=recipe_master.index)
		recipe_master["Carbohydrate_g"] = pd.to_numeric(carb_raw, errors="coerce")
		# compute Glycemic Load (GL) using available fiber column if present
		if 'TotalDietaryFibre_FIBTG_g' in recipe_master.columns:
			fiber_col = recipe_master['TotalDietaryFibre_FIBTG_g']
		else:
			fiber_col = 0

		recipe_master["GL"] = (recipe_master["GI"] * (recipe_master["Carbohydrate_g"] - fiber_col)) / 100.0

		if not model.empty and {"Subcategories", "Delta_Glucose", "TimeAbove160_pct"}.issubset(set(model.columns)):
			metrics = model[["Subcategories", "Delta_Glucose", "TimeAbove160_pct"]].copy()
			metrics["Subcategories"] = metrics["Subcategories"].astype(str)
			metrics["Delta_Glucose"] = pd.to_numeric(metrics["Delta_Glucose"], errors="coerce")
			metrics["TimeAbove160_pct"] = pd.to_numeric(metrics["TimeAbove160_pct"], errors="coerce")
			metrics["Subcategories"] = metrics["Subcategories"].str.split("+")
			metrics = metrics.explode("Subcategories")
			metrics["Subcategories"] = metrics["Subcategories"].astype(str).str.strip().str.upper()
			metrics = metrics[metrics["Subcategories"] != ""]
			agg = (
				metrics.groupby("Subcategories", as_index=False)
				.agg(
					Avg_Delta_Glucose=("Delta_Glucose", "mean"),
					Avg_TimeAbove160_pct=("TimeAbove160_pct", "mean"),
				)
			)
			recipe_master["Subcategories"] = recipe_master["Subcategories"].astype(str).str.strip().str.upper()
			recipe_master = recipe_master.merge(agg, on="Subcategories", how="left")
		else:
			recipe_master["Avg_Delta_Glucose"] = np.nan
			recipe_master["Avg_TimeAbove160_pct"] = np.nan

		energy_kj_raw = recipe_master["Energy_ENERC_KJ"] if "Energy_ENERC_KJ" in recipe_master.columns else pd.Series(np.nan, index=recipe_master.index)
		energy_kcal_raw = recipe_master["Energy_ENERC_Kcal"] if "Energy_ENERC_Kcal" in recipe_master.columns else pd.Series(np.nan, index=recipe_master.index)
		energy_kj = pd.to_numeric(energy_kj_raw, errors="coerce")
		energy_kcal = pd.to_numeric(energy_kcal_raw, errors="coerce")
		recipe_master["Energy_ENERC_Kcal"] = energy_kcal.fillna(energy_kj / 4.184)
		recipe_master["Energy_ENERC_KJ"] = energy_kj.fillna(recipe_master["Energy_ENERC_Kcal"] * 4.184)

		# --- Ensure canonical nutrient columns exist by matching similar column names
		# This copies numeric values from any matching alternative column names
		import re

		canonical_nutrients = [
			"Energy_ENERC_Kcal", "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
			"CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg",
			"TotalFolatesB9_FOLSUM_mcg", "VB12_mcg", "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg",
			"NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
			"Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg", "PotassiumK_mg", "Cholesterol_mg",
		]

		def _norm_col(s: object) -> str:
			if s is None:
				return ""
			s2 = str(s).lower()
			s2 = re.sub(r"[^a-z0-9]", "", s2)
			return s2

		existing_norm = {col: _norm_col(col) for col in recipe_master.columns}

		for target in canonical_nutrients:
			if target in recipe_master.columns:
				# already present
				continue
			target_norm = _norm_col(target)
			found = None
			# first try exact normalized match, then substring matches
			for col, norm in existing_norm.items():
				if norm == target_norm:
					found = col
					break
			if not found:
				for col, norm in existing_norm.items():
					if target_norm in norm or norm in target_norm:
						found = col
						break
			if found:
				try:
					recipe_master[target] = pd.to_numeric(recipe_master[found], errors="coerce").fillna(0)
				except Exception:
					recipe_master[target] = 0.0

		return recipe_master

	def build_preference_map(self, ds: Dict[str, pd.DataFrame], uid: Optional[str]) -> pd.DataFrame:
		prefs = ds["preferences"].copy()
		sub_ref = ds.get("sub_category", pd.DataFrame()).copy()
		required = {"meal_time", "dish_type", "sub_category"}
		if not required.issubset(set(prefs.columns)):
			raise ValueError("Preference_onboarding.csv must include meal_time, dish_type, sub_category")

		if uid and "UID" in prefs.columns:
			prefs = prefs[prefs["UID"].astype(str).str.strip() == str(uid).strip()].copy()

		prefs = prefs.dropna(subset=["meal_time", "dish_type", "sub_category"]).copy()
		prefs = prefs.reset_index(drop=True)
		prefs["Preference_Row_ID"] = prefs.index + 1
		prefs["meal_time"] = prefs["meal_time"].astype(str).str.strip().str.title()
		prefs["dish_type"] = prefs["dish_type"].astype(str).str.strip().str.title()
		prefs["sub_category"] = prefs["sub_category"].astype(str).str.strip()
		prefs["sub_category_norm"] = prefs["sub_category"].map(self._normalize_text)

		code_set = set()
		if not sub_ref.empty and {"Code", "SubCategory"}.issubset(set(sub_ref.columns)):
			tmp = sub_ref[["Code", "SubCategory"]].dropna().copy()
			tmp["Code"] = tmp["Code"].astype(str).str.strip().str.upper()
			code_set = set(tmp["Code"].values)

		subcat_raw = prefs["sub_category"].astype(str).str.strip().str.upper()
		prefs["sub_category_code"] = subcat_raw.where(subcat_raw.isin(code_set), "")

		return prefs[["Preference_Row_ID", "meal_time", "dish_type", "sub_category", "sub_category_code", "sub_category_norm"]].copy()

	def score_personalization(self, recipe_master: pd.DataFrame, prefs: pd.DataFrame, ds: Dict[str, pd.DataFrame], top_n: int = 10) -> pd.DataFrame:
		print(f"[DEBUG][score_personalization] recipe_master shape: {recipe_master.shape}")
		print(f"[DEBUG][score_personalization] prefs shape: {prefs.shape}")
		rec = recipe_master.copy()
		if rec.empty:
			return rec

		rec["SubCategory"] = rec.get("SubCategory", rec.get("Subcategories", "")).astype(str)
		rec["SubCategory_norm"] = rec["SubCategory"].map(self._normalize_text)
		rec["Subcategories"] = rec.get("Subcategories", "").astype(str)
		rec["Dish_Bucket"] = rec.apply(self._infer_dish_bucket, axis=1)

		meal_flag_map = {
			"Breakfast": "Breakfast",
			"Lunch": "Lunch",
			"Dinner": "Dinner",
			"Snacks": "Snack",
		}
		print(list(rec.columns))
		print(rec.get("SubCategory"))
		print(rec.get("GI"))
		print(rec["Carbohydrate_g"])

		gi_series = pd.to_numeric(rec.get("GI"), errors="coerce")
		carb_series = pd.to_numeric(rec.get("Carbohydrate_g"), errors="coerce")
		gl_series = pd.to_numeric(rec.get("GL"), errors="coerce")
		# determine fiber column (support both American/British spellings)
		if 'TotalDietaryFibre_FIBTG_g' in rec.columns:
			fiber_series = pd.to_numeric(rec.get('TotalDietaryFibre_FIBTG_g'), errors='coerce')
		else:
			fiber_series = 0

		if gl_series.notna().sum() == 0:
			# subtract fiber from carbs before GL calculation; avoid negatives
			carb_minus_fiber = carb_series - fiber_series
			if isinstance(carb_minus_fiber, pd.Series):
				carb_minus_fiber = carb_minus_fiber.clip(lower=0)
			else:
				carb_minus_fiber = max(0, carb_minus_fiber)
			gl_series = (gi_series * carb_minus_fiber) / 100.0

		if gl_series.notna().any():
			gl_filled = gl_series.fillna(gl_series.median())
			gl_score = 1.0 - ((gl_filled - gl_filled.min()) / (gl_filled.max() - gl_filled.min() + 1e-9))
		else:
			return("NO gl info available")
			# No GL information available at all — assign an extreme high GL so
			# these recipes are treated as very high-GL by default and
			# give them neutral score (0.5) for downstream ranking.
			gl_filled = pd.Series(99999.0, index=rec.index, dtype=float)
			gl_score = pd.Series(0.5, index=rec.index, dtype=float)
		rec["GL"] = gl_filled
		rec["GL_SubCategory_Score"] = gl_score
		rec["GL_SubCategory"] = gl_filled ##jawa
		rec["GI_SubCategory_Score"] = gl_score

		delta_series = pd.to_numeric(rec.get("Avg_Delta_Glucose"), errors="coerce")
		if delta_series.notna().any():
			delta_filled = delta_series.fillna(delta_series.median())
			delta_score = 1.0 - ((delta_filled - delta_filled.min()) / (delta_filled.max() - delta_filled.min() + 1e-9))
		else:
			return("NO delta glucose info available")

			# No delta glucose info — set an extreme placeholder so these
			# recipes don't inadvertently get favored; score remains neutral.
			delta_filled = pd.Series(99999.0, index=rec.index, dtype=float)
			delta_score = pd.Series(0.5, index=rec.index, dtype=float)
		rec["Avg_Delta_Glucose"] = delta_filled
		rec["Delta_Glucose_Score"] = delta_score

		t160_series = pd.to_numeric(rec.get("Avg_TimeAbove160_pct"), errors="coerce")
		if t160_series.notna().any():
			t160_filled = t160_series.fillna(t160_series.median())
			t160_score = 1.0 - ((t160_filled - t160_filled.min()) / (t160_filled.max() - t160_filled.min() + 1e-9))
		else:
			return("NO TimeAbove160 info available")
			# No TimeAbove160 info — use extreme placeholder to avoid giving
			# these recipes an artificially good score; keep score neutral.
			t160_filled = pd.Series(99999.0, index=rec.index, dtype=float)
			t160_score = pd.Series(0.5, index=rec.index, dtype=float)
		rec["Avg_TimeAbove160_pct"] = t160_filled
		rec["TimeAbove160_Score"] = t160_score

		combo_rows = []
		main1_to_main2, main1_to_optional = self._get_main1_main2_map(ds)

		print(f"[DEBUG][score_personalization] main1_to_main2 mapping: {main1_to_main2}")
		print(f"[DEBUG][score_personalization] main1_to_optional mapping: {main1_to_optional}")
		print("///////////-----------------------------")
		print(main1_to_main2)
		print(main1_to_optional)
		print(prefs)
		if not prefs.empty:
			for _, pref in prefs.iterrows():
				pref_row_id = int(pref.get("Preference_Row_ID", 0))
				meal_time = str(pref["meal_time"]).strip().title()
				dish_type = str(pref["dish_type"]).strip().title()
				subcat = str(pref["sub_category"]).strip()
				subcat_code = str(pref.get("sub_category_code", "")).strip().upper()
				codeoccurance = str(pref.get("codeoccurance", "")).strip().upper()
				print(f"[DEBUG] Processing preference {pref_row_id}: meal_time={meal_time}, dish_type={dish_type}, subcat_code={subcat_code}")
				combo_rows.append({
					"Preference_Row_ID": pref_row_id,
					"Meal_Time": meal_time,
					"Dish_Type": dish_type,
					"Preferred_SubCategory": subcat,
					"Preferred_SubCategory_code": subcat_code,
				})
				if dish_type == "Main":
					main1_code = codeoccurance or subcat_code or subcat.strip().upper()
					# Add Main2 if present in mapping
					for m2 in main1_to_main2.get(main1_code, set()):
						combo_rows.append({
							"Preference_Row_ID": pref_row_id,
							"Meal_Time": meal_time,
							"Dish_Type": "Main 2",
							"Preferred_SubCategory": m2,
							"Preferred_SubCategory_code": m2,
						})
					# Add Optional as sides for this Main
					for opt in main1_to_optional.get(main1_code, set()):
						combo_rows.append({
							"Preference_Row_ID": pref_row_id,
							"Meal_Time": meal_time,
							"Dish_Type": "Side",
							"Preferred_SubCategory": opt,
							"Preferred_SubCategory_code": opt,
						})

		print(f"[DEBUG][score_personalization] combo_rows contents: {combo_rows}")
		combos = pd.DataFrame(combo_rows).drop_duplicates().reset_index(drop=True)

		all_rows = []
		for _, combo in combos.iterrows():
			print(f"[DEBUG][score_personalization] Combo: {combo.to_dict()}")
			pref_row_id = int(combo.get("Preference_Row_ID", 0))
			meal_time = str(combo["Meal_Time"]).strip().title()
			dish_type = str(combo["Dish_Type"]).strip().title()
			# Use the preferred subcategory CODE as the primary matching key
			preferred_code_upper = str(combo.get("Preferred_SubCategory_code", "")).strip().upper()
			# keep a readable subcat field but prefer the code for matching
			subcat = preferred_code_upper or str(combo.get("Preferred_SubCategory", "")).strip()
			subcat_norm = self._normalize_text(subcat)

			main_data = rec.copy()

			family_code = preferred_code_upper[:2] if len(preferred_code_upper) >= 2 else preferred_code_upper
			preferred_cooc_code = family_code

			def _exact_mask(df: pd.DataFrame) -> pd.Series:
				return (
					(df["SubCategory_norm"] == subcat_norm)
					| (df["Subcategories"].astype(str).str.strip().str.upper() == preferred_code_upper)
					| (df.get("MainCategoryCode", "").astype(str).str.strip().str.upper() == preferred_code_upper)
					| (df.get("Code_cooccurence", "").astype(str).str.strip().str.upper() == preferred_code_upper)
				)

			def _cooc_mask(df: pd.DataFrame) -> pd.Series:
				if not preferred_cooc_code:
					return pd.Series(False, index=df.index)
				return (
					(df.get("Code_cooccurence", "").astype(str).str.strip().str.upper() == preferred_cooc_code)
					| (df.get("MainCategoryCode", "").astype(str).str.strip().str.upper() == preferred_cooc_code)
				)

			def _score_frame(df: pd.DataFrame, source_label: str) -> pd.DataFrame:
				if df.empty:
					return df
				tmp = df.copy()
				tmp["Preference_Match"] = _exact_mask(tmp).astype(float)
				tmp["Personalization_Score"] = (
					0.1 * tmp["Preference_Match"]
					- 0.7 * tmp["GL_SubCategory"] ##jawa
					+ 0.1 * tmp["Delta_Glucose_Score"]
					+ 0.1 * tmp["TimeAbove160_Score"]
				)
				tmp["Source"] = source_label
				return tmp.sort_values("Personalization_Score", ascending=False)

			limit = max(1, int(top_n))

			selected_codes = set()
			selected_frames = []

			exact_subset = main_data[_exact_mask(main_data)].copy()
			print(f"[DEBUG][score_personalization] exact_subset shape: {exact_subset.shape}")
			exact_subset = _score_frame(exact_subset, "exact_preference")
			if not exact_subset.empty:
				exact_subset = exact_subset.drop_duplicates(subset=["Recipe_Code"]).head(limit).copy()
				selected_frames.append(exact_subset)
				selected_codes.update(exact_subset["Recipe_Code"].astype(str).tolist())

			if sum(len(x) for x in selected_frames) < limit:
				remaining = limit - sum(len(x) for x in selected_frames)
				cooc_subset = main_data[_cooc_mask(main_data)].copy()
				print(f"[DEBUG][score_personalization] cooc_subset shape: {cooc_subset.shape}")
				cooc_subset = _score_frame(cooc_subset, "fallback_code_cooccurence")
				if not cooc_subset.empty:
					cooc_subset = cooc_subset[~cooc_subset["Recipe_Code"].astype(str).isin(selected_codes)].copy()
					cooc_subset = cooc_subset.drop_duplicates(subset=["Recipe_Code"]).head(remaining).copy()
					if not cooc_subset.empty:
						selected_frames.append(cooc_subset)
						selected_codes.update(cooc_subset["Recipe_Code"].astype(str).tolist())

			pool = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
			print(f"[DEBUG][score_personalization] pool shape: {pool.shape}")

			if pool.empty:
				continue

			pool["Preference_Row_ID"] = pref_row_id
			pool["Meal_Time"] = meal_time
			pool["Dish_Type"] = dish_type
			# Store both but ensure Preferred_SubCategory holds the code for consistency
			pool["Preferred_SubCategory"] = preferred_code_upper
			pool["Preferred_SubCategory_code"] = preferred_code_upper
			all_rows.append(pool)

		if not all_rows:
			return pd.DataFrame()

		out = pd.concat(all_rows, ignore_index=True)
		out = out.sort_values(["Preference_Row_ID", "Meal_Time", "Dish_Type", "Preferred_SubCategory_code", "Personalization_Score"], ascending=[True, True, True, True, False]).reset_index(drop=True)
		out.to_csv("personalization_scoring_debug.csv", index=False)	
		return out


	def _get_weekly_requirement_maps(
		self,
		ds: Dict[str, pd.DataFrame],
		age_group_col: str,
		n_days: int,
		profile: Optional[dict] = None,
	) -> Tuple[Dict[str, float], Dict[str, float], Optional[float]]:
		ear = ds.get("ear_100", pd.DataFrame()).copy()
		tul = ds.get("tul", pd.DataFrame()).copy()

		nutrient_name_candidates = [c for c in ["Nutrients_name"] if c in ear.columns]
		if not nutrient_name_candidates or age_group_col not in ear.columns:
			return {}, {}, None

		name_col = nutrient_name_candidates[0]

		def _norm(s: object) -> str:
			return self._normalize_text(s).replace("_", "").replace(" ", "")

		recipe_to_ear_name = {
			"Energy_ENERC_Kcal": "Energy",
			"Protein_PROTCNT_g": "Protein",
			"TotalFat_FATCE_g": "Fat",
			"TotalDietaryFibre_FIBTG_g": "Dietary_Fibre",
			"CalciumCa_CA_mg": "Calcium",
			"ZincZn_ZN_mg": "Zinc",
			"IronFe_FE_mg": "Iron",
			"MagnesiumMg_MG_mg": "Magnesium",
			"VA_RAE_mcg": "VA",
			"TotalFolatesB9_FOLSUM_mcg": "Folate",
			"VB12_mcg": "VB12",
			"ThiamineB1_THIA_mg": "VB1",
			"RiboflavinB2_RIBF_mg": "VB2",
			"NiacinB3_NIA_mg": "VB3",
			"TotalB6A_VITB6A_mg": "VB6",
			"TotalAscorbicAcid_VITC_mg": "VC",
		}



		ear_lookup: Dict[str, float] = {}
		for _, row in ear.iterrows():
			v = pd.to_numeric(row.get(age_group_col), errors="coerce")
			if pd.isna(v):
				continue
			ear_lookup[_norm(row.get(name_col))] = float(v)

		weekly_min: Dict[str, float] = {}
		for col, ear_name in recipe_to_ear_name.items():
			key = _norm(ear_name)
			if key in ear_lookup:
				weekly_min[col] = float(ear_lookup[key]) * float(n_days)

		daily_energy_kcal = None
		if "Energy_ENERC_Kcal" in weekly_min:
			daily_energy_kcal = weekly_min["Energy_ENERC_Kcal"] / float(n_days)

		weekly_max: Dict[str, float] = {}
		if not tul.empty and age_group_col in tul.columns:
			tul_name_col_candidates = [c for c in ["Nutrients_name"] if c in tul.columns]
			if tul_name_col_candidates:
				tul_name_col = tul_name_col_candidates[0]
				tul_lookup: Dict[str, float] = {}
				for _, row in tul.iterrows():
					v = pd.to_numeric(row.get(age_group_col), errors="coerce")
					if pd.isna(v):
						continue
					tul_lookup[_norm(row.get(tul_name_col))] = float(v)
				for col, ear_name in recipe_to_ear_name.items():
					key = _norm(ear_name)
					if key in tul_lookup:
						weekly_max[col] = float(tul_lookup[key]) * float(n_days)
				if "Energy_ENERC_Kcal" in weekly_max:
					del weekly_max["Energy_ENERC_Kcal"]

		return weekly_min, weekly_max, daily_energy_kcal

	# def optimize_weekly_menu_with_constraints(
	# 	self,
	# 	meal_choices: pd.DataFrame,
	# 	ds: Dict[str, pd.DataFrame],
	# 	age_group_col: str,
	# 	n_days: int = 7,
	# 	weekly_rep: int = 3,
	# 	category_weekly_rep: Optional[int] = 4,
	# 	non_snack_serving_bounds: Tuple[float, float] = (0.5, 1),
	# 	snack_serving_bounds: Tuple[float, float] = (0.5, 1.0),
	# 	time_limit_sec: int = 120,
	# 	# GL-related caps (optional): per-meal, per-day, and per-recipe maximum
	# 	per_meal_gl_cap: Optional[float] = 40,
	# 	per_day_gl_cap: Optional[float] = None,
	# 	per_recipe_max_gl: Optional[float] = 40,
	# 	# Optional explicit dataframes (prefer these over `ds` keys when provided)
	# 	recipe_ing_df: Optional[pd.DataFrame] = None,
	# 	main1_main2_mapping: Optional[pd.DataFrame] = None,
	# 	ear_100: Optional[pd.DataFrame] = None,
	# 	tul: Optional[pd.DataFrame] = None,
	# 	profile: Optional[Dict[str, object]] = None,
	# ) -> Tuple[pd.DataFrame, Dict[str, object]]:
	# 	# ── Overridden in the web backend ────────────────────────────────────────
	# 	# The ModelOptimiser subclass (routers/plan.py) replaces this with
	# 	# services/lp_optimizer.run_lp(), which removes the hard macronutrient %
	# 	# constraints (carbs 45-50%) that make this LP infeasible.
	# 	# The LP body below is retained for reference and standalone usage only.
	# 	# ─────────────────────────────────────────────────────────────────────────
	# 	pass
# 		if profile is None:
# 			raise ValueError("profile is required for optimize_weekly_menu_with_constraints")
# 		try:
# 			from pulp import LpProblem, LpMinimize, LpVariable, lpSum, PULP_CBC_CMD, LpStatus, value
# 		except Exception as exc:
# 			return pd.DataFrame(), {"status": "missing_pulp", "error": str(exc)}
#
# 		if meal_choices.empty:
# 			return pd.DataFrame(), {"status": "no_candidates"}
#
# 		# Use set-based mapping for Main1→Main2. Prefer explicit mapping if provided.
# 		if main1_main2_mapping is not None:
# 			main1_to_main2, main1_to_optional = self._get_main1_main2_map({'main1_main2_mapping': main1_main2_mapping})
# 		else:
# 			main1_to_main2, main1_to_optional = self._get_main1_main2_map(ds)
#
# 		candidates = meal_choices.copy()#.sort_values("Personalization_Score", ascending=False)
# 		# Preserve candidates per preference — include Preference_Row_ID in duplicate subset
# 		dedup_subset = ["Meal_Time", "Dish_Type", "Recipe_Code", "Preference_Row_ID"]
# 		candidates = candidates.drop_duplicates(subset=dedup_subset).reset_index(drop=True)
# 		if candidates.empty:
# 			return pd.DataFrame(), {"status": "no_candidates"}
#
# 		# Keep only required columns: Recipe_Category, Code_cooccurence, Preference_Row_ID, Meal_Time, Dish_Type, and nutrient columns
# 		required_cols = [
# 			"Recipe_Code","Recipe_Name","Recipe_Category", "Code_cooccurence", "Preferred_SubCategory_code", "Preference_Row_ID", "Meal_Time", "Dish_Type",
# 			"GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose", "Energy_ENERC_Kcal", "Energy_ENERC_KJ",
# 			"Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g", "CalciumCa_CA_mg", "ZincZn_ZN_mg",
# 			"IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg", "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg",
# 			"ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg", "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
# 			"Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg","PotassiumK_mg","Cholesterol_mg"
# 		]
# 		# Only keep columns that exist in candidates
# 		keep_cols = [col for col in required_cols if col in candidates.columns]
# 		candidates = candidates[keep_cols].copy()
# 		candidates = candidates.drop_duplicates().reset_index(drop=True)
#
# 		# Normalize dish type and identifiers to avoid grouping mismatches
# 		candidates["Dish_Type"] = candidates["Dish_Type"].astype(str).str.strip()
# 		candidates["Preference_Row_ID"] = candidates["Preference_Row_ID"].astype(str).str.strip()
# 		candidates["Meal_Time"] = candidates["Meal_Time"].astype(str).str.strip()
#
# 		candidates["Main_Category_code"] = (
# 			candidates.get("MainCategoryCode", candidates.get("Code_cooccurence", ""))
# 			.astype(str)
# 			.str.strip()
# 			.str.upper()
# 		)
# 		# Main2_Target_code assignment diagnostics
# 		# Auto-fill missing Main2 and Side codes using mapping from Main1
#
# 		if "Category" in candidates.columns:
# 			candidates["Category_Key"] = candidates["Category"].astype(str).str.strip()
# 		elif "SubCategory" in candidates.columns:
# 			candidates["Category_Key"] = candidates["SubCategory"].astype(str).str.strip()
# 		elif "Subcategories" in candidates.columns:
# 			candidates["Category_Key"] = candidates["Subcategories"].astype(str).str.strip()
# 		else:
# 			candidates["Category_Key"] = ""
# 		candidates["Category_Key"] = candidates["Category_Key"].replace({"": np.nan})
#
# 		nutrient_cols = [
# 			"Energy_ENERC_Kcal", "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
# 			"CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg",
# 			"TotalFolatesB9_FOLSUM_mcg", "VB12_mcg", "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg",
# 			"NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
# 			"Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg","PotassiumK_mg","Cholesterol_mg"
# 		]
# 		for col in nutrient_cols:
# 			if col in candidates.columns:
# 				candidates[col] = pd.to_numeric(candidates[col], errors="coerce").fillna(0)
#
# 		energy_kj_raw = candidates["Energy_ENERC_KJ"] if "Energy_ENERC_KJ" in candidates.columns else pd.Series(np.nan, index=candidates.index)
# 		energy_kcal_raw = candidates["Energy_ENERC_Kcal"] if "Energy_ENERC_Kcal" in candidates.columns else pd.Series(np.nan, index=candidates.index)
# 		energy_kj = pd.to_numeric(energy_kj_raw, errors="coerce")
# 		energy_kcal = pd.to_numeric(energy_kcal_raw, errors="coerce")
# 		candidates["Energy_ENERC_Kcal"] = energy_kcal.fillna(energy_kj / 4.184).fillna(0)
# 		candidates["Energy_ENERC_KJ"] = energy_kj.fillna(candidates["Energy_ENERC_Kcal"] * 4.184).fillna(0)
#
# 		required_obj_cols = ["GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]
# 		missing_obj_cols = [col for col in required_obj_cols if col not in candidates.columns]
# 		if missing_obj_cols:
# 			raise ValueError(f"Missing required objective columns: {missing_obj_cols}")
# 		for col in required_obj_cols:
# 			candidates[col] = pd.to_numeric(candidates[col], errors="coerce")
# 		# Fill missing objective columns with sensible defaults instead of dropping rows.
# 		# This ensures Main/Main2 candidate pairs aren't removed due to a missing metric.
# 		# For GL, use the median if available otherwise a small default; for the model metrics use 0.0.
# 		if candidates["GL"].isna().any():
# 			gl_median = candidates["GL"].median()
# 			if pd.isna(gl_median):
# 				gl_median = 10.0
# 			candidates["GL"] = candidates["GL"].fillna(gl_median)
# 		for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
# 			if candidates[col].isna().any():
# 				candidates[col] = candidates[col].fillna(0.0)
#
# 		# Compute z-scores for observed metrics only
# 		for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
# 			mean_val = float(candidates[col].mean())
# 			std_val = float(candidates[col].std(ddof=0))
# 			if std_val <= 1e-12:
# 				candidates[f"{col}_z"] = 0.0
# 			else:
# 				candidates[f"{col}_z"] = (candidates[col] - mean_val) / std_val
#
# 		# Use raw GL, z-scores for the other two
# 		candidates["Weighted_Objective_Score"] = (
# 			500 * candidates["GL"]
# 			+ 0.3 * candidates["Avg_TimeAbove160_pct_z"]
# 			+ 0.2 * candidates["Avg_Delta_Glucose_z"]
# 		)
# 		objective_metric_col = "Weighted_Objective_Score"
#
# 		required_slots = (
# 			candidates[["Meal_Time", "Dish_Type"]]
# 			.dropna()
# 			.drop_duplicates()
# 			.reset_index(drop=True)
# 		)
# 		if required_slots.empty:
# 			return pd.DataFrame(), {"status": "no_slots"}
#
# 		# Build a minimal dict for weekly requirement maps; prefer explicit ear/tul if provided
# 		req_ds = {}
# 		if ear_100 is not None:
# 			req_ds['ear_100'] = ear_100
# 		else:
# 			req_ds['ear_100'] = ds.get('ear_100', pd.DataFrame())
# 		if tul is not None:
# 			req_ds['tul'] = tul
# 		else:
# 			req_ds['tul'] = ds.get('tul', pd.DataFrame())
# 		weekly_min, weekly_max, daily_energy_kcal = self._get_weekly_requirement_maps(req_ds, age_group_col=age_group_col, n_days=n_days, profile=profile)
# 		# Compute effective daily energy requirement (`eff_daily`) and the
# 		# upper multiplier (`upper_mult`) once, based on the profile. This
# 		# keeps the energy logic centralized and avoids recomputing later.
# 		eff_daily = None
# 		upper_mult = 1.2  # default maximum multiplier for daily energy
# 		try:
# 			if daily_energy_kcal is not None:
# 				eff_daily = float(daily_energy_kcal)
# 				# Apply BMI reduction first
# 				if profile is not None:
# 					_bmi = profile.get("bmi")
# 					if _bmi is not None:
# 						try:
# 							_bmi_val = float(_bmi)
# 							if _bmi_val >= 25.0:
# 								eff_daily = eff_daily *1 ### 0.8 ####Jawa
# 						except Exception:
# 							pass
# 				# Apply age-based reductions on top of BMI adjustment
# 				if profile is not None:
# 					_age = profile.get("age")
# 					if _age is not None:
# 						try:
# 							_age_val = float(_age)
# 							if _age_val > 60:
# 								eff_daily = eff_daily * 1 ### 0.9 ####Jawa
# 							elif _age_val > 50:
# 								eff_daily = eff_daily * 1 ### 0.95 ####Jawa
# 						except Exception:
# 							pass
# 		except Exception:
# 			# non-fatal; leave eff_daily as None so downstream code can skip
# 			pass
#
# 		# Slot -> candidate indices mapping will be (re)built after index normalization below
# 		slot_to_ids: Dict[Tuple[str, str], List[int]] = {}
#
# 		print(f"[DEBUG] Number of candidates: {len(candidates)}")
# 		print(f"[DEBUG] Required slots:\n{required_slots}")
# 		print(f"[DEBUG] Slot to IDs mapping:\n{slot_to_ids}")
#
# 		# Profile (external) available for use in constraints/selection
# 		if profile is not None:
# 			print(f"[DEBUG] Profile: {profile}")
#
# 		#### model starts 
# 		# Defensive preprocessing: ensure integer 0-based index and numeric objective column
# 		candidates = candidates.reset_index(drop=True)
# 		# ensure objective metric exists and is numeric
# 		if objective_metric_col not in candidates.columns:
# 			candidates[objective_metric_col] = 0.0
# 		else:
# 			candidates[objective_metric_col] = pd.to_numeric(candidates[objective_metric_col], errors="coerce")
# 			if candidates[objective_metric_col].isna().all():
# 				candidates[objective_metric_col] = 0.0
# 			else:
# 				med = candidates[objective_metric_col].median()
# 				candidates[objective_metric_col] = candidates[objective_metric_col].fillna(med)
#
# 		candidates.to_csv("candidates_debug.csv", index=False)
#
# 		# --- Sugar and salt aggregation: compute grams per standard serving per recipe
# 		# Prefer explicit `recipe_ing_df` parameter; otherwise fall back to `ds` lookup.
# 		# If ingredient data is unavailable, default sugar/salt per serving to 0.0.
# 		if recipe_ing_df is not None and isinstance(recipe_ing_df, pd.DataFrame) and not recipe_ing_df.empty:
# 			rig_df = recipe_ing_df.copy()
# 		else:
# 			rig = ds.get('recipe_ing') or ds.get('recipe_ing_db') or ds.get('recipe_ingredients')
# 			if isinstance(rig, pd.DataFrame) and not rig.empty:
# 				rig_df = rig.copy()
# 			else:
# 				rig_df = pd.DataFrame()
#
# 		if not rig_df.empty:
# 			rig_df['Ing_raw_amounts_g'] = pd.to_numeric(rig_df.get('Ing_raw_amounts_g', 0), errors='coerce')
# 			rig_valid = rig_df.dropna(subset=['Ing_raw_amounts_g', 'Food Group']).copy()
# 			# normalize food group labels
# 			rig_valid['Food Group'] = rig_valid['Food Group'].astype(str).str.strip().str.lower()
# 			# Sugar per serving (grams)
# 			sugars = (
# 				rig_valid.loc[rig_valid['Food Group'] == 'sugars']
# 				.groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
# 				.sum()
# 				.rename('Sugar_per_serving_g')
# 			)
# 			if not sugars.empty:
# 				sug_df = sugars.reset_index()
# 				candidates = candidates.merge(sug_df, on='Recipe_Code', how='left')
# 			else:
# 				candidates['Sugar_per_serving_g'] = 0.0
#
# 			# Salt per serving (grams) — prefer Ingredients text, otherwise detect Food Group
# 			if 'Ingredients' in rig_df.columns:
# 				mask_salt = rig_df['Ingredients'].astype(str).str.contains(r"\bSalt\b", case=False, na=False)
# 				salt_series = (
# 					rig_df.loc[mask_salt]
# 					.groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
# 					.sum()
# 					.rename('Salt_per_serving_g')
# 				)
# 			else:
# 				mask_salt = rig_valid['Food Group'].astype(str).str.contains('salt', case=False, na=False)
# 				salt_series = (
# 					rig_valid.loc[mask_salt]
# 					.groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
# 					.sum()
# 					.rename('Salt_per_serving_g')
# 				)
# 			if not salt_series.empty:
# 				salt_df = salt_series.reset_index()
# 				candidates = candidates.merge(salt_df, on='Recipe_Code', how='left')
# 			else:
# 				candidates['Salt_per_serving_g'] = 0.0
# 		else:
# 			# no ingredient data available — default sugar and salt to zero
# 			candidates['Sugar_per_serving_g'] = 0.0
# 			candidates['Salt_per_serving_g'] = 0.0
#
# 		# Apply optional per-recipe GL filter (drop very high-GL recipes entirely)
# 		if per_recipe_max_gl is not None:
# 			try:
# 				_per = float(per_recipe_max_gl)
# 				candidates = candidates[pd.to_numeric(candidates.get("GL", 0), errors="coerce") <= _per].reset_index(drop=True)
# 			except Exception:
# 				# if conversion fails, ignore the filter
# 				pass
#
# 		# Rebuild slot -> ids mapping now that indices are stable (0..N-1)
# 		slot_to_ids = {}
# 		for idx, row in candidates.iterrows():
# 			slot_to_ids.setdefault((str(row["Meal_Time"]), str(row["Dish_Type"])), []).append(int(idx))
#
# 		print(f"[DEBUG] Rebuilt slot_to_ids after index reset: {slot_to_ids}")
#
# 		days = list(range(1, int(n_days) + 1))
# 		model = LpProblem("weekly_menu_min_weighted_gl_time_delta", LpMinimize)
#
# 		y = {}
# 		x = {}
# 		for d in days:
# 			for idx, _ in candidates.iterrows():
# 				i = int(idx)
# 				y[(d, i)] = LpVariable(f"y_d{d}_r{i}", lowBound=0, upBound=1, cat="Binary")
# 				x[(d, i)] = LpVariable(f"x_d{d}_r{i}", lowBound=0)
# 		model += lpSum(float(candidates.loc[i, objective_metric_col]) * x[(d, int(i))] for d in days for i in candidates.index)
#
# 		for d in days:
# 			for _, slot_row in required_slots.iterrows():
# 				slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
# 				ids = slot_to_ids.get(slot, [])
# 				if not ids:
# 					continue
# 				dtype = str(slot_row["Dish_Type"]).strip()
# 				# Make certain dish types optional with upper bounds; other required slots remain mandatory (==1).
# 				if dtype == "Snacks":
# 					# Allow up to 2 snack selections per slot
# 					model += lpSum(y[(d, i)] for i in ids) <= 2
# 					model += lpSum(y[(d, i)] for i in ids) >= 1
# 				elif dtype in ("Main 2", "Side", "Beverage"):
# 					# These remain optional but limited to 1
# 					model += lpSum(y[(d, i)] for i in ids) <= 1
# 				else:
# 					model += lpSum(y[(d, i)] for i in ids) == 1
#
# 		# Enforce meal-specific allowed dish types:
# 		# - `Side` must NOT appear for Breakfast; allowed only for Lunch and Dinner.
# 		# - `Beverage` is allowed ONLY for Breakfast (disallow in other meals).
# 		for d in days:
# 			for i in candidates.index:
# 				mt = str(candidates.loc[i, "Meal_Time"]).strip()
# 				dt = str(candidates.loc[i, "Dish_Type"]).strip().lower()
# 				# disallow Side in Breakfast
# 				if dt == "side" and mt.lower() == "breakfast":
# 					model += y[(d, int(i))] == 0
# 				# Side only in Lunch/Dinner
# 				if dt == "side" and mt.lower() not in ("lunch", "dinner"):
# 					model += y[(d, int(i))] == 0
# 				# Beverage only for Breakfast
# 				if dt == "beverage" and mt.lower() != "breakfast":
# 					model += y[(d, int(i))] == 0
#
# 		# Conditional pairing constraints: If a Preference row has both Main and Main 2,
# 		# their selections must be identical. If only Main exists, it's free to be chosen.
# 		for d in days:
# 			for meal_time in candidates["Meal_Time"].dropna().unique():
# 				meal_mask = candidates["Meal_Time"] == meal_time
# 				for pref_id, group in candidates[meal_mask].groupby("Preference_Row_ID"):
# 					mains = group[group["Dish_Type"].astype(str).str.strip() == "Main"].index.tolist()
# 					mains2 = group[group["Dish_Type"].astype(str).str.strip() == "Main 2"].index.tolist()
#
# 					if mains and mains2:
# 						# If this ID has both, their selection must be identical (1 and 1, or 0 and 0)
# 						model += lpSum(y[(d, i)] for i in mains) == lpSum(y[(d, j)] for j in mains2)
# 						# Ensure servings for Main are at least servings for Main 2 (Main >= Main2)
# 						model += lpSum(x[(d, i)] for i in mains) >= lpSum(x[(d, j)] for j in mains2)
# 					else:
# 						# If there is no Main available for this preference+meal, explicitly
# 						# disallow selecting Main 2 or Side items so they don't appear without Main.
# 						if not mains and mains2:
# 							model += lpSum(y[(d, j)] for j in mains2) == 0
# 						# also disallow sides for this pref+meal when no Main exists
# 						sides = group[group["Dish_Type"].astype(str).str.strip().str.lower() == "side"].index.tolist()
# 						if not mains and sides:
# 							model += lpSum(y[(d, s)] for s in sides) == 0
#
# 		# Write pairing constraint debug info (which candidate indices were considered for each pref+meal)
# 		try:
# 			pairing_debug_rows = []
# 			for d in days:
# 				for meal_time in sorted(candidates["Meal_Time"].dropna().astype(str).unique().tolist()):
# 					slot_candidates = candidates[candidates["Meal_Time"].astype(str) == str(meal_time)]
# 					for pref_id, group in slot_candidates.groupby("Preference_Row_ID"):
# 						main_ids = group[group["Dish_Type"].astype(str).str.strip() == "Main"].index.tolist()
# 						main2_ids = group[group["Dish_Type"].astype(str).str.strip() == "Main 2"].index.tolist()
# 						pairing_debug_rows.append({
# 							"Day": d,
# 							"Meal_Time": meal_time,
# 							"Preference_Row_ID": pref_id,
# 							"main_ids": ";".join([str(x) for x in main_ids]),
# 							"main2_ids": ";".join([str(x) for x in main2_ids]),
# 							"has_main": bool(len(main_ids) > 0),
# 							"has_main2": bool(len(main2_ids) > 0),
# 						})
# 			out_dir = self.config.outputs_dir
# 			out_dir.mkdir(parents=True, exist_ok=True)
# 			pd.DataFrame(pairing_debug_rows).to_csv(out_dir / "pairing_constraints_debug.csv", index=False)
# 		except Exception:
# 			pass
#
#
# 		for d in days:
# 			for idx, row in candidates.iterrows():
# 				i = int(idx)
# 				meal_time = str(row.get("Meal_Time", ""))
# 				lb, ub = snack_serving_bounds if meal_time == "Snacks" else non_snack_serving_bounds
# 				model += x[(d, i)] <= float(ub) * y[(d, i)]
# 				model += x[(d, i)] >= float(lb) * y[(d, i)]
#
# 		# GL-cap constraints: per-meal and per-day (if provided)
# 		if per_meal_gl_cap is not None:
# 			try:
# 				pmeal = float(per_meal_gl_cap)
# 				for d in days:
# 					for _, slot_row in required_slots.iterrows():
# 						slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
# 						ids = slot_to_ids.get(slot, [])
# 						if not ids:
# 							continue
# 						model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in ids) <= float(pmeal)
# 			except Exception:
# 				pass
#
# 		if per_day_gl_cap is not None:
# 			try:
# 				pday = float(per_day_gl_cap)
# 				for d in days:
# 					model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in candidates.index) <= float(pday)
# 			except Exception:
# 				pass
#
# 		for _, group_df in candidates.groupby(["Meal_Time", "Dish_Type", "Recipe_Code"], dropna=False):
# 			ids = [int(i) for i in group_df.index.tolist()]
# 			model += lpSum(y[(d, i)] for d in days for i in ids) <= int(weekly_rep)
#
# 		# Relax category weekly rep constraint if infeasible
# 		if category_weekly_rep is None:
# 			category_weekly_rep = 0
# 		if category_weekly_rep > 0:
# 			category_df = candidates.dropna(subset=["Category_Key"]).copy()
# 			for _, group_df in category_df.groupby(["Dish_Type", "Category_Key"], dropna=False):
# 				dish_type_u = str(group_df["Dish_Type"].iloc[0]).strip().upper() if not group_df.empty else ""
# 				if dish_type_u != "MAIN":
# 					continue
# 				ids = [int(i) for i in group_df.index.tolist()]
# 				if ids:
# 					# Use a relaxed upper bound (double the rep)
# 					model += lpSum(y[(d, i)] for d in days for i in ids) <= int(category_weekly_rep)
#
# 		# Elastic (goal) constraints for nutrients: add slack variables and penalize shortfall
# 		nutrient_slacks = {}
# 		penalty_weight = 100.0  # Lower penalty to allow more flexibility
# 		for col, req in weekly_min.items():
# 			if col not in candidates.columns or req <= 0:
# 				continue
# 			# Slack variable for shortfall (>=0)
# 			slack = LpVariable(f"nutrient_shortfall_{col}", lowBound=0)
# 			nutrient_slacks[col] = slack
#
# 			if profile and isinstance(profile, dict):
# 				dt = str(profile.get("diet_type", "")).strip().lower()
# 				# for all diets except explicit 'Non-veg', drop VB12 requirement
# 				if dt and dt != "non-veg" and "VB12_mcg" in col:
# 					continue
# 				else:
# 					# Allow shortfall, but penalize in objective
# 					model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for d in days for i in candidates.index) + slack >= float(req)
#
# 		# Add penalty for all nutrient shortfalls to the objective
# 		if nutrient_slacks:
# 			model += penalty_weight * lpSum(slack for slack in nutrient_slacks.values())
#
#
# 		# Enforce per-day kcal bounds using the previously computed `eff_daily` and `upper_mult`.
# 		if eff_daily is not None and "Energy_ENERC_Kcal" in candidates.columns:
# 			for d in days:
# 				daily_kcal = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in candidates.index)
# 				model += daily_kcal >= float(eff_daily)
# 				model += daily_kcal <= float(eff_daily) * float(upper_mult)
#
# 		# Macronutrient percentage constraints (per-day):
# 		# Carbohydrates 45–50% energy, Protein 15–20% energy, Fat 25–35% energy.
# 		# Use energy conversions: carbs=4 kcal/g, protein=4 kcal/g, fat=9 kcal/g.
# 		# Assume required macro columns exist in `candidates`.
# 		candidates["Carb_g"] = pd.to_numeric(candidates.get("Carbohydrate_g", 0), errors="coerce").fillna(0.0)
# 		candidates["Prot_g"] = pd.to_numeric(candidates.get("Protein_PROTCNT_g", 0), errors="coerce").fillna(0.0)
# 		candidates["Fat_g"] = pd.to_numeric(candidates.get("TotalFat_FATCE_g", 0), errors="coerce").fillna(0.0)
# 		candidates["Energy_kcal"] = pd.to_numeric(candidates.get("Energy_ENERC_Kcal", 0), errors="coerce").fillna(0.0)
# 		for d in days:
# 			# Carbs: 45-50% of E_d
# 			model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.45 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
# 			model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.50 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0
#
# 			# Protein: 15-20% of E_d
# 			model += lpSum((4.0 * candidates.loc[i, "Prot_g"] - 0.15 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
# 			model += lpSum((4.0 * candidates.loc[i, "Prot_g"] - 0.20 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0
#
# 			# Fat: 25-35% of E_d
# 			model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.25 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
# 			model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.35 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0
#
# 			# Minimum carbohydrates per day (grams)
# 			min_carbs_per_day = 130.0
# 			model += lpSum(candidates.loc[i, "Carb_g"] * x[(d, int(i))] for i in candidates.index) >= float(min_carbs_per_day)
#
#
# 		# --- Fiber constraints (separate block):
# 		# 1) Energy-based: at least 14 g fiber per 1000 kcal per day
# 		#    (i.e. 4 * sugar_energy example; here: 1000 * daily_fiber >= 14 * daily_energy)
# 		# 2) Gender-based absolute minimum per day: male >=30 g, female >=25 g
# 		candidates["Fiber_g"] = pd.to_numeric(candidates.get("TotalDietaryFibre_FIBTG_g", 0), errors="coerce").fillna(0.0)
# 		# determine gender-based minimum (None if unknown)
# 		_gender_min = None
# 		if profile is not None:
# 			_g = profile.get("gender")
# 			if isinstance(_g, str):
# 				_gs = _g.strip().lower()
# 				if _gs.startswith("m"):
# 					_gender_min = 30.0
# 				elif _gs.startswith("f"):
# 					_gender_min = 25.0
#
# 		for d in days:
# 			daily_fiber = lpSum(float(candidates.loc[i, "Fiber_g"]) * x[(d, int(i))] for i in candidates.index)
# 			daily_energy = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in candidates.index)
# 			# energy-based requirement: 1000 * fiber_g >= 14 * energy_kcal  => daily_fiber >= 14/1000 * daily_energy
# 			model += daily_fiber * 1000.0 >= 14.0 * daily_energy
# 			# enforce gender absolute minimum if known
# 			if _gender_min is not None:
# 				model += daily_fiber >= float(_gender_min)
#
# 		for col, max_req in weekly_max.items():
# 			if col not in candidates.columns or max_req <= 0:
# 				continue
# 			# Relax max constraints by 20%
# 			model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for d in days for i in candidates.index) <= float(max_req) * 1.2
#
# 		# Sugar constraint linked to energy: ensure sugar energy <= 5% of daily energy
# 		# i.e., for each day d: 4 * sum(Sugar_per_serving_g * x[d,i]) <= 0.05 * sum(Energy_ENERC_Kcal * x[d,i])
# 		if 'Sugar_per_serving_g' in candidates.columns and 'Energy_ENERC_Kcal' in candidates.columns:
# 			for d in days:
# 				sugar_energy = lpSum(4.0 * float(candidates.loc[i, 'Sugar_per_serving_g']) * x[(d, int(i))] for i in candidates.index)
# 				daily_energy = lpSum(float(candidates.loc[i, 'Energy_ENERC_Kcal']) * x[(d, int(i))] for i in candidates.index)
# 				model += sugar_energy <= 0.05 * daily_energy
#
# 		# Hard sodium constraint: enforce daily sodium <= 2000 mg (applied across the week)
# 		sodium_limit_per_day_mg = 1500.0
# 		if 'Sodium_mg' in candidates.columns:
# 			model += lpSum(float(candidates.loc[i, 'Sodium_mg']) * x[(d, int(i))] for d in days for i in candidates.index) <= float(sodium_limit_per_day_mg) * float(n_days)
#
# 		# Hard cholesterol constraint: per-day cholesterol < 300 mg
# 		cholesterol_limit_per_day_mg = 300.0
# 		if 'Cholesterol_mg' in candidates.columns:
# 			for d in days:
# 				model += lpSum(float(candidates.loc[i, 'Cholesterol_mg']) * x[(d, int(i))] for i in candidates.index) <= float(cholesterol_limit_per_day_mg)
#
# 		# Hard salt quantity constraint: total salt (grams) per day <= 5 g (applied across the week)
# 		salt_limit_per_day_g = 5
# 		if 'Salt_per_serving_g' in candidates.columns:
# 			model += lpSum(float(candidates.loc[i, 'Salt_per_serving_g']) * x[(d, int(i))] for d in days for i in candidates.index) <= float(salt_limit_per_day_g) * float(n_days)
#
# 		solver = PULP_CBC_CMD(timeLimit=int(time_limit_sec))
# 		_ = model.solve(solver)
# 		status = str(LpStatus.get(model.status, model.status))
#
# 		selected_rows: List[Dict[str, object]] = []
# 		for d in days:
# 			for i in candidates.index:
# 				if float(y[(d, int(i))].value() or 0) > 0.5:
# 					row = candidates.loc[i].to_dict()
# 					row["Day"] = d
# 					row["Serving"] = float(x[(d, int(i))].value() or 0)
# 					selected_rows.append(row)
#
# 		# Dump post-solve variable values for diagnostics (y and x)
# 		try:
# 			vars_rows = []
# 			for d in days:
# 				for i in candidates.index:
# 					y_val = float(y[(d, int(i))].value() or 0)
# 					x_val = float(x[(d, int(i))].value() or 0)
# 					vars_rows.append({
# 						"Day": d,
# 						"Candidate_Index": int(i),
# 						"y_var": f"y_d{d}_r{int(i)}",
# 						"y_val": y_val,
# 						"x_var": f"x_d{d}_r{int(i)}",
# 						"x_val": x_val,
# 					})
# 			out_dir = self.config.outputs_dir
# 			out_dir.mkdir(parents=True, exist_ok=True)
# 			pd.DataFrame(vars_rows).to_csv(out_dir / "y_x_values_postsolve.csv", index=False)
# 		except Exception:
# 			pass
#
# 		weekly_menu = pd.DataFrame(selected_rows)
# 		if not weekly_menu.empty:
# 			weekly_menu = weekly_menu.sort_values(["Day", "Meal_Time", "Dish_Type"]).reset_index(drop=True)
# 		else:
# 			# Fallback: select top candidates for each slot
# 			fallback_rows = []
# 			for d in days:
# 				for _, slot_row in required_slots.iterrows():
# 					slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
# 					ids = slot_to_ids.get(slot, [])
# 					if ids:
# 						i = ids[0]
# 						row = candidates.loc[i].to_dict()
# 						row["Day"] = d
# 						row["Serving"] = 1.0
# 						fallback_rows.append(row)
# 			weekly_menu = pd.DataFrame(fallback_rows)
#
# 		summary = {
# 			"status": status,
# 			"objective": float(value(model.objective)) if model.objective is not None else np.nan,
# 			"objective_metric": objective_metric_col,
# 			"objective_formula": "0.5*z(GL) + 0.3*z(Avg_TimeAbove160_pct) + 0.2*z(Avg_Delta_Glucose)",
# 			"category_weekly_rep": int(category_weekly_rep) if category_weekly_rep is not None else None,
# 			"rows": int(len(weekly_menu)),
# 			"days": int(n_days),
# 			"required_slots": int(len(required_slots)),
# 		}
#
# 		return weekly_menu, summary

	def build_weekly_nutrient_summary(
		self,
		weekly_menu: pd.DataFrame,
		ds: Dict[str, pd.DataFrame],
		age_group_col: str,
		n_days: int = 7,
		profile: Optional[dict] = None,
	) -> pd.DataFrame:
		weekly_min, _, _ = self._get_weekly_requirement_maps(ds, age_group_col=age_group_col, n_days=n_days, profile=profile)
		if not weekly_min:
			return pd.DataFrame(columns=["Nutrient", "Weekly_Requirement", "Achieved_From_Menu", "Percent_Requirement_Met"])

		menu = weekly_menu.copy() if isinstance(weekly_menu, pd.DataFrame) else pd.DataFrame(weekly_menu)
		if menu.empty:
			return pd.DataFrame([
				{
					"Nutrient": nutrient_col,
					"Weekly_Requirement": float(required_val),
					"Achieved_From_Menu": 0.0,
					"Percent_Requirement_Met": 0.0,
				}
				for nutrient_col, required_val in weekly_min.items()
			])

		serving = pd.to_numeric(menu.get("Serving", 1.0), errors="coerce").fillna(1.0)
		# Only retain a fixed set of reported nutrients (nutrient_cols) and the
		# three macro energy-ratio rows as requested.
		nutrient_cols = [
			"Energy_ENERC_Kcal", "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
			"CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg",
			"TotalFolatesB9_FOLSUM_mcg", "VB12_mcg", "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg",
			"NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
			"Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg", "PotassiumK_mg", "Cholesterol_mg"
		]

		rows = []
		# helper to safely get column total (serving-weighted)
		def _total(col_name: str) -> float:
			if col_name in menu.columns:
				vals = pd.to_numeric(menu[col_name], errors="coerce").fillna(0.0)
				return float((vals * serving).sum())
			return 0.0

		for col in nutrient_cols:
			req = weekly_min.get(col, None)
			req_val = float(req) if req is not None else np.nan
			ach = _total(col)
			pct = (100.0 * ach / req_val) if (not pd.isna(req_val) and req_val > 0) else np.nan
			rows.append({
				"Nutrient": col,
				"Weekly_Requirement": req_val,
				"Achieved_From_Menu": ach,
				"Percent_Requirement_Met": pct,
			})

		# Add macro percentage rows
		total_energy = _total("Energy_ENERC_Kcal")
		total_carb_g = _total("Carbohydrate_g")
		total_prot_g = _total("Protein_PROTCNT_g")
		total_fat_g = _total("TotalFat_FATCE_g")
		carb_energy = 4.0 * total_carb_g
		prot_energy = 4.0 * total_prot_g
		fat_energy = 9.0 * total_fat_g
		energy_den = total_energy if total_energy > 1e-6 else (carb_energy + prot_energy + fat_energy)
		if energy_den > 1e-6:
			carb_pct = 100.0 * carb_energy / energy_den
			prot_pct = 100.0 * prot_energy / energy_den
			fat_pct = 100.0 * fat_energy / energy_den
		else:
			carb_pct = prot_pct = fat_pct = np.nan

		rows.append({"Nutrient": "Carbohydrate_pct_energy", "Weekly_Requirement": np.nan, "Achieved_From_Menu": carb_pct, "Percent_Requirement_Met": np.nan})
		rows.append({"Nutrient": "Protein_pct_energy", "Weekly_Requirement": np.nan, "Achieved_From_Menu": prot_pct, "Percent_Requirement_Met": np.nan})
		rows.append({"Nutrient": "Fat_pct_energy", "Weekly_Requirement": np.nan, "Achieved_From_Menu": fat_pct, "Percent_Requirement_Met": np.nan})

		return pd.DataFrame(rows).reset_index(drop=True)

	def run(
		self,
		uid: Optional[str],
		top_n: int,
		ear_group_col: str = "Men_sedentary",
		category_weekly_rep: Optional[int] = None,
		user_preference: str = "yes",
		profile: Optional[Dict[str, object]] = None,
	) -> Dict[str, pd.DataFrame | Dict[str, object]]:
		print("\n[DEBUG] Filtering for top choices...")
		if user_preference.lower() == "no":
			ds = self.load_data(profile)
			recipe_master = self.build_recipe_master(ds)
			main1_to_main2, main1_to_optional = self._get_main1_main2_map(ds)
			mapping_df = ds.get("main1_main2_mapping", pd.DataFrame()).copy()
			scored = self.score_personalization(recipe_master, pd.DataFrame(), ds, top_n=top_n)
			prefs = pd.DataFrame()
		else:
			ds = self.load_data(profile)
			recipe_master = self.build_recipe_master(ds)
			prefs = self.build_preference_map(ds, uid=uid)
			subcat_df = ds.get("sub_category", pd.DataFrame()).copy()
			if not subcat_df.empty:
				subcat_df["SubCategory_merge"] = subcat_df["SubCategory"].astype(str).str.strip().str.lower()
				prefs["sub_category_merge"] = prefs["sub_category"].astype(str).str.strip().str.lower()
				prefs = prefs.merge(
					subcat_df[["Code", "SubCategory_merge"]],
					left_on="sub_category_merge",
					right_on="SubCategory_merge",
					how="left"
				)
				prefs = prefs.rename(columns={"Code": "sub_category_code"})
				prefs = prefs.drop(columns=["sub_category_merge"], errors="ignore")
		print("[DEBUG] recipe_master shape:", recipe_master.shape)
		print("[DEBUG] prefs shape before scoring:", prefs.shape)
		print("[DEBUG] prefs columns:", list(prefs.columns))
		print("[DEBUG] ds keys:", list(ds.keys()))
		print("[DEBUG] Calling score_personalization...")
		scored = self.score_personalization(recipe_master, prefs, ds, top_n=top_n)
		print(scored)
		print("[DEBUG] scored shape after scoring:", scored.shape)
		print("[DEBUG] scored columns after scoring:", list(scored.columns))
		print(f"[DEBUG] prefs shape: {prefs.shape}")
		print(f"[DEBUG] scored shape: {scored.shape}")
		print(f"[DEBUG] scored columns: {list(scored.columns)}")
		if "Recipe_Category" not in scored.columns:
			if "SubCategory" in scored.columns:
				scored["Recipe_Category"] = scored["SubCategory"]
			elif "Subcategories" in scored.columns:
				scored["Recipe_Category"] = scored["Subcategories"]
			else:
				scored["Recipe_Category"] = ""
		for i, pref in enumerate(prefs.iterrows()):
			pref_row = pref[1]
			subcat_code = str(pref_row.get("SubCategory_merge", "")).strip().upper()
			dish_type = str(pref_row.get("dish_type", "")).strip().title()
			meal_time = str(pref_row.get("meal_time", "")).strip().title()
			print(f"[DEBUG] Pref {i+1}: subcat_code={subcat_code}, dish_type={dish_type}, meal_time={meal_time}")
			if scored.empty:
				print(f"[DEBUG]   Scored DataFrame is empty. No candidates for subcat_code={subcat_code}")
				continue
			candidates = scored[scored["Recipe_Category"].astype(str).str.strip().str.upper() == subcat_code]
			print(f"[DEBUG]   Candidates after Recipe_Category filter: {len(candidates)}")
			if candidates.empty:
				print(f"[DEBUG]   No candidates for subcat_code={subcat_code}")
		ds = self.load_data(profile)
		recipe_master = self.build_recipe_master(ds)
		if user_preference.lower() == "no":
			# Strict, code-driven mapping logic for Main, Main 2, and Optional
			main1_to_main2, main1_to_optional = self._get_main1_main2_map(ds)
			mapping_df = ds.get("main1_main2_mapping", pd.DataFrame()).copy()
			scored = self.score_personalization(recipe_master, pd.DataFrame(), ds, top_n=top_n)
			meal_times = ["Breakfast", "Lunch", "Dinner","Snacks"]
			all_rows = []


			# Determine which columns are available in scored
			code_cols = [c for c in ["Code_cooccurence", "MainCategoryCode", "Subcategories"] if c in scored.columns]
			for _, row in mapping_df.iterrows():
				main1 = str(row["Main1_Code"]).strip().upper()
				main2_codes = set(x.strip().upper() for x in str(row["Main2_Code"]).split("/") if x)
				optional_codes = set(x.strip().upper() for x in str(row["Optional"]).split("/") if x)
				# Main
				if code_cols:
					mask_main1 = pd.Series(False, index=scored.index)
					for col in code_cols:
						mask_main1 = mask_main1 | scored[col].astype(str).str.upper().str.startswith(main1)
					subset_main1 = scored[mask_main1].copy()
				else:
					subset_main1 = pd.DataFrame()
				if not subset_main1.empty:
					subset_main1["Preferred_SubCategory_code"] = main1
					subset_main1["Dish_Type"] = "Main"
					for meal_time in meal_times:
						subset_main1["Meal_Time"] = meal_time
						all_rows.append(subset_main1.sort_values("Personalization_Score", ascending=False).head(top_n))
				# Main 2
					for main2 in main2_codes:
						if code_cols:
							mask_main2 = pd.Series(False, index=scored.index)
							for col in code_cols:
								mask_main2 = mask_main2 | scored[col].astype(str).str.upper().str.startswith(main2)
							subset_main2 = scored[mask_main2.astype(bool)].copy()
					else:
						subset_main2 = pd.DataFrame()
					if not subset_main2.empty:
						subset_main2["Preferred_SubCategory_code"] = main2
						subset_main2["Dish_Type"] = "Main 2"
						for meal_time in meal_times:
							subset_main2["Meal_Time"] = meal_time
							all_rows.append(subset_main2.sort_values("Personalization_Score", ascending=False).head(top_n))
				# Optional
					for opt in optional_codes:
						if code_cols:
							mask_opt = pd.Series(False, index=scored.index)
							for col in code_cols:
								mask_opt = mask_opt | scored[col].astype(str).str.upper().str.startswith(opt)
							subset_opt = scored[mask_opt.astype(bool)].copy()
					else:
						subset_opt = pd.DataFrame()
					if not subset_opt.empty:
						subset_opt["Preferred_SubCategory_code"] = opt
						subset_opt["Dish_Type"] = "Side"
						for meal_time in meal_times:
							subset_opt["Meal_Time"] = meal_time
							all_rows.append(subset_opt.sort_values("Personalization_Score", ascending=False).head(top_n))
			top_choices = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
			# Limit to top_n candidates per preference/meal/dish to keep consistent truncation
			if not top_choices.empty:
				top_choices = top_choices.sort_values("Personalization_Score", ascending=False)
				top_choices = top_choices.groupby(["Preference_Row_ID", "Meal_Time", "Dish_Type"], as_index=False, sort=False).head(top_n).reset_index(drop=True)
			prefs = pd.DataFrame()
		else:
			prefs = self.build_preference_map(ds, uid=uid)
			# Use robust merge to ensure sub_category_code is filled for all preferences
			subcat_df = ds.get("subcategories", pd.DataFrame()).copy()
			if not subcat_df.empty:
				prefs = self.merge_preferences_with_subcategory(prefs, subcat_df)
			scored = self.score_personalization(recipe_master, prefs, ds, top_n=top_n)
			# Strict, auditable mapping for YES logic
			main1_to_main2, main1_to_optional = self._get_main1_main2_map(ds)
			all_rows = []
			meal_times = ["Breakfast", "Lunch", "Dinner", "Snacks"]
			print("/////////////////////////////////////")
			print(main1_to_main2)
			print(main1_to_optional)
			scored.to_csv("scored_debug.csv", index=False)
			prefs.to_csv("prefs_debug.csv", index=False)
			
			for _, pref in prefs.iterrows():
				# Use sub_category_code for matching
				subcat_code = str(pref.get("sub_category_code", "")).strip().upper()
				dish_type = str(pref.get("dish_type", "")).strip().title()
				meal_time = str(pref.get("meal_time", "")).strip().title()
				pref_row_id = int(pref.get("Preference_Row_ID", 0))
				# 1. Filter recipes by Recipe_Category (not Subcategories)
				matched_recipes = scored[scored["Recipe_Category"].astype(str).str.strip().str.upper() == subcat_code].copy()
				if matched_recipes.empty:
					continue
				# 2. For Main, use Code_cooccurence from these recipes to drive mapping
				if dish_type == "Main":
					for _, rec_row in matched_recipes.iterrows():
						code_cooc = str(rec_row.get("Code_cooccurence", "")).strip().upper()
						# Main1 (the recipe itself)
						rec_main = rec_row.copy()
						rec_main["Preferred_SubCategory_code"] = subcat_code
						rec_main["Dish_Type"] = "Main"
						rec_main["Meal_Time"] = meal_time
						rec_main["Preference_Row_ID"] = pref_row_id
						# Convert Series to DataFrame for consistent concatenation
						all_rows.append(pd.DataFrame([rec_main]))
						# Main2 (from mapping file, using code_cooc)
						# Prefer mapping keyed by the preference's subcategory code, fall back to recipe's Code_cooccurence
						# Lookup mapping keys robustly: try exact match, fall back to code_cooc,
						# and also allow prefix matches (e.g. mapping has 'A1' while subcat_code is 'A1B').
						mapped_main2_keys = set()
						# exact
						if subcat_code and subcat_code in main1_to_main2:
							mapped_main2_keys |= set(main1_to_main2.get(subcat_code, set()))
						if code_cooc and code_cooc in main1_to_main2:
							mapped_main2_keys |= set(main1_to_main2.get(code_cooc, set()))
						# prefix match: if any mapping key is a prefix of the subcat_code or code_cooc
						for k, vals in main1_to_main2.items():
							if not k:
								continue
							if (subcat_code and str(subcat_code).startswith(k)) or (code_cooc and str(code_cooc).startswith(k)):
								mapped_main2_keys |= set(vals)
						# Expand mapped keys like 'D1/D2' into individual codes
						for key in mapped_main2_keys:
							for main2 in [m.strip().upper() for m in str(key).split('/') if m.strip()]:
								main2_mask = pd.Series(False, index=scored.index)
								for col in ["Code_cooccurence", "MainCategoryCode", "Subcategories"]:
									if col in scored.columns:
										main2_mask = main2_mask | (scored[col].astype(str).str.upper().str.startswith(main2))
								subset_main2 = scored[main2_mask.astype(bool)].copy()
								if not subset_main2.empty:
									subset_main2["Preferred_SubCategory_code"] = main2
									subset_main2["Dish_Type"] = "Main 2"
									subset_main2["Meal_Time"] = meal_time
									subset_main2["Preference_Row_ID"] = pref_row_id
									all_rows.append(subset_main2.sort_values("Personalization_Score", ascending=False))
						# Optional (from mapping file, using code_cooc)
						# Robust lookup for optional mappings as well (same logic as main2)
						mapped_opt_keys = set()
						if subcat_code and subcat_code in main1_to_optional:
							mapped_opt_keys |= set(main1_to_optional.get(subcat_code, set()))
						if code_cooc and code_cooc in main1_to_optional:
							mapped_opt_keys |= set(main1_to_optional.get(code_cooc, set()))
						for k, vals in main1_to_optional.items():
							if not k:
								continue
							if (subcat_code and str(subcat_code).startswith(k)) or (code_cooc and str(code_cooc).startswith(k)):
								mapped_opt_keys |= set(vals)
						for key in mapped_opt_keys:
							for opt in [m.strip().upper() for m in str(key).split('/') if m.strip()]:
								opt_mask = pd.Series(False, index=scored.index)
								for col in ["Code_cooccurence", "MainCategoryCode", "Subcategories"]:
									if col in scored.columns:
										opt_mask = opt_mask | (scored[col].astype(str).str.upper().str.startswith(opt))
								subset_opt = scored[opt_mask.astype(bool)].copy()
								if not subset_opt.empty:
									subset_opt["Preferred_SubCategory_code"] = opt
									subset_opt["Dish_Type"] = "Side"
									subset_opt["Meal_Time"] = meal_time
									subset_opt["Preference_Row_ID"] = pref_row_id
									all_rows.append(subset_opt.sort_values("Personalization_Score", ascending=False))
				else:
					# For non-Main, apply scoring and select top_n
					non_main = matched_recipes.copy()
					non_main["Preferred_SubCategory_code"] = subcat_code
					non_main["Dish_Type"] = dish_type
					non_main["Meal_Time"] = meal_time
					non_main["Preference_Row_ID"] = pref_row_id
					# Recalculate Personalization_Score if needed (already present from scored)
					all_rows.append(non_main.sort_values("Personalization_Score", ascending=False))
			top_choices = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
			# Remove any accidental index columns
			if not top_choices.empty and (top_choices.columns[0] == 'Unnamed: 0' or str(top_choices.columns[0]).startswith('Unnamed')):
				top_choices = top_choices.loc[:, top_choices.columns != top_choices.columns[0]]
		
		# Save intermediate outputs as soon as they are ready
		out_dir = self.config.outputs_dir
		out_dir.mkdir(parents=True, exist_ok=True)
		pd.DataFrame(prefs).to_csv(out_dir / "preferences_used.csv", index=False)
		pd.DataFrame(scored).to_csv(out_dir / "personalization_scored_recipes.csv", index=False)
		
		# Ensure top_choices is a DataFrame with proper columns and no extra index
		if not isinstance(top_choices, pd.DataFrame):
			top_choices = pd.DataFrame(top_choices)
		# Remove any accidental index columns (guard against empty DataFrame)
		if not top_choices.empty:
			first_col = top_choices.columns[0]
			if str(first_col) == 'Unnamed: 0' or str(first_col).startswith('Unnamed'):
				top_choices = top_choices.loc[:, top_choices.columns != first_col]
		# Write only relevant columns (drop any all-NaN columns)
		top_choices = top_choices.dropna(axis=1, how='all')
		required_cols = [
			"Recipe_Code","Recipe_Name","Recipe_Category", "Code_cooccurence", "Preferred_SubCategory_code", "Preference_Row_ID", "Meal_Time", "Dish_Type",
			"GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose", "Energy_ENERC_Kcal", "Energy_ENERC_KJ",
			"Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g", "CalciumCa_CA_mg", "ZincZn_ZN_mg",
			"IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg", "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg",
			"ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg", "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg"
		]

		# Include extended nutrient columns so they are preserved in top_choices and flow through to outputs
		extended_nutrients = [
			"Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg", "PotassiumK_mg", "Cholesterol_mg"
		]
		for c in extended_nutrients:
			if c not in required_cols:
				required_cols.append(c)
		# Only keep columns that exist in top_choices
		
		keep_cols = [col for col in required_cols if col in top_choices.columns]
		top_choices = top_choices[keep_cols].copy()
		top_choices = top_choices.drop_duplicates().reset_index(drop=True)
		top_choices.to_csv(out_dir / "personalized_top_choices.csv", index=False)

		# If a profile was provided to run(), use it; otherwise build one from prefs/defaults
		if profile is None:
			profile = {
				"age": 55,
				"gender": "female",
				"bmi": 26.5,
				"hba1c": None,
				"diet_type": "Veg",
				# default EAR/TUL age-group column; callers/users can override this in the profile
				"age_group_col": ear_group_col or "Men_sedentary",
			}

		# Allow per-user EAR/TUL group to be driven by the profile
		age_group_for_run = profile.get("age_group_col", ear_group_col)
		weekly_menu, weekly_optimization_summary = self.optimize_weekly_menu_with_constraints(
			meal_choices=top_choices,
			ds=ds,
			age_group_col=age_group_for_run,
			n_days=7,
			category_weekly_rep=category_weekly_rep,
			profile=profile,
		)
		weekly_nutrient_summary = self.build_weekly_nutrient_summary(
			weekly_menu=weekly_menu,
			ds=ds,
			age_group_col=age_group_for_run,
			n_days=7,
			profile=profile,
		)
		return {
			"preferences_used": prefs,
			"scored_recipes": scored,
			"top_personalized_choices": top_choices,
			"weekly_menu": weekly_menu,
			"weekly_nutrient_summary": weekly_nutrient_summary,
			"weekly_optimization_summary": weekly_optimization_summary,
		}

	def prepare_combination_summary(self, top_choices_path: Optional[str] = None, top_choices_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
		"""
		Create a simple diagnostic summary that checks, for each selected `Main` recipe,
		whether corresponding `Main 2` and `Side` options exist for the same
		`Preference_Row_ID` and `Meal_Time` in the top choices.

		Either `top_choices_path` (path to CSV) or `top_choices_df` (DataFrame) must be provided.
		The summary CSV is written to the outputs directory as `combination_summary.csv`.
		"""
		if top_choices_df is None:
			if not top_choices_path:
				raise ValueError("Either top_choices_path or top_choices_df must be provided")
			# If the file is empty or unreadable, treat as empty DataFrame rather
			# than failing the whole pipeline.
			try:
				top_choices_df = pd.read_csv(top_choices_path)
			except Exception as exc:
				print(f"[WARN] Failed to read top choices from {top_choices_path}: {exc} -- proceeding with empty DataFrame")
				top_choices_df = pd.DataFrame()

		df = top_choices_df.copy()
		if df.empty:
			return pd.DataFrame()

		# Normalize key columns
		for c in ["Dish_Type", "Preference_Row_ID", "Meal_Time"]:
			if c not in df.columns:
				raise ValueError(f"top_choices missing required column: {c}")

		df["Dish_Type_norm"] = df["Dish_Type"].astype(str).str.strip().str.lower()
		df["Pref_ID_str"] = df["Preference_Row_ID"].astype(str)
		df["Meal_Time_str"] = df["Meal_Time"].astype(str)

		main_rows = df[df["Dish_Type_norm"] == "main"].copy()
		rows = []
		for _, m in main_rows.iterrows():
			pr = str(m["Pref_ID_str"]) if "Pref_ID_str" in m else str(m.get("Preference_Row_ID", ""))
			mt = str(m["Meal_Time_str"]) if "Meal_Time_str" in m else str(m.get("Meal_Time", ""))
			mask = (df["Pref_ID_str"] == pr) & (df["Meal_Time_str"] == mt)
			main2_count = int(df[mask & (df["Dish_Type_norm"] == "main 2")].shape[0])
			side_count = int(df[mask & (df["Dish_Type_norm"] == "side")].shape[0])
			# Build combination string from Code_cooccurence (fallback to Preferred_SubCategory_code)
			vals = set()
			if "Code_cooccurence" in df.columns:
				vals.update({str(x).strip().upper() for x in df.loc[mask, "Code_cooccurence"].dropna().astype(str) if str(x).strip()})
			if not vals and "Preferred_SubCategory_code" in df.columns:
				vals.update({str(x).strip().upper() for x in df.loc[mask, "Preferred_SubCategory_code"].dropna().astype(str) if str(x).strip()})
			combination = "+".join(sorted(vals)) if vals else ""
			rows.append({
				"Preference_Row_ID": pr,
				"Meal_Time": mt,
				"Recipe_Code_Main": m.get("Recipe_Code", ""),
				"Recipe_Name_Main": m.get("Recipe_Name", ""),
				"Recipe_Category": m.get("Recipe_Category", m.get("Recipe_Category", "")),
				"Num_Main2_Available": main2_count,
				"Num_Side_Available": side_count,
				"Combination": combination,
				"Has_Main2": bool(main2_count > 0),
				"Has_Side": bool(side_count > 0),
			})

		summary = pd.DataFrame(rows)
		# Keep only requested three columns and use lowercase 'combination'
		if not summary.empty:
			summary_three = summary[["Preference_Row_ID", "Meal_Time", "Combination"]].copy()
			summary_three = summary_three.rename(columns={"Combination": "combination"})
		else:
			summary_three = pd.DataFrame(columns=["Preference_Row_ID", "Meal_Time", "combination"]) 
		out_dir = self.config.outputs_dir
		out_dir.mkdir(parents=True, exist_ok=True)
		out_path = out_dir / "combination_summary.csv"
		summary_three.to_csv(out_path, index=False)
		print(f"[INFO] Wrote combination summary to {out_path}")
		return summary_three

	def export_outputs(self, outputs: Dict[str, pd.DataFrame | Dict[str, object]]) -> Dict[str, str]:
		out_dir = self.config.outputs_dir
		out_dir.mkdir(parents=True, exist_ok=True)

		paths = {
			"preferences_used": out_dir / "preferences_used.csv",
			"scored_recipes": out_dir / "personalization_scored_recipes.csv",
			"top_personalized_choices": out_dir / "personalized_top_choices.csv",
			"weekly_menu": out_dir / "weekly_menu.csv",
			"weekly_nutrient_summary": out_dir / "weekly_nutrient_summary.csv",
			"weekly_optimization_summary": out_dir / "weekly_optimization_summary.json",
		}
		for key in ["preferences_used", "scored_recipes", "top_personalized_choices", "weekly_menu", "weekly_nutrient_summary"]:
			file_path = paths[key]
			obj = outputs.get(key, pd.DataFrame())
			if isinstance(obj, pd.DataFrame):
				obj.to_csv(file_path, index=False)
			else:
				pd.DataFrame(obj).to_csv(file_path, index=False)

		with Path(paths["weekly_optimization_summary"]).open("w", encoding="utf-8") as fp:
			json.dump(outputs.get("weekly_optimization_summary", {}), fp, indent=2)

		# Generate final human-friendly weekly menu summary merging tagging metadata
		try:
			weekly_menu_df = outputs.get("weekly_menu", pd.DataFrame())
			if not isinstance(weekly_menu_df, pd.DataFrame) or weekly_menu_df.empty:
				# attempt to read from written file
				try:
					weekly_menu_df = pd.read_csv(paths["weekly_menu"])
				except Exception:
					weekly_menu_df = pd.DataFrame()

			# Load tagging file from data directory
			tag_path = self.config.data_dir / "RecipeTagging_Format_verification_All_ADAM.csv"
			try:
				tag_df = pd.read_csv(tag_path)
			except Exception:
				tag_df = pd.DataFrame()

			if not weekly_menu_df.empty:
				# Ensure Serving numeric
				weekly_menu_df["Serving"] = pd.to_numeric(weekly_menu_df.get("Serving", 0.0), errors="coerce").fillna(0.0)
				# Select tagging columns if present
				tag_sel_cols = [c for c in ["Recipe code", "Portion", "Portion weight (g)", "Description","Subcategories"] if c in tag_df.columns]
				tag_sel = tag_df[tag_sel_cols].copy() if not tag_df.empty else pd.DataFrame()
				merged = weekly_menu_df.merge(tag_sel, left_on="Recipe_Code", right_on="Recipe code", how="left")

				# Numeric portion weight
				merged["Portion weight (g)"] = pd.to_numeric(merged.get("Portion weight (g)"), errors="coerce")
				merged["Recipe weight Original (g)"] = merged["Portion weight (g)"]
				merged["Portion original"] = merged.get("Portion")

				merged["Optimal proportion"] = merged.get("Serving", 0.0)
				merged["Recipe weight Optimal (g)"] = (merged["Recipe weight Original (g)"].fillna(0.0) * merged["Optimal proportion"].fillna(0.0)).round(2)

				# Parse numeric portion count from 'Portion' (e.g. '2.0 Number' -> 2.0)
				try:
					merged["Portion_count_original"] = pd.to_numeric(merged.get("Portion", "").astype(str).str.extract(r'([-+]?\d*\.?\d+)')[0], errors="coerce")
				except Exception:
					merged["Portion_count_original"] = pd.Series([pd.NA] * len(merged))
				# Compute numeric Portion optimal = Portion_count_original * Optimal proportion
				_raw_portion_opt = (
					merged["Portion_count_original"].fillna(0.0).astype(float)
					* merged["Optimal proportion"].fillna(0.0).astype(float)
				)
				# Round to nearest 0.25 for user-friendly portions
				merged["Portion optimal"] = (np.round(_raw_portion_opt / 0.25) * 0.25).round(2)
				merged["Description_tagging"] = merged.get("Description")
				merged["OPTIMAL_STATUS"] = merged["Optimal proportion"].apply(lambda v: "selected" if (pd.notna(v) and float(v) > 0) else "not selected")

				out_cols = [
					"Day",
					"Meal_Time",
					"Recipe_Code",
					"Code_cooccurence",
					"Subcategories",
					"Dish_Type",
					"Recipe_Name",
					"Optimal proportion",
					"Recipe weight Original (g)",
					"Portion original",
					"Recipe weight Optimal (g)",
					"Portion optimal",
					"Description_tagging",
					"OPTIMAL_STATUS",
				]
				final_df = merged.reindex(columns=[c for c in out_cols if c in merged.columns])

				# Merge SubCategory GI averages from Excel (Code, GI_Avg) if available
				sub_gi_path = self.config.data_dir / "SubCategory_foods_GI_GL.xlsx"
				try:
					if sub_gi_path.exists():
						sub_gi = pd.read_excel(sub_gi_path)
						if "Code" in sub_gi.columns and "GI_Avg" in sub_gi.columns:
							sg = sub_gi[["Code", "GI_Avg"]].copy()
							sg["Code"] = sg["Code"].astype(str).str.strip().str.upper()
							final_df["Subcategories_norm"] = final_df.get("Subcategories", "").astype(str).str.strip().str.upper()
							final_df = final_df.merge(sg, left_on="Subcategories_norm", right_on="Code", how="left")
							# rename merged Code to Subcategory_Code for clarity
							if "Code" in final_df.columns:
								final_df = final_df.rename(columns={"Code": "Subcategory_Code"})
							# drop helper column
							final_df = final_df.drop(columns=[c for c in ["Subcategories_norm"] if c in final_df.columns])
							# Attach human-readable subcategory name from SubCategory.csv (if available)
							try:
								sub_ref_path = self.config.data_dir / "SubCategory.csv"
								if sub_ref_path.exists():
									sub_ref = pd.read_csv(sub_ref_path, dtype=str)
									if "Code" in sub_ref.columns and "SubCategory" in sub_ref.columns:
										# Normalize codes for matching
										sub_ref["Code"] = sub_ref["Code"].astype(str).str.strip().str.upper()
										final_df["Subcategory_Code"] = final_df.get("Subcategory_Code", "").astype(str).str.strip().str.upper()
										final_df = final_df.merge(sub_ref[["Code", "SubCategory"]], left_on="Subcategory_Code", right_on="Code", how="left")
										# keep the name under a clear column and drop the merge helper
										if "SubCategory" in final_df.columns:
											final_df = final_df.rename(columns={"SubCategory": "Subcategory_Name"})
										final_df = final_df.drop(columns=[c for c in ["Code"] if c in final_df.columns])
							except Exception:
								# non-fatal: proceed without subcategory name
								pass

					# Enrich final_df with nutrition from Recipes and compute GL at optimal serving
					try:
						rec_path = self.config.data_dir / "Recipes_All_ADAM.csv"
						if rec_path.exists():
							rec_df = pd.read_csv(rec_path)
							# find recipe code column in recipes
							code_col = None
							for c in ["Recipe code", "Recipe_Code", "Recipe Code", "Code"]:
								if c in rec_df.columns:
									code_col = c
									break
							if code_col is not None:
								rec_sel = rec_df[[code_col] + [col for col in ["Carbohydrate_g", "TotalDietaryFibre_FIBTG_g"] if col in rec_df.columns]].copy()
								rec_sel = rec_sel.rename(columns={code_col: "Recipe_Code"})
								final_df = final_df.merge(rec_sel, on="Recipe_Code", how="left")

							# determine fiber column to use
							if "TotalDietaryFibre_FIBTG_g" in final_df.columns:
								final_df["_fiber_for_gl"] = pd.to_numeric(final_df["TotalDietaryFibre_FIBTG_g"], errors="coerce").fillna(0.0)
							else:
								final_df["_fiber_for_gl"] = 0.0

							# ensure numeric carbs, GI and optimal proportion
							final_df["_carb_g"] = pd.to_numeric(final_df.get("Carbohydrate_g"), errors="coerce")
							final_df["_gi"] = pd.to_numeric(final_df.get("GI_Avg"), errors="coerce")
							final_df["_opt_prop"] = pd.to_numeric(final_df.get("Optimal proportion"), errors="coerce").fillna(0.0)

							# compute GL at optimal serving: GI * ((Carbs - fiber) * optimal_prop) / 100
							carb_minus_fiber = (final_df["_carb_g"].fillna(0.0) - final_df["_fiber_for_gl"].fillna(0.0)).clip(lower=0.0)
							final_df["GL"] = (final_df["_gi"].fillna(np.nan) * (carb_minus_fiber * final_df["_opt_prop"])) / 100.0
							# if GI or carbs missing, leave GL as NaN
						else:
							# recipes file missing — set GL to NaN
							final_df["GL"] = np.nan
					except Exception:
						# non-fatal; leave GL unset
						final_df["GL"] = final_df.get("GL", np.nan)
				except Exception:
					# non-fatal; proceed without GI merge
					pass

				# Save CSV for backward compatibility
				# Ensure all expected columns are present (create as NaN/defaults if missing)
				expected_cols = [
					"Day",
					"Meal_Time",
					"Recipe_Code",
					"Code_cooccurence",
					"Subcategories",
					"Dish_Type",
					"Recipe_Name",
					"Optimal proportion",
					"Recipe weight Original (g)",
					"Portion original",
					"Recipe weight Optimal (g)",
					"Portion optimal",
					"Description_tagging",
					"OPTIMAL_STATUS",
					"Subcategory_Code",
					"GI_Avg",
					"Carbohydrate_g",
					"TotalDietaryFibre_FIBTG_g",
					"_fiber_for_gl",
					"_carb_g",
					"_gi",
					"_opt_prop",
					"GL",
				]
				for c in expected_cols:
					if c not in final_df.columns:
						final_df[c] = pd.NA

				# Ensure numeric columns have numeric dtypes where possible
				numeric_cols = ["Carbohydrate_g", "TotalDietaryFibre_FIBTG_g", "_fiber_for_gl", "_carb_g", "_gi", "_opt_prop", "GL"]
				for nc in numeric_cols:
					if nc in final_df.columns:
						final_df[nc] = pd.to_numeric(final_df[nc], errors="coerce")

				csv_path = out_dir / "final_menu_summary.csv"
				final_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
				paths["final_menu_summary"] = csv_path
				# Also save as Excel with two sheets: full data and a compact summary view
				try:
					xlsx_path = out_dir / "final_menu_summary.xlsx"
					with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
						final_df.to_excel(writer, sheet_name='full', index=False)
						cols = [
							"Day",
							"Meal_Time",
							"Dish_Type",
							"Recipe_Name",
							"Portion optimal",
							"Description_tagging",
							"Subcategory_Name",
							"GI_Avg",
							"GL",
						]
						subset = final_df[[c for c in cols if c in final_df.columns]].copy()
						subset.to_excel(writer, sheet_name='summary_view', index=False)
					paths["final_menu_summary_xlsx"] = xlsx_path
				except Exception:
					# non-fatal: continue without Excel
					pass
		except Exception:
			# Non-fatal: fail silently but continue returning paths
			pass

		# If we didn't build `final_df` above (e.g., weekly_menu was empty),
		# run the migrated generator to produce the final menu summary files.
		try:
			if (('final_df' not in locals() or final_df.empty) and 'generate_final_menu_summary_script' in globals()):
				try:
					generate_final_menu_summary_script()
					paths["final_menu_summary"] = out_dir / "final_menu_summary.csv"
					paths["final_menu_summary_xlsx"] = out_dir / "final_menu_summary.xlsx"
				except Exception:
					pass
		except Exception:
			# non-fatal; don't block export
			pass



		# Post-process written final_menu_summary.csv (if present) to ensure
		# it contains the full set of expected columns.
		try:
			fm_csv = paths.get("final_menu_summary")
			if fm_csv:
				fm_path = Path(fm_csv)
				if fm_path.exists():
					df_fm = pd.read_csv(fm_path)
					expected_cols = [
						"Day",
						"Meal_Time",
						"Recipe_Code",
						"Code_cooccurence",
						"Subcategories",
						"Dish_Type",
						"Recipe_Name",
						"Optimal proportion",
						"Recipe weight Original (g)",
						"Portion original",
						"Recipe weight Optimal (g)",
						"Portion optimal",
						"Description_tagging",
						"OPTIMAL_STATUS",
						"Subcategory_Code",
						"GI_Avg",
						"Carbohydrate_g",
						"TotalDietaryFibre_FIBTG_g",
						"_fiber_for_gl",
						"_carb_g",
						"_gi",
						"_opt_prop",
						"GL",
					]
					for c in expected_cols:
						if c not in df_fm.columns:
							df_fm[c] = pd.NA
					# Coerce numeric columns
					numeric_cols = ["Carbohydrate_g", "TotalDietaryFibre_FIBTG_g", "_fiber_for_gl", "_carb_g", "_gi", "_opt_prop", "GL"]
					for nc in numeric_cols:
						if nc in df_fm.columns:
							df_fm[nc] = pd.to_numeric(df_fm[nc], errors='coerce')
					df_fm.to_csv(fm_path, index=False, encoding='utf-8-sig')
		except Exception:
			pass


		# Finalize paths as strings and return
		return {key: str(path) for key, path in paths.items()}
				# Sides and Beverages: no restriction on Preference_Row_ID

def get_example_profile() -> Dict[str, object]:
	"""
	Return an example `profile` dictionary suitable for passing to
	`optimize_weekly_menu_with_constraints`.

	Fields provided (caller can extend/update as needed):
	- age: int
	- gender: str
	- bmi: float
	- hba1c: float
	- diet_type: str
	"""
	return {
		"age": 45,
		"gender": "female",
		"bmi": 26.5,
		"hba1c": 6.5,
		"diet_type": "standard",
	}


# --- moved from scripts/generate_final_menu_summary.py ---
ROOT = Path(".")
WEEKLY = ROOT / "base_outputs" / "weekly_menu.csv"
TAG = ROOT / "Datasets" / "RecipeTagging_Format_verification_All_ADAM.csv"
OUT = ROOT / "base_outputs" / "final_menu_summary.csv"


def gfm_load_data():
	wk = pd.read_csv(WEEKLY)
	tag = pd.read_csv(TAG)
	# Normalize column names
	tag.columns = [c.strip() for c in tag.columns]
	return wk, tag


def gfm_build_summary(wk: pd.DataFrame, tag: pd.DataFrame) -> pd.DataFrame:
	# Ensure Serving is numeric
	wk["Serving"] = pd.to_numeric(wk.get("Serving", 0.0), errors="coerce").fillna(0.0)

	# Select tagging fields we need
	tag_sel = tag[[c for c in ["Recipe code", "Portion", "Portion weight (g)", "Description"] if c in tag.columns]]

	merged = wk.merge(tag_sel, left_on="Recipe_Code", right_on="Recipe code", how="left")

	# Compute numeric portion weight
	merged["Portion weight (g)"] = pd.to_numeric(merged.get("Portion weight (g)"), errors="coerce")

	# Original weight and portion
	merged["Recipe weight Original (g)"] = merged["Portion weight (g)"]
	merged["Portion original"] = merged.get("Portion")

	# Optimal computations
	merged["Optimal proportion"] = merged.get("Serving")
	merged["Recipe weight Optimal (g)"] = (merged["Recipe weight Original (g)"] * merged["Optimal proportion"]).round(2)

	merged["Portion optimal"] = (merged["Portion original"] * merged["Optimal proportion"]).round(2)

	# Description from tagging file
	merged["Description_tagging"] = merged.get("Description")

	# OPTIMAL STATUS: selected if serving > 0
	merged["OPTIMAL_STATUS"] = merged["Optimal proportion"].apply(lambda v: "selected" if (pd.notna(v) and v > 0) else "not selected")

	# Build final columns in requested order
	out_cols = [
		"Day",
		"Meal_Time",
		"Recipe_Code",
		"Recipe_Name",
		"Optimal proportion",
		"Recipe weight Original (g)",
		"Portion original",
		"Recipe weight Optimal (g)",
		"Portion optimal",
		"Description_tagging",
		"OPTIMAL_STATUS",
	]

	# Ensure Meal_Time present
	if "Meal_Time" not in merged.columns and "Meal_Time" in wk.columns:
		merged["Meal_Time"] = wk["Meal_Time"]

	final = merged.reindex(columns=[c for c in out_cols if c in merged.columns])
	return final


def generate_final_menu_summary_script():
	wk, tag = gfm_load_data()
	final = gfm_build_summary(wk, tag)
	OUT.parent.mkdir(parents=True, exist_ok=True)
	final.to_csv(OUT, index=False)
	print(f"Wrote final summary to: {OUT}")
	# Also save as Excel with a full sheet and a compact summary_view sheet
	try:
		xlsx_out = OUT.parent / "final_menu_summary.xlsx"
		with pd.ExcelWriter(xlsx_out, engine='openpyxl') as writer:
			final.to_excel(writer, sheet_name='full', index=False)
			cols = [
				"Day",
				"Meal_Time",
				"Dish_Type",
				"Recipe_Name",
				"Portion optimal",
				"Description_tagging",
				"Subcategory_Name",
				"GI_Avg",
				"GL",
			]
			subset = final[[c for c in cols if c in final.columns]].copy()
			subset.to_excel(writer, sheet_name='summary_view', index=False)
		print(f"Wrote Excel final summary to: {xlsx_out}")
	except Exception as e:
		print(f"Failed to write Excel final summary: {e}")

# --- end moved code ---


def _cli() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="ADAM Personalization model (GI by subcategory)")
	parser.add_argument("--workspace", type=str, default=".", help="Workspace root containing Datasets")
	parser.add_argument("--uid", type=str, default=None, help="UID in Preference_onboarding.csv")
	parser.add_argument("--top-n", type=int, default=10, help="Top choices per meal/dish/subcategory")
	parser.add_argument("--ear-group", type=str, default="Men_sedentary", help="EAR/TUL group for weekly optimization")
	parser.add_argument("--category-weekly-rep", type=int, default=5, help="Max weekly uses per Dish_Type x Category (boredom control)")
	parser.add_argument("--user-preference", type=str, default="yes", help="Use user preferences (yes) or mapping file only (no)")
	parser.add_argument("--profile", type=str, default=None, help="Path to a JSON file containing user profile (age, gender, bmi, hba1c, age_group_col, etc.)")
	return parser.parse_args()


def main() -> None:
	args = _cli()
	model = ADAMPersonalizationModel(args.workspace)
	# Load profile JSON if provided on the CLI (so load_data can use it)
	profile_obj = None
	if args.profile:
		try:
			with open(args.profile, 'r', encoding='utf-8') as pf:
				profile_obj = json.load(pf)
		except Exception as _exc:
			print(f"[WARN] Failed to load profile from {args.profile}: {_exc}")

	# Print merged preferences for debugging
	ds = model.load_data(profile_obj)
	prefs = ds["preferences"].copy()
	subcat = ds["subcategories"].copy()
	merged = model.merge_preferences_with_subcategory(prefs, subcat)
	print("\nMERGED PREFERENCES (first 10 rows):")
	print(merged.head(10).to_string())
	print("\nRows with empty sub_category_code:")
	print(merged[merged['sub_category_code'].isnull() | (merged['sub_category_code'] == '')].to_string())
	print("\nRows with empty SubCategory_merge (if present):")
	if 'SubCategory_merge' in merged.columns:
		print(merged[merged['SubCategory_merge'].isnull() | (merged['SubCategory_merge'] == '')].to_string())

	outputs = model.run(
		uid=args.uid,
		top_n=args.top_n,
		ear_group_col=args.ear_group,
		category_weekly_rep=args.category_weekly_rep,
		user_preference=args.user_preference,
		profile=profile_obj,
	)
	paths = model.export_outputs(outputs)

	print("personalization_ok: True")
	for key, path in paths.items():
		print(f"{key}: {path}")
	print(f"rows_top_choices: {len(outputs['top_personalized_choices'])}")
	print(f"weekly_optimization_status: {outputs.get('weekly_optimization_summary', {}).get('status', 'unknown')}")

	# Run combination summary after top choices are saved
	if 'top_personalized_choices' in paths:
		model.prepare_combination_summary(top_choices_path=paths['top_personalized_choices'])

	# Run pairing diagnostic script (non-fatal if tools not available)
	try:
		from tools.pairing_diag import run_pairing_diagnostic
		try:
			report_path = run_pairing_diagnostic(out_dir=model.config.outputs_dir)
			print(f"pairing_diagnostic: {report_path}")
		except Exception as _exc:
			print(f"[WARN] pairing diagnostic failed: {_exc}")
	except Exception:
		# tools package or script not present — skip
		pass

	# # Diagnostic summary for Main, Main 2, and Side availability
	# import pandas as pd
	# top_choices = pd.read_csv(paths['top_personalized_choices'])
	# print("\n[DIAG] Checking Main, Main 2, and Side availability for each Main in top choices:")
	# missing_main2 = []
	# missing_side = []
	# for _, main_row in top_choices[top_choices['Dish_Type'] == 'Main'].iterrows():
	# 	pr_id = main_row['Preference_Row_ID']
	# 	meal_time = main_row['Meal_Time']
	# 	# Skip Beverages
	# 	if str(main_row['Recipe_Category']).strip().lower() in ['beverage', 'beverages'] or str(main_row['Dish_Type']).strip().lower() == 'beverage':
	# 		continue
	# 	# Check Main 2
	# 	has_main2 = not top_choices[(top_choices['Dish_Type'] == 'Main 2') & (top_choices['Preference_Row_ID'] == pr_id) & (top_choices['Meal_Time'] == meal_time)].empty
	# 	if not has_main2:
	# 		missing_main2.append((pr_id, meal_time, main_row['Recipe_Category']))
	# 	# Check Side
	# 	has_side = not top_choices[(top_choices['Dish_Type'] == 'Side') & (top_choices['Preference_Row_ID'] == pr_id) & (top_choices['Meal_Time'] == meal_time)].empty
	# 	if not has_side:
	# 		missing_side.append((pr_id, meal_time, main_row['Recipe_Category']))
	# if not missing_main2 and not missing_side:
	# 	print("All Main choices have corresponding Main 2 and Side options available (except Beverages, which are independent).")
	# else:
	# 	if missing_main2:
	# 		print("Missing Main 2 for the following Main choices:")
	# 		for pr_id, meal_time, cat in missing_main2:
	# 			print(f"  Preference_Row_ID={pr_id}, Meal_Time={meal_time}, Recipe_Category={cat}")
	# 	if missing_side:
	# 		print("Missing Side for the following Main choices:")
	# 		for pr_id, meal_time, cat in missing_side:
	# 			print(f"  Preference_Row_ID={pr_id}, Meal_Time={meal_time}, Recipe_Category={cat}")


if __name__ == "__main__":
	main()
