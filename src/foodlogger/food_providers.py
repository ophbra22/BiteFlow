"""Attributed candidates; never synthesized composition or a global user catalog."""

import hashlib
import json
from functools import lru_cache
from importlib.resources import files

from foodlogger.analysis_schemas import ReferenceFood
from foodlogger.nutrition_reference import ReferenceCatalog
from foodlogger.products import LookupUnavailable, OpenFoodFactsClient, ProductNotFound

REGIONAL_ALIASES = {
    "פיתה": "pita bread",
    "פיתות": "pita bread",
    "חומוס": "hummus",
    "טחינה": "tahini",
    "פלאפל": "falafel",
    "שקשוקה": "shakshuka",
    "סביח": "sabich",
    "שניצל": "chicken breaded fried",
    "סלט ישראלי": "israeli salad",
    "בורקס": "bourekas",
    "מלאווח": "malawach",
    "מלוואח": "malawach",
    "ג׳חנון": "jachnun",
    "ג'חנון": "jachnun",
    "גחנון": "jachnun",
    "קוטג׳": "cottage cheese",
    "קוטג'": "cottage cheese",
    "קוטג": "cottage cheese",
    "לבנה": "labneh",
    "שווארמה": "shawarma",
    "קבב": "kebab",
}
RECIPE_DEPENDENT = frozenset(
    {
        "hummus",
        "tahini",
        "falafel",
        "shakshuka",
        "sabich",
        "chicken breaded fried",
        "israeli salad",
        "bourekas",
        "malawach",
        "jachnun",
        "shawarma",
        "kebab",
    }
)


def regional_query(query):
    return REGIONAL_ALIASES.get(query.strip().lower(), query.strip().lower())


@lru_cache(maxsize=1)
def reference_version():
    # Serving seeds pin this hash, so a CRLF checkout must not change it. The extract is
    # stored with LF endings, and JSON strings cannot hold a raw CR, so its value is unchanged.
    data = files("foodlogger").joinpath("data/usda_reference.json").read_bytes()
    return "sha256:" + hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def validate_extract(data):
    errors = []
    if data.get("basis") != "per 100 g edible portion":
        errors.append("Expected per 100 g edible portion.")
    seen = set()
    records = data.get("foods", [])
    if not isinstance(records, list) or not records:
        errors.append("Expected nonempty foods list.")
        records = []
    for index, record in enumerate(records):
        try:
            ref = ReferenceFood.model_validate(
                {
                    **record,
                    "source_url": "https://fdc.nal.usda.gov/food-details/"
                    + record["id"].removeprefix("fdc:")
                    + "/nutrients",
                }
            )
            if ref.id in seen:
                raise ValueError("Duplicate identity")
            seen.add(ref.id)
            for key, value in ref.nutrition.model_dump().items():
                if value is not None and not 0 <= value <= (1000 if key == "calories" else 100):
                    raise ValueError("Out-of-range nutrition")
        except (ValueError, TypeError, KeyError):
            errors.append(f"Invalid record at index {index}.")
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {
        "valid": not errors,
        "count": len(records),
        "errors": errors,
        "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
    }


class FoodProviders:
    def __init__(self, catalog=None, products=None):
        self.catalog = catalog or ReferenceCatalog()
        self.products = products or OpenFoodFactsClient()

    def search(self, query, barcode=None):
        normalized = regional_query(query)
        result = {
            "foods": [],
            "exact_product": None,
            "source_status": {"usda": "available"},
            "recipe_dependent": normalized in RECIPE_DEPENDENT,
            "precedence": ["exact_barcode", "selected_private_product", "generic_reference"],
        }
        if barcode:
            try:
                result["exact_product"] = self.products.lookup(barcode)
                result["source_status"]["open_food_facts"] = "available"
            except ProductNotFound:
                result["source_status"]["open_food_facts"] = "not_found"
            except LookupUnavailable:
                result["source_status"]["open_food_facts"] = "unavailable"
        for ref in self.catalog.search(normalized, limit=8):
            result["foods"].append(
                {
                    "reference": ref.model_dump(),
                    "version": reference_version(),
                    "license": "CC0",
                    "display_source": f"{ref.source} · {ref.data_type} · {ref.id}",
                    "requires_confirmation": True,
                }
            )
        return result
