"""Public-domain USDA reference retrieval and auditable decimal portion arithmetic.

Matching scores rank records; they are NOT calibrated probabilities. A record is
never invented and a missing value never becomes zero. No photo or user data in cache.
"""

import json
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from importlib.resources import files

from foodlogger.analysis_schemas import ReferenceFood
from foodlogger.nutrition import NUTRIENTS

ALIASES = {
    # --- Israeli & Middle Eastern Staples ---
    "חומוס גרגירים": "chickpeas",
    "גרגירי חומוס": "chickpeas",
    "גרגרי חומוס": "chickpeas",
    "טחינה גולמית": "tahini",
    "שניצל עוף": "chicken breaded fried",
    "שניצלים": "chicken breaded fried",
    "שניצל": "chicken breaded fried",
    "פיתה כוסמין": "spelt pita bread",
    "פיתה מלאה": "pita bread whole wheat",
    "פיתה מחיטה מלאה": "pita bread whole wheat",
    "פיתות": "pita bread",
    "פיתה": "pita bread",
    "חלות": "challah",
    "חלה": "challah",
    "חומוס": "hummus",
    "פלאפל": "falafel",
    "טחינה": "tahini",
    "קוסקוס": "couscous cooked",
    "בורגול": "bulgur",
    "טאבולה": "tabbouleh",
    "חלבה": "halavah",
    "בקלאווה": "baklava",
    "בקلاווה": "baklava",
    "מצות": "matzo",
    "מצה": "matzo",
    "צזיקי": "tzatziki",
    "ציזיקי": "tzatziki",
    "שווארמה": "shawarma",
    "שקשוקה": "shakshuka",
    "סביח": "sabich",
    "בורקס": "bourekas",
    "מלאווח": "malawach",
    "מלוואח": "malawach",
    "ג׳חנון": "jachnun",
    "ג'חנון": "jachnun",
    "גחנון": "jachnun",
    "קובה": "kubbeh",
    "במבה": "bamba",
    "פתיתים": "ptitim",
    "לבנה": "labneh",
    "קבב": "kebab",
    "זעתר": "zaatar",
    # --- Eggs & Omelets ---
    "ביצה מקושקשת": "egg scrambled",
    "ביצים מקושקשות": "egg scrambled",
    "ביצה קשה": "egg hard boiled",
    "ביצים קשות": "egg hard boiled",
    "ביצה עלומה": "egg poached",
    "ביצים עלומות": "egg poached",
    "ביצת עין": "egg fried",
    "ביצי עין": "egg fried",
    "חביתות": "egg omelet",
    "חביתה": "egg omelet",
    "ביצים": "eggs",
    "ביצה": "egg",
    # --- Vegetables & Greens ---
    "תפוחי אדמה": "potato",
    "תפוח אדמה": "potato",
    "שעועית ירוקה": "green beans",
    "בצל ירוק": "scallion",
    "פלפל אדום": "pepper sweet red",
    "פלפל ירוק": "pepper sweet green",
    "פלפל צהוב": "pepper sweet yellow",
    "פלפל חריף": "pepper hot",
    "עגבניות שרי": "tomatoes",
    "עגבנייה": "tomato",
    "עגבניה": "tomato",
    "עגבניות": "tomatoes",
    "מלפפון חמוץ": "pickle cucumber",
    "מלפפונים חמוצים": "pickle cucumber",
    "מלפפונים": "cucumber",
    "מלפפון": "cucumber",
    "גזרים": "carrots",
    "גזר": "carrot",
    "בצלים": "onions",
    "בצל": "onion",
    "שום": "garlic",
    "חסה": "lettuce",
    "גמבה": "pepper sweet red",
    "פלפלים": "peppers",
    "פלפל": "pepper",
    "חצילים": "eggplant",
    "חציל": "eggplant",
    "קישואים": "zucchini",
    "קישוא": "zucchini",
    "זוקיני": "zucchini",
    "כרוב אדום": "cabbage red",
    "כרוב סגול": "cabbage red",
    "כרוב": "cabbage",
    "כרובית": "cauliflower",
    "ברוקולי": "broccoli",
    "תרד": "spinach",
    "פטריות": "mushrooms",
    "פטרייה": "mushroom",
    "פטריה": "mushroom",
    "אבוקדו": "avocado",
    "זיתים": "olives",
    "זית": "olive",
    "תירס": "corn",
    "בטטות": "sweet potato",
    "בטטה": "sweet potato",
    "סלק": "beet",
    "אפונה ירוקה": "green peas",
    "אפונה": "green peas",
    "סלרי": "celery",
    "צנונית": "radish",
    "צנון": "radish",
    "קולורבי": "kohlrabi",
    "אספרגוס": "asparagus",
    "ארטישוק": "artichoke",
    "דלעת": "pumpkin",
    "כרישה": "leeks",
    "שומר": "fennel",
    "במיה": "okra",
    "פטרוזיליה": "parsley",
    "כוסברה": "coriander",
    "רוקט": "arugula",
    "ארוגולה": "arugula",
    # --- Fruits ---
    "תפוחי עץ": "apples",
    "תפוח עץ": "apple",
    "תפוחים": "apples",
    "תפוח": "apple",
    "בננות": "bananas",
    "בננה": "banana",
    "תפוזים": "oranges",
    "תפוז": "orange",
    "אבטיח": "watermelon",
    "מלון": "cantaloupe",
    "ענבים": "grapes",
    "תות שדה": "strawberries",
    "תותים": "strawberries",
    "תות": "strawberry",
    "אוכמניות": "blueberries",
    "פטל": "raspberries",
    "אפרסקים": "peaches",
    "אפרסק": "peach",
    "נקטרינה": "nectarine",
    "מנגו": "mango",
    "אגסים": "pears",
    "אגס": "pear",
    "שזיפים": "plums",
    "שזיף": "plum",
    "משמשים": "apricots",
    "משמש": "apricot",
    "אננס": "pineapple",
    "קיווי": "kiwi",
    "רימון": "pomegranate",
    "תאנים": "figs",
    "תאנה": "fig",
    "תמרים": "date",
    "תמר": "date",
    "דובדבנים": "cherries sweet",
    "דובדבן": "cherries sweet",
    "לימון": "lemon",
    "ליים": "lime",
    "אשכולית": "grapefruit",
    "קלמנטינות": "clementine",
    "קלמנטינה": "clementine",
    "מנדרינה": "tangerine",
    "אפרסמון": "persimmon",
    "גויאבה": "guava",
    "פפאיה": "papaya",
    "צימוקים": "raisins",
    # --- Poultry, Meat & Fish ---
    "חזה עוף": "chicken breast",
    "ירך עוף": "chicken thigh",
    "פרגיות": "chicken thigh",
    "פרגית": "chicken thigh",
    "שוק עוף": "chicken drumstick",
    "שוקיים עוף": "chicken drumstick",
    "כנפי עוף": "chicken wing",
    "כנפיים עוף": "chicken wing",
    "חזה הודו": "turkey light meat",
    "הודו": "turkey",
    "עוף": "chicken",
    "בשר טחון": "beef ground",
    "בקר טחון": "beef ground",
    "סטייק בקר": "beef steak",
    "סטייק": "steak",
    "בשר בקר": "beef",
    "בקר": "beef",
    "כבש": "lamb",
    "טלה": "lamb",
    "עגל": "veal",
    "נקניקיות": "hot dog",
    "נקניקייה": "hot dog",
    "נקניקיה": "hot dog",
    "פסטרמה": "pastrami",
    "סלמי": "salami",
    "טונה במים": "tuna canned water",
    "טונה בשמן": "tuna canned oil",
    "טונה": "tuna",
    "סלמון": "salmon",
    "אמנון": "tilapia",
    "מושט": "tilapia",
    "סרדינים": "sardines",
    "סרדין": "sardines",
    "בקלה": "cod",
    "קוד": "cod",
    "פורל": "trout",
    "לברק": "sea bass",
    "קרפיון": "carp",
    "הליבוט": "halibut",
    "שרימפס": "shrimp",
    # --- Dairy, Cheese & Plant Proteins ---
    "גבינת קוטג׳": "cottage cheese",
    "גבינת קוטג'": "cottage cheese",
    "גבינת קוטג": "cottage cheese",
    "קוטג׳": "cottage cheese",
    "קוטג'": "cottage cheese",
    "קוטג": "cottage cheese",
    "גבינה בולגרית": "feta cheese",
    "בולגרית": "feta cheese",
    "גבינת פטה": "feta cheese",
    "פטה": "feta cheese",
    "גבינה צהובה": "gouda cheese",
    "גבינת צ'דר": "cheddar cheese",
    "גבינת צ׳דר": "cheddar cheese",
    "צ'דר": "cheddar cheese",
    "צ׳דר": "cheddar cheese",
    "גבינת מוצרלה": "mozzarella cheese",
    "מוצרלה": "mozzarella cheese",
    "גבינת ריקוטה": "ricotta cheese",
    "ריקוטה": "ricotta cheese",
    "גבינת פרמזן": "parmesan cheese",
    "פרמזן": "parmesan cheese",
    "פרמז'ן": "parmesan cheese",
    "גבינת גאודה": "gouda cheese",
    "גאודה": "gouda cheese",
    "גבינת שמנת": "cream cheese",
    "גבינת עיזים": "goat cheese",
    "גבינה לבנה": "cottage cheese",
    "גבינה": "cheese",
    "יוגורט יווני": "yogurt greek",
    "יוגורט": "yogurt",
    "חלב": "milk",
    "חמאה": "butter",
    "שמנת חמוצה": "sour cream",
    "גלידה": "ice cream",
    "קפיר": "kefir",
    "טופו": "tofu",
    # --- Bread, Grains, Pasta & Legumes ---
    "לחם חיטה מלאה": "bread whole wheat",
    "לחם דגנים מלא": "bread whole wheat",
    "לחם מלא": "bread whole wheat",
    "לחם לבן": "bread white",
    "לחם אחיד": "bread white",
    "לחם שיפון": "bread rye",
    "לחם": "bread",
    "לחמנייה": "bread roll",
    "לחמניה": "bread roll",
    "לחמניות": "bread roll",
    "בייגל": "bagel",
    "טורטיות": "tortilla",
    "טורטייה": "tortilla",
    "טורטיה": "tortilla",
    "קרואסון": "croissant",
    "אורז לבן": "white rice cooked",
    "אורז מלא": "brown rice cooked",
    "אורז בסמטי": "white rice cooked",
    "אורז יסמין": "white rice cooked",
    "אורז": "rice cooked",
    "ספגטי": "pasta cooked",
    "פסטה": "pasta cooked",
    "מקרוני": "macaroni cooked",
    "אטריות": "noodles cooked",
    "נודלס": "noodles cooked",
    "קינואה": "quinoa cooked",
    "דייסת שיבולת שועל": "oatmeal",
    "שיבולת שועל": "oatmeal",
    "קוואקר": "oatmeal",
    "כוסמת": "buckwheat",
    "עדשים": "lentils",
    "שעועית לבנה": "white beans",
    "שעועית שחורה": "beans black",
    "שעועית": "beans",
    "פול": "fava beans",
    "אדממה": "edamame",
    "פנקייק": "pancakes",
    "וופל בלגי": "waffle",
    "פופקורן": "popcorn",
    "בייגלה": "pretzels",
    # --- Nuts, Seeds, Oils, Condiments & Beverages ---
    "אגוזי מלך": "walnuts",
    "אגוז מלך": "walnuts",
    "אגוזי פקאן": "pecans",
    "פקאן": "pecans",
    "אגוזי קשיו": "cashews",
    "קשיו": "cashews",
    "אגוזי לוז": "hazelnuts",
    "אגוזי מקדמיה": "macadamia",
    "שקדים": "almonds",
    "שקד": "almond",
    "חמאת בוטנים": "peanut butter",
    "בוטנים": "peanuts",
    "פיסטוקים": "pistachio",
    "פיסטוק": "pistachio",
    "צנוברים": "pine nuts",
    "גרעיני חמנייה": "sunflower seeds",
    "גרעיני חמניה": "sunflower seeds",
    "גרעיני דלעת": "pumpkin seeds",
    "זרעי צ'יה": "chia seeds",
    "זרעי צ׳יה": "chia seeds",
    "צ'יה": "chia seeds",
    "זרעי פשתן": "flaxseed",
    "פשתן": "flaxseed",
    "שמן זית": "olive oil",
    "שמן קנולה": "canola oil",
    "שמן קוקוס": "coconut oil",
    "שמן שומשום": "sesame oil",
    "ושמן": "oil",
    "שמן": "oil",
    "מיונז": "mayonnaise",
    "קטשופ": "ketchup",
    "חרדל": "mustard",
    "רוטב סויה": "soy sauce",
    "חומץ": "vinegar",
    "דבש": "honey",
    "ריבה": "jam",
    "סוכר": "sugar",
    "סירופ מייפל": "syrup maple",
    "שוקולד מריר": "chocolate dark",
    "שוקולד": "chocolate",
    "קפה שחור": "coffee turkish",
    "קפה הפוך": "coffee latte",
    "קפוצ'ינו": "coffee cappuccino",
    "קפוצ׳ינו": "coffee cappuccino",
    "אספרסו": "coffee espresso",
    "נס קפה": "coffee brewed",
    "קפה": "coffee brewed",
    "תה ירוק": "tea hot leaf green",
    "תה שחור": "tea hot leaf black",
    "תה": "tea hot leaf black",
    "מיץ תפוזים": "orange juice",
    "מיץ תפוחים": "apple juice",
    "יין אדום": "wine red",
    "בירה": "beer",
    "מרק עדשים": "soup lentil",
    "מרק עוף": "soup chicken",
    "מרק עגבניות": "soup tomato",
    "סלט יווני": "greek salad",
    "סלט קיסר": "caesar salad",
    "קולסלאו": "coleslaw",
    "סלט": "salad",
    "עם": "with",
    # --- English Synonyms & Spelling Variants ---
    "schnitzel": "chicken breaded fried",
    "garbanzo": "chickpea",
    "aubergine": "eggplant",
    "courgette": "zucchini",
    "tahina": "tahini",
    "capsicum": "pepper",
    "halva": "halavah",
    "halvah": "halavah",
    "matzah": "matzo",
}
STOP = {
    "and",
    "with",
    "of",
    "the",
    "a",
    "an",
    "in",
    "or",
    "food",
    "plain",
    "fresh",
    "sliced",
    "chopped",
    "cubed",
    "cubes",
    "pieces",
}
# A mention inside a different recipe is not the requested food's composition.
RECIPE_KINDS = {
    "cookie",
    "cake",
    "pie",
    "soup",
    "sandwich",
    "pudding",
    "salad",
    "dressing",
    "sauce",
    "bread",
    "pizza",
    "juice",
    "jam",
    "butter",
    "spread",
    "candy",
    "chocolate",
    "flour",
    "powder",
    "cereal",
    "bar",
    "oil",
    "paste",
    "cracker",
    "muffin",
    "gravy",
    "burrito",
    "roll",
    "grease",
    "margarine",
    "chip",
    "quesadilla",
    "taquito",
    "congee",
    "burger",
    "glazed",
    "cider",
    "nectar",
    "dip",
    "syrup",
    "casserole",
    "souffle",
    "stick",
    "nugget",
    "cornbread",
    "kombucha",
    "bubble",
    "dog",
    "pone",
    "bran",
}
OTHER_MAIN_FOODS = {
    "chicken",
    "fish",
    "shrimp",
    "tofu",
    "bean",
    "pea",
    "milk",
    "yogurt",
    "egg",
    "cheese",
    "potato",
    "rice",
    "pasta",
    "noodle",
    "lentil",
    "carrot",
    "vegetable",
    "tomato",
    "onion",
    "corn",
}
IMPLICIT_RAW = {
    "almond",
    "walnut",
    "cashew",
    "pecan",
    "hazelnut",
    "pistachio",
    "peanut",
    "sunflower",
    "pumpkin",
    "seed",
}
CATEGORY_PREFIXES = {
    "nuts",
    "seeds",
    "mollusks",
    "crustaceans",
    "spices",
    "snacks",
    "beverages",
    "cereals",
    "cereals ready-to-eat",
    "cereals, ready-to-eat",
    "fast foods",
    "babyfood",
    "fish",
    "cheese",
    "squash",
    "soup",
    "candies",
    "crackers",
    "oil",
    "syrups",
    "sugars",
    "pickles",
}
EGG_VARIANTS = {
    "white",
    "yolk",
    "substitute",
    "meat",
    "deviled",
    "benedict",
    "creamed",
    "yung",
    "goose",
    "duck",
    "quail",
    "turkey",
    "spray",
    "restaurant",
}
EGG_METHODS = {"omelet", "scrambled", "poached", "fried", "boiled"}
COOKED = {
    "cooked",
    "grilled",
    "roasted",
    "fried",
    "boiled",
    "steamed",
    "baked",
    "stewed",
    "braised",
    "rotisserie",
}

