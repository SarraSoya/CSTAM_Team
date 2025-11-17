from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient
import random, json, os, math
from typing import List

app = FastAPI(
    title="Fitness Pipeline API",
    description="Pipeline: Load users → Assign targets → Generate monthly plans → MongoDB",
    version="3.1.0",
    docs_url="/",  # Swagger UI at root
)

# ------------------------
# MongoDB connection
# ------------------------
client = MongoClient("mongodb://root:example@localhost:27017/")
db = client["fitness_db"]

raw_collection = db["users_raw"]             # Stage 1
target_collection = db["users_with_targets"] # Stage 2
plan_collection = db["users_monthly_plan"]   # Stage 3

# ------------------------
# Pydantic Model for manual input
# ------------------------
class TargetInput(BaseModel):
    start_weight: float
    target_weight: float
    pace: str
    goal: str


# ------------------------
# Stage 1: Load raw users.json
# ------------------------
@app.post("/load-users")
def load_users(file_path: str = "users.json"):
    """Load users.json into MongoDB (users_raw)."""
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"{file_path} not found")

    with open(file_path, "r") as f:
        users = json.load(f)

    if not users:
        raise HTTPException(status_code=400, detail="users.json is empty")

    raw_collection.delete_many({})
    raw_collection.insert_many(users)

    return {"message": f"✅ Loaded {len(users)} users into MongoDB (users_raw)"}


# ------------------------
# Stage 2: Assign goals & targets (automatic)
# ------------------------
def assign_goals(users: List[dict]) -> List[dict]:
    updated_users = []
    for user in users:
        start_weight = user.get("weight")
        if start_weight is None:
            continue
        try:
            start_weight = float(start_weight)
        except Exception:
            continue

        # Goal assignment
        if start_weight <= 60:
            goal = "Gain Weight"
        elif start_weight >= 70:
            goal = "Lose Weight"
        else:
            goal = random.choice(["Maintain Weight", "Gain Muscle"])

        target_weight = start_weight
        pace = None

        if goal == "Lose Weight":
            target_weight = round(start_weight - random.uniform(1, 10), 1)
            pace = random.choice(["Quickly", "Normal"])
        elif goal == "Gain Weight":
            target_weight = round(start_weight + random.uniform(1, 10), 1)
            pace = random.choice(["Quickly", "Normal"])
        elif goal == "Gain Muscle":
            target_weight = round(start_weight + random.uniform(1, 8), 1)
            pace = random.choice(["Quickly", "Normal"])

        user["goal"] = goal
        user["start_weight"] = start_weight
        user["target_weight"] = target_weight
        if pace:
            user["pace"] = pace

        updated_users.append(user)
    return updated_users


@app.post("/targets/users")
def assign_and_store_targets():
    """Assign goals for users in users_raw → store in users_with_targets."""
    users = list(raw_collection.find({}, {"_id": 0}))
    if not users:
        raise HTTPException(status_code=400, detail="No users found in users_raw. Load users first.")

    updated_users = assign_goals(users)
    target_collection.delete_many({})
    target_collection.insert_many(updated_users)

    return {"message": f"✅ Assigned targets for {len(updated_users)} users and saved into users_with_targets"}


@app.get("/targets/users")
def list_targets():
    """See all users with their goal + target values."""
    return list(target_collection.find({}, {"_id": 0}))


@app.post("/targets/users/{user_id}")
def submit_user_target(user_id: str, target: TargetInput):
    """
    Submit target info for a single user (manual input).
    """
    raw_user = raw_collection.find_one({"user_id": user_id}, {"_id": 0})
    if not raw_user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found in users_raw")

    # Merge user raw data with provided target
    updated_user = {
        "user_id": user_id,
        "start_weight": target.start_weight,
        "target_weight": target.target_weight,
        "pace": target.pace,
        "goal": target.goal,
    }

    # Save to users_with_targets
    target_collection.update_one({"user_id": user_id}, {"$set": updated_user}, upsert=True)

    return {"message": f"✅ Target saved for user {user_id}", "user": updated_user}


# ------------------------
# Stage 3: Generate monthly plan
# ------------------------
def get_base_calories(weight):
    if weight <= 50:
        return 1700
    elif weight <= 60:
        return 2000
    elif weight <= 70:
        return 2200
    else:
        return 2400


@app.post("/generate-plans")
def generate_monthly_plan():
    """Generate monthly plans from users_with_targets and save to MongoDB (users_monthly_plan)."""
    users = list(target_collection.find({}, {"_id": 0}))

    if not users:
        raise HTTPException(status_code=400, detail="No users found in users_with_targets. Assign targets first.")

    plans = []
    for user in users:
        goal = user["goal"]
        pace = user.get("pace", "Normal")
        start = user["start_weight"]
        target = user["target_weight"]

        weight_diff = round(target - start, 1)
        total_calories_needed = abs(weight_diff) * 7700

        # Duration
        if goal == "Maintain Weight":
            duration_months = 12
        else:
            duration_months = max(1, math.ceil(abs(weight_diff) / 5) * (1 if pace == "Quickly" else 3))

        days = duration_months * 30
        base_calories = get_base_calories(start)

        # Daily change
        daily_change = total_calories_needed / days if days > 0 else 0
        if goal == "Lose Weight":
            daily_change = min(daily_change, 500)
        elif goal in ["Gain Weight", "Gain Muscle"]:
            daily_change = min(daily_change, 500)

        # Monthly plan
        monthly_plan = {}
        if goal == "Lose Weight":
            for m in range(1, duration_months + 1):
                calories = round(base_calories - daily_change - (m - 1) * 50, 1)
                if calories < 1500:
                    calories = 1500
                monthly_plan[f"month{m}"] = {
                    "calories_per_day": calories,
                    "calories_burn": round(daily_change + (m - 1) * 20, 1),
                }
        elif goal in ["Gain Weight", "Gain Muscle"]:
            for m in range(1, duration_months + 1):
                monthly_plan[f"month{m}"] = {
                    "calories_per_day": round(base_calories + daily_change + (m - 1) * 50, 1),
                    "calories_burn": random.randint(100, 200),
                }
        else:  # Maintain
            for m in range(1, duration_months + 1):
                monthly_plan[f"month{m}"] = {
                    "calories_per_day": base_calories,
                    "calories_burn": random.randint(300, 500),
                }

        plan_doc = {
            "user_id": user["user_id"],
            "goal": goal,
            "pace": pace,
            "start_weight": start,
            "target_weight": target,
            "monthly_plan": monthly_plan,
        }
        plans.append(plan_doc)

    plan_collection.delete_many({})
    plan_collection.insert_many(plans)

    return {"message": f"✅ Generated monthly plans for {len(plans)} users and saved into users_monthly_plan"}


# ------------------------
# Read endpoints
# ------------------------
@app.get("/plans/users")
def list_users():
    """Get all users with monthly plans."""
    return list(plan_collection.find({}, {"_id": 0}))


@app.get("/plans/user/{user_id}")
def get_user(user_id: str):
    """Get a single user's monthly plan."""
    user = plan_collection.find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user
