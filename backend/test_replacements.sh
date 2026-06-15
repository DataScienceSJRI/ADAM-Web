#!/usr/bin/env bash
# Test script for the GL-ranked replacement endpoints.
# Usage:
#   bash test_replacements.sh
#   BASE_URL=https://staging/api/v1 EMAIL=x@y.com PASSWORD=pass bash test_replacements.sh
#   DATE=2026-06-07 bash test_replacements.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
EMAIL="${EMAIL:-test@example.com}"
PASSWORD="${PASSWORD:-test1234}"
DATE="${DATE:-$(date +%Y-%m-%d)}"

# ── Auth ─────────────────────────────────────────────────────────────────────
echo "==> Authenticating as $EMAIL"
TOKEN=$(curl -sf -X POST "$BASE_URL/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$EMAIL&password=$PASSWORD" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "    OK"

# ── Daily plan ────────────────────────────────────────────────────────────────
echo ""
echo "==> Fetching daily plan for $DATE"
PLAN=$(curl -sf "$BASE_URL/plan/daily?plan_date=$DATE" \
  -H "Authorization: Bearer $TOKEN")
echo "$PLAN" | python3 -m json.tool

# ── Extract lunch ─────────────────────────────────────────────────────────────
echo ""
echo "==> Extracting lunch slot"
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
  echo "    No lunch items found for $DATE — skipping"
  exit 0
fi
echo "    Params: $LUNCH"

# ── GET /replacements: GL-ranked pre-approved alternatives ────────────────────
echo ""
echo "==> GET /replacements — GL-ranked alternatives for lunch"
REPL=$(curl -sf "$BASE_URL/plan/replacements?date=$DATE&day=1&meal_slot=lunch&$LUNCH" \
  -H "Authorization: Bearer $TOKEN")
echo "$REPL" | python3 -c "
import sys, json
data = json.load(sys.stdin)
original_gl = data.get('original_gl', 0)
print(f'Original meal GL: {original_gl}')
for i, combo in enumerate(data.get('alternatives', []), 1):
    combo_gl = sum(item.get('gl') or 0 for item in combo)
    delta = abs(combo_gl - original_gl)
    print(f'\nCombo {i}  (total GL: {combo_gl:.2f}, delta from original: {delta:.2f}):')
    for item in combo:
        print(f\"  [{item['recipe_code']}] {item['recipe_name']}\")
        print(f\"    qty={item['quantity']}  gl={item.get('gl', 'n/a')}\")
"

# Extract the first pre-approved combo's recipe codes and original codes
ORIG_CODES=$(echo "$PLAN" | python3 -c "
import sys, json
meals = json.load(sys.stdin).get('meals', [])
lunch = [m for m in meals if m.get('Timings') == 'Lunch']
import json as j
print(j.dumps([m['Food_Name_desc'] for m in lunch]))
")
ALT_CODES=$(echo "$REPL" | python3 -c "
import sys, json
data = json.load(sys.stdin)
alts = data.get('alternatives', [])
if not alts or not alts[0]:
    print('[]')
else:
    import json as j
    print(j.dumps([x['recipe_code'] for x in alts[0]]))
")

# ── POST /replacements/request: GL validation + plan write ────────────────────
echo ""
echo "==> POST /replacements/request — Test 1: propose Combo 1 from pre-approved list"
echo "    Original: $ORIG_CODES  →  Proposed: $ALT_CODES"
curl -s -X POST "$BASE_URL/plan/replacements/request" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"date\":\"$DATE\",\"meal_slot\":\"lunch\",\"recipe_codes\":$ALT_CODES,\"original_recipe_codes\":$ORIG_CODES}" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'possible: {d[\"possible\"]}')
if d.get('combination'):
    combo_gl = sum(i.get('gl') or 0 for i in d['combination'])
    print(f'Accepted combo GL: {combo_gl:.2f}')
    for i in d['combination']:
        print(f'  [{i[\"recipe_code\"]}] {i[\"recipe_name\"]} qty={i[\"quantity\"]} gl={i.get(\"gl\")}')
"

echo ""
echo "==> POST /replacements/request — Test 2: propose single Cucumber (low-GL, should be REJECTED)"
echo "    Original GL target ~$(echo "$REPL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('original_gl',0))")"
curl -s -X POST "$BASE_URL/plan/replacements/request" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"date\":\"$DATE\",\"meal_slot\":\"lunch\",\"recipe_codes\":[\"B000031\"],\"original_recipe_codes\":$ORIG_CODES}" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'possible: {d[\"possible\"]}  (expected: False — Cucumber GL too low to match original meal GL ±20%)')
"