_ALIAS_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(w) for w in sorted(ALIASES, key=len, reverse=True))
    + r")(?!\w)"
)
_IRREGULAR = {
    "omelette": "omelet",
    "omelettes": "omelet",
    "potatoes": "potato",
    "tomatoes": "tomato",
    "berries": "berry",
    "strawberries": "strawberry",
    "blueberries": "blueberry",
    "raspberries": "raspberry",
    "blackberries": "blackberry",
    "cherries": "cherry",
    "peaches": "peach",
    "radishes": "radish",
}
_QUALIFIER_WORDS = {
    "babyfood",
    "toddler",
    "infant",
    "dried",
    "powder",
    "dehydrated",
    "canned",
    "skin",
    "battered",
    "breaded",
    "sweetened",
    "imitation",
    "substitute",
    "vegan",
    "glutinous",
    "liver",
    "turkey",
    "sweet",
    "solution",
    "flavored",
    "salted",
    "multigrain",
    "meatless",
    "canadian",
    "beef",
    "bits",
    "pickled",
    "scalloped",
    "creamed",
    "candied",
    "blossom",
    "beverage",
    "deli",
    "prepackaged",
    "restaurant",
    "chinese",
    "puerto",
    "alaska",
    "lomi",
    "tartare",
    "teriyaki",
    "salisbury",
    "kiev",
    "curry",
    "barbecue",
    "bbq",
    "stuffed",
    "wasabi",
    "wild",
    "parboiled",
    "zucchini",
    "pumpkin",
    "fruit",
    "nut",
    "almond",
    "sesame",
    "orange",
    "soy",
    "barley",
    "oatmeal",
    "black",
    "wing",
    "pepper",
    "swiss",
    "spanish",
    "light",
    "diet",
    "reduced",
    "nonfat",
    "squash",
    "raab",
    "grain",
    "navajo",
    "ground",
    "feet",
    "neck",
    "giblet",
    "gizzard",
    "heart",
    "back",
    "tail",
    "thigh",
    "drumstick",
}
_FISH_SPECIES = {
    "salmon",
    "tuna",
    "tilapia",
    "sardine",
    "cod",
    "halibut",
    "trout",
    "carp",
    "bass",
    "mackerel",
    "herring",
    "anchovy",
}
_CHEESE_KINDS = {
    "feta",
    "cheddar",
    "mozzarella",
    "ricotta",
    "gouda",
    "edam",
    "parmesan",
    "cottage",
}


