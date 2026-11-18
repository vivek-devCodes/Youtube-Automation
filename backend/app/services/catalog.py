"""Static catalogs: niches, languages, durations, budget modes."""

NICHES = [
    # slug, name, YouTube categoryId, kids, seed keywords
    ("childrens-entertainment", "Children's entertainment", "1", True, ["kids story", "cartoon story", "bedtime story"]),
    ("nursery-rhymes", "Nursery rhymes", "1", True, ["nursery rhyme", "kids song", "learning song"]),
    ("education", "Education", "27", False, ["explained", "how it works", "learn"]),
    ("science-technology", "Science and technology", "28", False, ["science", "technology", "space", "physics"]),
    ("artificial-intelligence", "Artificial intelligence", "28", False, ["AI", "artificial intelligence", "machine learning", "chatbot"]),
    ("sports", "Sports", "17", False, ["sports", "athlete", "tournament"]),
    ("cricket", "Cricket", "17", False, ["cricket", "IPL", "Test match", "ODI", "T20"]),
    ("football", "Football", "17", False, ["football", "soccer", "Premier League", "FIFA"]),
    ("memes-comedy", "Memes and comedy", "23", False, ["funny", "comedy", "relatable"]),
    ("facts-stories", "Facts and interesting stories", "27", False, ["facts", "did you know", "story", "history"]),
    ("motivation", "Motivation", "22", False, ["motivation", "habits", "discipline", "success"]),
    ("business", "Business", "27", False, ["business", "startup", "company", "brand"]),
    ("finance-education", "Finance education", "27", False, ["personal finance", "investing", "savings", "stock market"]),
    ("history", "History", "27", False, ["history", "ancient", "empire", "war"]),
    ("travel", "Travel", "19", False, ["travel", "destination", "places to visit"]),
    ("food", "Food", "26", False, ["recipe", "food", "street food", "cooking"]),
    ("gaming", "Gaming", "20", False, ["gaming", "video game", "game update"]),
    ("entertainment-news", "Entertainment news", "24", False, ["movie", "series", "celebrity", "box office"]),
]
NICHE_BY_SLUG = {n[0]: n for n in NICHES}

LANGUAGES = {
    "en": "English", "hi": "Hindi", "hinglish": "Hinglish", "mr": "Marathi", "gu": "Gujarati", "ta": "Tamil",
    "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "bn": "Bengali", "es": "Spanish", "fr": "French", "ar": "Arabic",
}
# YouTube wants BCP-47; Hinglish is Hindi audio written in Latin script.
YOUTUBE_LANG = {"hinglish": "hi"}

SHORT_DURATIONS = [15, 30, 45, 60, 180]
LONG_RANGES = {"3-5": (180, 300), "5-8": (300, 480), "8-12": (480, 720), "12-20": (720, 1200)}

BUDGET_MODES = {
    "free": {"label": "Free / open-source only", "llm": "ollama", "tts": "system", "image": "procedural", "video": "none"},
    "low": {"label": "Low-cost production", "llm": "gemini", "tts": "system", "image": "procedural", "video": "none"},
    "balanced": {"label": "Balanced quality and cost", "llm": "anthropic", "tts": "openai", "image": "openai", "video": "none"},
    "premium": {"label": "Premium AI generation", "llm": "anthropic", "tts": "openai", "image": "openai", "video": "comfyui"},
}

# Franchise / brand names that must not appear as characters or imitation in generated content.
DEFAULT_TRADEMARK_BLOCKLIST = [
    "peppa pig", "cocomelon", "paw patrol", "disney", "pixar", "marvel", "spider-man", "spiderman", "batman", "superman",
    "pokemon", "pokémon", "mickey mouse", "frozen elsa", "minecraft steve", "mario", "sonic the hedgehog", "bluey",
    "chhota bheem", "motu patlu", "doraemon", "shinchan", "harry potter", "star wars", "barbie", "hello kitty",
]

KIDS_BANNED_TERMS = ["blood", "kill", "gun", "weapon", "scary", "horror", "drugs", "alcohol", "violence", "dead body", "sexy"]

DEFAULT_TREND_WEIGHTS = {
    "view_velocity": 0.25, "engagement": 0.20, "search_interest": 0.20,
    "freshness": 0.15, "relevance": 0.10, "feasibility": 0.10,
}

# YouTube Partner Program thresholds (verify against YouTube Help — they change).
YPP_TARGETS = {
    "early_access": {"subscribers": 500, "public_uploads_90d": 3, "watch_hours_12m": 3000, "shorts_views_90d": 3_000_000},
    "full": {"subscribers": 1000, "watch_hours_12m": 4000, "shorts_views_90d": 10_000_000},
}
