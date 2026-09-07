-- Adds the columns backend/whatsapp_feedback_backtest.py's
-- handle_diet_recall_entry() needs to log a full feedback message (GL,
-- nutrition, dish attribution) into WH_Messages, not just the plain text
-- the table originally supported.
--
-- Purely additive: every new column is nullable, nothing existing is
-- renamed or retyped, and no existing caller (log_pending / mark_sent /
-- mark_error / send_whatsapp) needs to change.
--
-- Already applied to production (2026-09-07) via the Supabase SQL editor —
-- this file exists so the change is version-controlled and repeatable in
-- any other environment (staging, a fresh project, etc.).

ALTER TABLE public."WH_Messages"
  ADD COLUMN IF NOT EXISTS meal_date date,
  ADD COLUMN IF NOT EXISTS meal_slot text,
  ADD COLUMN IF NOT EXISTS message_type text,
  ADD COLUMN IF NOT EXISTS meal_source text,
  ADD COLUMN IF NOT EXISTS dishes text,
  ADD COLUMN IF NOT EXISTS actual_gl numeric,
  ADD COLUMN IF NOT EXISTS planned_gl numeric,
  ADD COLUMN IF NOT EXISTS response_status text,
  ADD COLUMN IF NOT EXISTS energy_kcal numeric,
  ADD COLUMN IF NOT EXISTS carbs_g numeric,
  ADD COLUMN IF NOT EXISTS fibre_g numeric,
  ADD COLUMN IF NOT EXISTS scheduled_at text;
