from enum import Enum
from pydantic import BaseModel
from typing import Optional, List


class GeneratePlanRequest(BaseModel):
    week_no: int = 1
    onboarding_id: Optional[str] = None
    target_user_id: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {"week_no": 1, "onboarding_id": "a1b2c3d4-0000-0000-0000-000000000000"}}}


class GeneratePlanResponse(BaseModel):
    status: str
    rows_written: int
    plan_id: Optional[str] = None
    onboarding_id: Optional[str] = None
    optimization_status: Optional[str] = None
    message: Optional[str] = None


class PlanSummary(BaseModel):
    plan_id: str
    onboarding_id: Optional[str] = None
    week_no: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    row_count: int


class PlanStatusResponse(BaseModel):
    has_plan: bool
    row_count: int
    plans: list[PlanSummary]


class MealSlot(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snacks"


# DB Recommendation.Timings stores "Snacks" (plural) for snack slot
SLOT_TO_TIMINGS: dict = {
    MealSlot.BREAKFAST: "Breakfast",
    MealSlot.LUNCH: "Lunch",
    MealSlot.DINNER: "Dinner",
    MealSlot.SNACK: "Snacks",
}


class IntensityLevel(str, Enum):
    LIGHT = "Light"
    MODERATE = "Moderate"
    VIGOROUS = "Vigorous"


class TimeOfDay(str, Enum):
    MORNING = "Morning"
    AFTERNOON = "Afternoon"
    EVENING = "Evening"
    NIGHT = "Night"


class ReactionType(str, Enum):
    LIKE = "like"
    DISLIKE = "dislike"


class LoginRequest(BaseModel):
    email: str
    password: str

    model_config = {"json_schema_extra": {"example": {"email": "user@example.com", "password": "yourpassword"}}}


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str


class RefreshRequest(BaseModel):
    refresh_token: str

    model_config = {"json_schema_extra": {"example": {"refresh_token": "your-refresh-token-here"}}}


class ActivityLogRequest(BaseModel):
    pa_name: str
    duration_min: int
    intensity: IntensityLevel
    date: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {"pa_name": "Walking", "duration_min": 30, "intensity": "Light", "date": "2026-06-12"}}}


class MealReactionRequest(BaseModel):
    plan_id: str
    date: str
    meal_slot: MealSlot
    recipe_codes: List[str]
    reaction: ReactionType

    model_config = {"json_schema_extra": {"example": {"plan_id": "abc-123", "date": "2026-05-22", "meal_slot": "breakfast", "recipe_codes": ["A001745", "A004981"], "reaction": "like"}}}


class DietRecallLogRequest(BaseModel):
    plan_id: str
    date: Optional[str] = None
    meal_slot: MealSlot
    did_eat_as_planned: bool
    recipe_code: Optional[str] = None              # single recipe (legacy)
    recipe_codes: Optional[List[str]] = None       # multiple recipes (preferred)
    actual_quantity: Optional[str] = None          # single quantity (legacy)
    actual_quantities: Optional[List[str]] = None  # one per recipe_codes entry (preferred)

    model_config = {"json_schema_extra": {"example": {"plan_id": "abc-123", "date": "2026-05-22", "meal_slot": "breakfast", "did_eat_as_planned": False, "recipe_codes": ["B000029", "A001234"], "actual_quantities": ["0.8", "1.0"]}}}


class DietRecallUpdateRequest(BaseModel):
    did_eat_as_planned: Optional[bool] = None
    food_qty: Optional[str] = None
    notes: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {"did_eat_as_planned": False, "food_qty": "0.75", "notes": "ate less"}}}


class DietRecallImageRequest(BaseModel):
    plan_id: str
    meal_slot: MealSlot
    image_url_pre: Optional[str] = None
    image_url_post: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {"plan_id": "abc-123", "meal_slot": "breakfast", "image_url_pre": "https://<project>.supabase.co/storage/v1/object/public/meal-images/user/breakfast/pre_123.jpg", "image_url_post": None}}}


class RecipeWithQty(BaseModel):
    recipe_code: str
    recipe_name: Optional[str] = None
    quantity: float
    unit: str = "serving"


class OnDemandReplacementRequest(BaseModel):
    date: str
    meal_slot: MealSlot
    recipe_codes: List[str]
    original_recipe_codes: Optional[List[str]] = None  # recipes being replaced; if omitted, replaces the whole slot

    model_config = {"json_schema_extra": {"example": {"date": "2026-05-22", "meal_slot": "breakfast", "recipe_codes": ["A001745"], "original_recipe_codes": ["A002798"]}}}


class OnDemandReplacementResponse(BaseModel):
    possible: bool
    combination: Optional[List[RecipeWithQty]] = None


class RegisterTokenRequest(BaseModel):
    device_token: str
    platform: str

    model_config = {"json_schema_extra": {"example": {"device_token": "onesignal-player-id-here", "platform": "android"}}}


