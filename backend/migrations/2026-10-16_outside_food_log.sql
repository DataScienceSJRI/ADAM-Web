CREATE TABLE IF NOT EXISTS public."OutsideFoodLog" (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  user_id text NOT NULL,
  recipe_code text NOT NULL,
  recipe_name text,
  meal_date date NOT NULL,        
  meal_slot text NOT NULL,       
  plan_id text,
  week_no int,
  week_start_date date NOT NULL,  
  quantity numeric NOT NULL,       
  unit text,                       
  grams numeric,                   
  gl numeric,                     
  energy_kcal numeric,
  week_count int NOT NULL          
);

CREATE INDEX IF NOT EXISTS outside_food_log_user_week_idx
  ON public."OutsideFoodLog" (user_id, week_start_date);

CREATE INDEX IF NOT EXISTS outside_food_log_recipe_code_idx
  ON public."OutsideFoodLog" (recipe_code);
