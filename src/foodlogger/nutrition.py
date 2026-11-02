"""A deliberately small, auditable catalog of estimated nutrition."""

import json
import math
from importlib.resources import files

NUTRIENTS = ("calories", "protein", "carbs", "fat")


class Catalog:
    def __init__(self):
        data = json.loads(
            files("foodlogger").joinpath("data/foods.json").read_text(encoding="utf-8")
        )
        self.source = data["source"]
        self.reference = data["reference"]
        self.foods = {food["id"]: food for food in data["foods"]}

    def get(self, food_id: str) -> dict:
        return self.foods[food_id].copy()

    def estimate(self, food_id: str, grams: float) -> dict[str, float]:
        if not math.isfinite(grams) or not 1 <= grams <= 2000:
            raise ValueError("Portion must be between 1 and 2000 grams.")
        food = self.get(food_id)
        return {key: round(food[key] * grams / 100, 1) for key in NUTRIENTS}
