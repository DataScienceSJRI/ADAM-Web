#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
EMAIL="${EMAIL:-test@example.com}"
PASSWORD="${PASSWORD:-test1234}"
DATE="${DATE:-$(date +%Y-%m-%d)}"

echo "==> Authenticating as $EMAIL"
TOKEN=$(curl -sf -X POST "$BASE_URL/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$EMAIL&password=$PASSWORD" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "    OK"

echo ""
echo "==> Fetching daily plan for $DATE"
PLAN=$(curl -sf "$BASE_URL/plan/daily?plan_date=$DATE" \
  -H "Authorization: Bearer $TOKEN")
echo "$PLAN" | python3 -m json.tool

echo ""
echo "==> Extracting lunch slot from plan"
LUNCH=$(echo "$PLAN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
lunch = [m for m in data.get('meals', []) if m.get('Timings') == 'Lunch']
if not lunch:
    print('NO_LUNCH')
    sys.exit(0)
codes = '&'.join(f\"recipe_codes={m['Food_Name_desc']}\" for m in lunch)
qtys  = '&'.join(f\"recipe_quantities={m['Food_Qty']}\" for m in lunch)
print(f'{codes}&{qtys}')
")

if [ "$LUNCH" = "NO_LUNCH" ]; then
  echo "    No lunch items found for $DATE — skipping replacements test"
  exit 0
fi

echo "    Params: $LUNCH"

echo ""
echo "==> Fetching GL-ranked replacements for lunch"
curl -sf "$BASE_URL/plan/replacements?date=$DATE&day=1&meal_slot=lunch&$LUNCH" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
original_gl = data.get('original_gl', 0)
print(f'\nOriginal meal GL: {original_gl}')
for i, combo in enumerate(data.get('alternatives', []), 1):
    combo_gl = sum(item.get('gl') or 0 for item in combo)
    delta = abs(combo_gl - original_gl)
    print(f'\nCombo {i}  (total GL: {combo_gl:.2f}, delta from original: {delta:.2f}):')
    for item in combo:
        print(f\"  [{item['recipe_code']}] {item['recipe_name']}\")
        print(f\"    qty={item['quantity']}  gl={item.get('gl', 'n/a')}\")
"
