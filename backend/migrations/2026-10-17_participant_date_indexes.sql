CREATE INDEX IF NOT EXISTS recommendationsbackup_user_timings_date_idx
  ON public."RecommendationsBackup" (user_id, "Timings", "Date");


CREATE INDEX IF NOT EXISTS dietrecall_user_slot_date_idx
  ON public."DietRecall" (user_id, meal_slot, "Date");


CREATE INDEX IF NOT EXISTS dietrecall_created_at_idx
  ON public."DietRecall" (created_at);


CREATE INDEX IF NOT EXISTS recommendation_user_date_idx
  ON public."Recommendation" (user_id, "Date");


CREATE INDEX IF NOT EXISTS wh_messages_user_date_slot_idx
  ON public."WH_Messages" (user_id, meal_date, meal_slot);


CREATE INDEX IF NOT EXISTS be_preference_onboarding_details_user_idx
  ON public."BE_Preference_onboarding_details" (user_id);