class UserProfileResponse(BaseModel):
    user_id: str
    age: Optional[int] = None
    gender: Optional[str] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    hba1c: Optional[float] = None
    activity_level: Optional[str] = None
    diet_restrictions: Optional[str] = None
    breakfast_time: Optional[str] = None
    lunch_time: Optional[str] = None
    dinner_time: Optional[str] = None
    profile_url: Optional[str] = None


class UserProfileUpdateRequest(BaseModel):
    age: Optional[int] = None
    gender: Optional[str] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    hba1c: Optional[float] = None
    activity_level: Optional[str] = None
    diet_restrictions: Optional[str] = None
    breakfast_time: Optional[str] = None
    lunch_time: Optional[str] = None
    dinner_time: Optional[str] = None
    profile_url: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {
        "age": 35,
        "gender": "Female",
        "weight": 65,
        "height": 160,
        "hba1c": 6.5,
        "activity_level": "Sedentary",
        "diet_restrictions": "Gluten Free",
        "breakfast_time": "08:30:00",
        "lunch_time": "13:00:00",
        "dinner_time": "19:30:00",
    }}}


class DailyMealItem(BaseModel):
    Pkey: Optional[int] = None
    user_id: Optional[str] = None
    WeekNo: Optional[int] = None
    Date: Optional[str] = None
    Timings: Optional[str] = None
    Food_Name: Optional[str] = None
    Food_Name_desc: Optional[str] = None
    Food_Qty: Optional[float] = None
    R_desc: Optional[str] = None
    Energy_kcal: Optional[float] = None
    GL: Optional[float] = None

    model_config = {"extra": "allow"}


class TimingSummary(BaseModel):
    timing: str
    total_kcal: Optional[float] = None
    total_gl: Optional[float] = None


class DailyPlanResponse(BaseModel):
    date: str
    meals: List[DailyMealItem]
    total_kcal: Optional[float] = None
    total_gl: Optional[float] = None
    by_timing: List[TimingSummary] = []


class ReplacementsResponse(BaseModel):
    date: str
    day: int
    meal_slot: MealSlot
    alternatives: List[List[RecipeWithQty]]


class ActivityLogResponse(BaseModel):
    status: str
    activity_id: str


class RecallLogResponse(BaseModel):
    status: str
    recall_ids: List[str]


class RecallImageResponse(BaseModel):
    status: str
    recall_id: str
    review_id: str


class ReactionResponse(BaseModel):
    status: str


class ActivityHistoryItem(BaseModel):
    id: Optional[str] = None
    pa_name: Optional[str] = None
    duration_min: Optional[int] = None
    intensity: Optional[str] = None
    time_of_day: Optional[str] = None
    date: Optional[str] = None

    model_config = {"extra": "allow"}


class ActivityHistoryResponse(BaseModel):
    items: List[ActivityHistoryItem]
    total: int


class RecallHistoryItem(BaseModel):
    id: Optional[str] = None
    date: Optional[str] = None
    meal_slot: Optional[str] = None
    did_eat_as_planned: Optional[bool] = None
    food_name: Optional[str] = None
    food_qty: Optional[float] = None
    r_desc: Optional[str] = None
    energy_kcal: Optional[float] = None
    notes: Optional[str] = None

    model_config = {"extra": "allow"}


class RecallHistoryResponse(BaseModel):
    items: List[RecallHistoryItem]
    total: int


class ReactionItem(BaseModel):
    id: Optional[str] = None
    date: Optional[str] = None
    meal_slot: Optional[str] = None
    recipe_codes: Optional[list] = None
    reaction: Optional[str] = None

    model_config = {"extra": "allow"}


class ReactionsListResponse(BaseModel):
    items: List[ReactionItem]
    total: int


class WebReactionType(str, Enum):
    LIKED = "liked"
    DISLIKED = "disliked"


class RecipeReactionRequest(BaseModel):
    plan_id: str
    recipe_code: str
    reaction: ReactionType
    date: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {"plan_id": "abc-123", "recipe_code": "A001745", "reaction": "like", "date": "2026-05-29"}}}


class WebMealReactionRequest(BaseModel):
    plan_id: str
    recommendation_pkey: Optional[int] = None
    date: Optional[str] = None
    timings: Optional[str] = None
    reaction: WebReactionType

    model_config = {"json_schema_extra": {"example": {
        "plan_id": "abc-123",
        "recommendation_pkey": None,
        "date": "2026-05-22",
        "timings": "Breakfast",
        "reaction": "liked",
    }}}


class WebReactionItem(BaseModel):
    id: Optional[int] = None
    plan_id: Optional[str] = None
    recommendation_pkey: Optional[int] = None
    date: Optional[str] = None
    timings: Optional[str] = None
    user_id: Optional[str] = None
    reaction: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"extra": "allow"}


class WebReactionsListResponse(BaseModel):
    items: List[WebReactionItem]
    total: int