def tokens(text):
    from foodlogger.food_providers import regional_query

    text = regional_query(text)
    # Translate multiword foods before their component words (e.g. ביצה קשה).
    text = _ALIAS_PATTERN.sub(lambda m: ALIASES[m.group(0)], text)
    return {
        _IRREGULAR.get(word, word[:-1] if word.endswith("s") and len(word) > 3 else word)
        for word in re.findall(r"[^\W_]+", text)
        if word not in STOP
    }


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def subject_tokens(name):
    parts = [p.strip() for p in name.lower().split(",")]
    # Some USDA headings classify the food before naming it.
    if len(parts) > 2 and parts[0] == "squash" and parts[1] == "summer":
        subject = parts[2]
    elif len(parts) > 1 and parts[0] in CATEGORY_PREFIXES:
        subject = parts[0] + " " + parts[1]
    else:
        subject = parts[0]
    return tokens(re.split(r"\bwith\b|\bas ingredient\b", subject)[0])


def scale_nutrients(per100: dict, grams: float) -> dict:
    if isinstance(grams, bool) or not math.isfinite(grams) or not 1 <= grams <= 2000:
        raise ValueError("Use 1–2000 grams per component.")
    return {
        k: None
        if per100.get(k) is None
        else float(
            (Decimal(str(per100[k])) * Decimal(str(grams)) / 100).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
        )
        for k in NUTRIENTS
    }


def aggregate(items: list[dict]) -> dict:
    return {
        k: None
        if any(row.get(k) is None for row in items)
        else float(
            sum((Decimal(str(row[k])) for row in items), Decimal(0)).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
        )
        for k in NUTRIENTS
    }


@lru_cache(maxsize=1)
def _qualifier_sets():
    return tuple((q, tokens(q)) for q in _QUALIFIER_WORDS)


@lru_cache(maxsize=1)
def _data():
    from foodlogger.food_providers import reference_version

    payload = json.loads(files("foodlogger").joinpath("data/usda_reference.json").read_text())
    records = {
        row["id"]: ReferenceFood(
            **row,
            source_version=reference_version(),
            source_url=f"https://fdc.nal.usda.gov/food-details/{row['id'].split(':')[1]}/nutrients",
        )
        for row in payload["foods"]
    }
    index = {key: tokens(value.name) for key, value in records.items()}
    # USDA names start with the subject; a later ingredient is not that subject.
    subjects = {key: subject_tokens(value.name) for key, value in records.items()}
    frequency = {}
    for words in index.values():
        for word in words:
            frequency[word] = frequency.get(word, 0) + 1
    return records, index, frequency, subjects


class ReferenceCatalog:
    def __init__(self):
        self.records, self.index, self.frequency, self.subjects = _data()
        self._cached_search = lru_cache(maxsize=256)(self._search_ids)

    def get(self, reference_id: str) -> ReferenceFood:
        return self.records[reference_id].model_copy(deep=True)

    def _search_ids(self, query: str, preparation: str):
        words = tokens(query)
        # Implicit identities apply to queries only, never to a record merely
        # mentioning an omelet as the destination for a separate ingredient.
        if words & {"omelet", "scrambled"}:
            words.add("egg")
        if "pita" in words and "chip" not in words:
            words.add("bread")
        if "challah" in words:
            words.update({"bread", "egg"})
        if "matzo" in words:
            words.add("cracker")
        if "tzatziki" in words:
            words.add("dip")
        if words & _FISH_SPECIES:
            words.add("fish")
        if words & _CHEESE_KINDS:
            words.add("cheese")
        if words in ({"peas"}, {"pea"}):
            words.add("green")
        if words == {"spaghetti"}:
            words = {"pasta", "cooked"}
        if preparation == "unknown":
            preparation = next(
                (
                    p
                    for p in [
                        "raw",
                        "fried",
                        "grilled",
                        "roasted",
                        "boiled",
                        "steamed",
                        "baked",
                        "cooked",
                    ]
                    if p in words
                ),
                "unknown",
            )
        identity = words - COOKED - {"raw"}
        if not identity or identity <= {"meat", "vegetable", "fruit", "mixed", "dish"}:
            return ()
        # All identity terms must occur: better no result than matching tahini
        # sauce to undiluted paste, or chicken breast to chicken soup.
        results = []
        for key, record_words in self.index.items():
            if not identity <= record_words:
                continue
            name = self.records[key].name.lower()
            if "ingredient" in record_words or not identity & self.subjects[key]:
                continue
            if "egg" in words and "challah" not in words:
                if (record_words & EGG_VARIANTS) - words:
                    continue
                # Missing recipe detail is not evidence for a fat-free recipe.
                # Conversely "fat added" must never match "no added fat".
                if (
                    re.search(r"\bno (?:added fat|fat added)\b", name)
                    and not {
                        "no",
                        "added",
                        "fat",
                    }
                    <= words
                ):
                    continue
                if "fat free" in name and not {"fat", "free"} <= words:
                    continue
            if (record_words & RECIPE_KINDS) - words:
                continue
            if (record_words & OTHER_MAIN_FOODS) - words:
                continue
            if "rendered fat" in name and "fat" not in words:
                continue
            if preparation == "raw" and "raw" not in record_words and not identity <= IMPLICIT_RAW:
                continue
            if preparation in COOKED and (
                "raw" in record_words
                or "uncooked" in record_words
                or "unprepared" in record_words
            ):
                continue
            if (preparation == "raw" or "raw" in words) and record_words & COOKED:
                continue
            if preparation in {"fried", "grilled", "roasted", "boiled", "steamed", "baked"}:
                incompatible = record_words & {"fried", "grilled", "roasted", "boiled", "steamed"}
                if incompatible and preparation not in incompatible:
                    continue
            score = 8 - 0.3 * len(record_words - identity - {"nf", "nfs"})
            if preparation in record_words:
                score += 0.2 if preparation == "cooked" else 3
            if "egg" in words and preparation == "cooked" and not words & EGG_METHODS:
                if "ns as to cooking method" in name:
                    score += 3
            if (
                "chicken" in words
                and preparation in {"cooked", "grilled"}
                and "ns as to cooking method" in name
            ):
                score += 2.5
            if (
                "chicken" in words
                and "ns as to part" in name
                and not (words & {"breast", "thigh", "drumstick", "wing"})
            ):
                score += 2.0
            if preparation == "raw" and "unroasted" in record_words:
                score += 3
            if (
                preparation == "unknown"
                and "raw" in record_words
                and not (
                    record_words
                    & {"fish", "chicken", "beef", "pork", "turkey", "lamb", "veal"}
                )
            ):
                score += 0.5
            if "brewed" in record_words and "coffee" in words:
                score += 1.5
            if {"hot", "leaf", "black"} <= record_words and "tea" in words:
                score += 1.5
            if (
                "bread" in words
                and len(identity) == 1
                and "white" in record_words
                and len(record_words) == 2
            ):
                score += 1.5
            if "steak" in words and "beef" in record_words and "nf" in record_words:
                score += 2.0
            if "walnut" in words and "excluding" in record_words:
                score += 2.5
            if "fried" in record_words and preparation != "fried" and "fried" not in words:
                score -= 3.0
            if (
                "green" in record_words
                and "green" not in words
                and ("beet" in words or "cauliflower" in words)
            ):
                score -= 4.0
            if "cauliflower" in record_words and "cauliflower" not in words:
                score -= 4.0
            if "broccoli" in record_words and "broccoli" not in words:
                score -= 4.0
            if "fat added" in name and "fat" not in words:
                score -= 1.5
            score += 0.1 if preparation in COOKED and record_words & COOKED else 0
            # Avoid subtly different manufactured/baby/dried foods for generic meals.
            for qualifier, q_tokens in _qualifier_sets():
                if q_tokens & record_words and not q_tokens <= words:
                    if qualifier == "black" and ("tea" in words or "coffee" in words):
                        continue
                    if qualifier == "light" and "turkey" in words:
                        continue
                    if qualifier == "zucchini" and "zucchini" in words:
                        continue
                    if qualifier == "squash" and "zucchini" in words:
                        continue
                    if qualifier == "canned" and ("sardine" in words or "tuna" in words):
                        continue
                    if qualifier == "ground" and "beef" in words:
                        continue
                    if qualifier == "skin" and (
                        "ns as to cooking method" in name or "includes skin" in name
                    ):
                        score -= 0.5
                        continue
                    score -= 4
            if "not specified" in name:
                score -= 0.5
            if score > 0:
                results.append((score, key))
        return tuple(key for _, key in sorted(results, reverse=True)[:8])

    def search(self, query: str, preparation: str = "unknown", limit: int = 5):
        return [self.get(key) for key in self._cached_search(query[:160], preparation)[:limit]]
