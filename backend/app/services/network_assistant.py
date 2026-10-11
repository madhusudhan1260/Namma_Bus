"""
ನಮ್ಮ Bus assistant — grounded only in real data: the imported BMTC GTFS network (routes, stops, journeys), the live
BMTC feed (via NammaRoute) and the BMTC stage-fare chart. No language model and nothing invented: no made-up
buses, arrival times, crowding or delays. When something is not in the data it says so.

Pipeline:  normalize()  →  classify() → Intent(name, slots)  →  handler (reads the injected Sources)

`classify` is pure and deterministic, so it is measured against a labelled question set
(tests/assistant_eval_set.py) — English, Kanglish and Kannada script.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Language resources
# ---------------------------------------------------------------------------

VEHICLE_RE = re.compile(r"\bKA\s?-?\s?\d{2}\s?-?\s?[A-Z]{1,2}\s?-?\s?\d{3,4}\b", re.I)
ROUTE_RE = re.compile(r"\b([A-Z]{0,5}-?\d{1,4}[A-Z]{0,3}(?:-[A-Z0-9]{1,4})?)\b", re.I)

# Common spellings / nicknames → the names used in the BMTC stop data
PLACE_ALIASES: Dict[str, str] = {
    r"majestic|kbs|kempegowda bus stand|ಮೆಜೆಸ್ಟಿಕ್|ಮೆಜೆಸ್ಟಿಕ್ ಬಸ್ ನಿಲ್ದಾಣ": "Kempegowda Bus Station",
    r"(?:central )?silk ?board|ಸಿಲ್ಕ್ ?ಬೋರ್ಡ್": "Central Silk Board",
    r"airport|kia|bial|kempegowda (?:international )?airport|ವಿಮಾನ ನಿಲ್ದಾಣ|ಏರ್ ?ಪೋರ್ಟ್": "Kempegowda International Airport",
    r"yeshwant?h?pur(?:a)?|yeshvantpur|yesvantpur|ಯಶವಂತಪುರ": "Yeshwanthapura",
    r"k\.? ?r\.? ?puram|krishnarajapura(?:m)?|ಕೆ ?ಆರ್ ?ಪುರಂ": "K R Puram",
    r"malleswaram|malleshwaram|ಮಲ್ಲೇಶ್ವರಂ": "Malleshwaram",
    r"kalyan ?nagar|kalyananagar|ಕಲ್ಯಾಣ ?ನಗರ": "Kalyananagara",
    r"white ?field|ವೈಟ್ ?ಫೀಲ್ಡ್": "White Field",
    r"e[- ]?city|electronic ?city|ಎಲೆಕ್ಟ್ರಾನಿಕ್ ?ಸಿಟಿ": "Electronic City",
    r"shivaji ?nagar|shivajinagara|ಶಿವಾಜಿ ?ನಗರ": "Shivajinagara Bus Station",
    r"indira ?nagar|ಇಂದಿರಾ ?ನಗರ": "Indiranagara",
    r"hebbal|ಹೆಬ್ಬಾಳ": "Hebbala",
    r"jayanagar|ಜಯನಗರ": "Jayanagar",
    r"banashankari|ಬನಶಂಕರಿ": "Banashankari",
    r"koramangala|kormangala|ಕೋರಮಂಗಲ": "Koramangala",
    r"marathahalli|marthahalli|ಮಾರತ್ತಹಳ್ಳಿ": "Marathahalli",
    r"kengeri|ಕೆಂಗೇರಿ": "Kengeri",
    r"vijaya? ?nagara?|ವಿಜಯ ?ನಗರ": "Vijayanagara",
    r"rajaji ?nagara?|ರಾಜಾಜಿ ?ನಗರ": "Rajajinagara",
    r"mg road|m\.g\. road|ಎಂ ?ಜಿ ?ರಸ್ತೆ": "MG Road",
    r"btm(?: layout)?": "BTM Layout",
    r"hsr(?: layout)?": "HSR Layout",
}
_ALIAS_RES = [(re.compile(rf"(?<![\wಀ-೿])(?:{k})(?![\wಀ-೿])", re.I), v) for k, v in PLACE_ALIASES.items()]

FARE_WORDS = r"fare|fares|price|cost|charge|how much|ticket (?:price|cost|rate)|rate|estu|eshtu|ಎಷ್ಟು|ದರ|ಬೆಲೆ|ಶುಲ್ಕ"
CHILD_WORDS = r"child|children|kid|kids|ಮಕ್ಕಳ|ಮಗು"
SENIOR_WORDS = r"senior|elderly|old age|ಹಿರಿಯ"
TIMING_WORDS = r"when|timing|timings|time|schedule|next bus|frequency|first bus|last bus|yavaga|ಯಾವಾಗ|ಸಮಯ|ವೇಳಾಪಟ್ಟಿ"
LIVE_WORDS = r"where|live|track|running|location|now|ellide|ಎಲ್ಲಿದೆ|ಲೈವ್"

# Fillers that may lead/trail a place name in a question (removed only at the edges, never inside a name)
_LEAD = (r"(?:please|pls|can you|could you|tell me|show me|i want to|i need to|how (?:do|can) i|how to|what is the|what's the|whats the|"
         r"senior citizens?|seniors?|child(?:ren)?|kids?|student|travel|"
         r"which bus(?:es)?|what bus(?:es)?|is there a bus|any bus(?:es)?|bus(?:es)?|route(?:s)?|fare|price|cost|ticket|the|a|an|"
         r"go|get|reach|travel|from|to|for|ಯಾವ ಬಸ್|ಬಸ್)\s+")
_TRAIL = (r"\s+(?:please|pls|bus(?:es)?|stop|bus stop|stand|fare|price|cost|ticket|tickets|route|hogodu|hogbeku|hogodu hege|hege|hegey|"
          r"estu|eshtu|ಎಷ್ಟು|ದರ|ಟಿಕೆಟ್|ಬೆಲೆ|ಹೋಗುವುದು|ಹೋಗುವುದು ಹೇಗೆ|ಹೋಗಬೇಕು|ಹೇಗೆ|ಗೆ|ಕ್ಕೆ|ge|ki|ka|ke|yav bus|yavdu bus|ಯಾವ ಬಸ್|now|today)$")
# Question / filler words that are never a place on their own ("which" in "which bus goes to X", "how" in "how to …")
QUESTION_WORDS = {"which", "what", "how", "where", "when", "why", "who", "is", "are", "can", "could", "i", "we", "goes", "go", "get",
                  "reach", "travel", "going", "need", "want", "which bus", "what bus", "how do i", "how can i", "upload", "verify"}
NOT_A_PLACE = {"me", "my", "you", "here", "there", "women", "woman", "ladies", "students", "student", "girls", "it", "free", "home",
               "buy", "book", "ticket", "tickets", "pass", "bus", "buses", "go", "reach", "ಮಹಿಳೆಯರಿಗೆ", "ಮಹಿಳೆಯರು", "know"}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("→", " to ").replace("->", " to ").replace("–", "-").replace("—", "-")
    t = re.sub(r"[?!.,;:\"“”]+", " ", t)
    return " ".join(t.split())


def canonical_place(raw: str) -> str:
    p = clean_place(raw)
    for rx, name in _ALIAS_RES:
        if rx.fullmatch(p):
            return name
    for rx, name in _ALIAS_RES:  # alias inside a longer phrase, e.g. "majestic bus stand"
        if rx.search(p):
            return rx.sub(name, p)
    return p


def clean_place(raw: str) -> str:
    p = " " + (raw or "").strip() + " "
    for _ in range(8):
        before = p
        p = " " + re.sub(rf"^\s*{_LEAD}", "", p.strip(), flags=re.I) + " "
        p = re.sub(rf"{_TRAIL}", "", p.rstrip(), flags=re.I) + " "
        if p == before:
            break
    return p.strip(" -")


def normalize_route(token: str) -> str:
    """365p / 365 p / 365-p → 365-P ; 500d → 500-D ; v500d → V-500D (left as typed if unclear)."""
    t = token.strip().upper().replace(" ", "")
    m = re.fullmatch(r"(\d{1,4})-?([A-Z]{1,3})", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return t


# ---------------------------------------------------------------------------
# Intent classification (pure, deterministic, measured by tests/assistant_eval_set.py)
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    name: str
    slots: Dict[str, str] = field(default_factory=dict)


_JOURNEY_PATTERNS = [
    # explicit "… from A to B" (checked first so "which bus from A to B" splits correctly)
    re.compile(r"^(?:.*?\b)?from\s+(?P<a>.+?)\s+(?:to|till|upto|until)\s+(?P<b>.+)$", re.I),
    # "to B from A", "how to reach B from A"
    re.compile(r"^(?:.*?\b(?:to|reach|go to|get to)\s+)?(?P<b>.+?)\s+from\s+(?P<a>.+)$", re.I),
    # "from A to B", "A to B", "A till B"
    re.compile(r"^(?:.*?\bfrom\s+)?(?P<a>.+?)\s+(?:to|till|upto|until)\s+(?P<b>.+)$", re.I),
    # Kanglish / Kannada: "A inda B ge", "A ನಿಂದ B ಗೆ", "A se B"
    re.compile(r"^(?P<a>.+?)\s*(?:\binda\b|\bninda\b|\bind\b|\bse\b|ಇಂದ|ನಿಂದ|ದಿಂದ|ಯಿಂದ)\s+(?P<b>.+)$", re.I),
]
_DEST_PATTERNS = [
    re.compile(r"^(?:which|what)\s+bus(?:es)?\s+(?:goes|go|going|run|runs)?\s*(?:to|for|towards)\s+(?P<b>.+)$", re.I),
    re.compile(r"^(?:any\s+)?bus(?:es)?\s+(?:to|for|towards)\s+(?P<b>.+)$", re.I),
    re.compile(r"^(?:is|are)\s+there\s+(?:a\s+|any\s+)?bus(?:es)?\s+(?:to|for|towards)\s+(?P<b>.+)$", re.I),
    re.compile(r"^how\s+(?:to|do i|can i)\s+(?:go|get|reach|travel)\s+(?:to\s+)?(?P<b>.+)$", re.I),
    re.compile(r"^(?P<b>.+?)\s*(?:\bge\b|\bki\b|ಗೆ|ಕ್ಕೆ)\s+(?:yav|yavdu|yaav|ಯಾವ)\s*(?:bus|ಬಸ್).*$", re.I),
    re.compile(r"^(?P<b>.+?)\s*(?:\bge\b|ಗೆ|ಕ್ಕೆ)\s+(?:hogodu|hogbeku|ಹೋಗುವುದು|ಹೋಗಬೇಕು).*$", re.I),
]
_STOP_ROUTES_PATTERNS = [
    re.compile(r"^(?:which|what)?\s*(?:buses|bus|routes)\s+(?:stop|stops|halt|pass|go|run)s?\s+(?:at|through|via|from)\s+(?P<p>.+)$", re.I),
    re.compile(r"^(?:buses|routes)\s+(?:at|from|via|through|in)\s+(?P<p>.+)$", re.I),
    re.compile(r"^(?P<p>.+?)\s+(?:stop|bus stop|stand)\s+(?:buses|routes)$", re.I),
]


def _has(words: str, text: str) -> bool:
    return re.search(rf"(?<![\wಀ-೿])(?:{words})(?![\wಀ-೿])", text, re.I) is not None


def _valid_place(p: str) -> bool:
    c = clean_place(p).lower()
    first = c.split(" ")[0] if c else ""
    return (len(c) >= 2 and c not in NOT_A_PLACE and c not in QUESTION_WORDS and first not in QUESTION_WORDS
            and not re.fullmatch(r"\d+", c) and not _has(FARE_WORDS, c))


def parse_journey(text: str) -> Optional[Tuple[str, str]]:
    for rx in _JOURNEY_PATTERNS:
        m = rx.match(text)
        if m and _valid_place(m.group("a")) and _valid_place(m.group("b")):
            a, b = canonical_place(m.group("a")), canonical_place(m.group("b"))
            if a and b and a.lower() != b.lower():
                return a, b
    return None


def classify(message: str) -> Intent:
    text = normalize(message)
    low = text.lower()
    if not text:
        return Intent("HELP")

    m = VEHICLE_RE.search(text)
    if m:
        return Intent("BUS_LOCATION", {"reg": re.sub(r"[\s-]", "", m.group(0)).upper()})

    words = low.split()
    if len(words) <= 4 and re.match(r"^(?:hi|hii|hello|hey|hai|namaskara|namaskar|namaste|ನಮಸ್ಕಾರ|good (?:morning|afternoon|evening))\b", low):
        return Intent("GREETING")
    if _has(r"thanks|thank you|thank u|thx|dhanyavada|dhanyavadagalu|ಧನ್ಯವಾದ|ಧನ್ಯವಾದಗಳು", low) and len(words) <= 6:
        return Intent("THANKS")
    if re.fullmatch(r"(?:help|what can you do|how does this work|ಸಹಾಯ|menu|options)", low):
        return Intent("HELP")

    journey = parse_journey(text)
    category = "CHILD" if _has(CHILD_WORDS, low) else "SENIOR" if _has(SENIOR_WORDS, low) else "ADULT"

    if _has(r"how many buses|buses (?:are )?(?:running|live|on (?:the )?road)|live buses|ಎಷ್ಟು ಬಸ್", low) and not journey:
        return Intent("LIVE_COUNT")
    if _has(FARE_WORDS, low) and not _has(r"free|ಉಚಿತ", low):
        if journey:
            return Intent("FARE", {"a": journey[0], "b": journey[1], "category": category})
        return Intent("FARE_INFO", {"category": category})

    # Topic questions (checked before treating "X to Y" as places)
    if _has(r"student|students|college|bus pass|student pass|ವಿದ್ಯಾರ್ಥಿ|ಕಾಲೇಜು", low) and not journey:
        return Intent("STUDENT_PASS")
    if _has(r"women|woman|ladies|lady|female|girls|shakti|aadhaar|aadhar|ಮಹಿಳೆ|ಮಹಿಳೆಯರಿಗೆ|ಮಹಿಳೆಯರು|ಶಕ್ತಿ|ಆಧಾರ್", low) or (
            _has(r"free|ಉಚಿತ", low) and not journey):
        return Intent("FREE_TRAVEL")
    if _has(r"my tickets?|show (?:my )?tickets?|ticket history|qr code|my qr|ನನ್ನ ಟಿಕೆಟ್", low):
        return Intent("MY_TICKETS")
    if _has(r"(?:buy|book|get|purchase)\s+(?:a\s+)?tickets?|how to (?:buy|book)|ticket (?:kodi|kodsi|book)|ಟಿಕೆಟ್ ಖರೀದಿ|ಟಿಕೆಟ್ ಬುಕ್", low) and not journey:
        return Intent("BUY_TICKET")
    if _has(r"how many buses|buses (?:are )?(?:running|live|on (?:the )?road)|live buses|ಎಷ್ಟು ಬಸ್", low) and not journey:
        return Intent("LIVE_COUNT")
    if _has(r"near me|nearby|nearest|closest|around me|hattira|ಹತ್ತಿರ[\u0C80-\u0CFF]*|ಸಮೀಪ[\u0C80-\u0CFF]*", low):
        return Intent("NEAR_ME")

    if journey:
        return Intent("JOURNEY", {"a": journey[0], "b": journey[1]})

    for rx in _STOP_ROUTES_PATTERNS:
        sm = rx.match(text)
        if sm and _valid_place(sm.group("p")):
            return Intent("ROUTES_AT_STOP", {"place": canonical_place(sm.group("p"))})
    for rx in _DEST_PATTERNS:
        dm = rx.match(text)
        if dm and _valid_place(dm.group("b")):
            return Intent("ROUTES_TO", {"place": canonical_place(dm.group("b"))})

    # A route number (digits required): "500D", "route 365p timings", "where is 335-E"
    for token in ROUTE_RE.findall(text.upper()):
        if re.search(r"\d", token) and not re.fullmatch(r"\d{5,}", token):
            sub = "timing" if _has(TIMING_WORDS, low) else "live" if _has(LIVE_WORDS, low) else "info"
            return Intent("ROUTE_INFO", {"route": normalize_route(token), "sub": sub})

    place = canonical_place(text)
    if len(place) >= 3:
        return Intent("STOP_SEARCH", {"place": place})
    return Intent("UNKNOWN")


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------

T = {
    "EN": {
        "help": "I answer from real BMTC data. Ask me things like: “Majestic to Hebbal”, “fare from Silk Board to Majestic”, "
                "“which bus goes to Whitefield”, “500-D”, “where is KA57F4578”, “buses at Shivajinagar”, or “is bus free for women”.",
        "greeting": "Namaskara! 🙏 I'm the ನಮ್ಮ Bus assistant. Ask me how to get somewhere, a fare, a route or where a bus is.",
        "thanks": "You're welcome! Happy journey with ನಮ್ಮ Bus. 🚌",
        "no_live": "Live BMTC bus positions are unavailable right now, so I can't locate buses at the moment.",
        "bus_found": "Bus {num} is on route {route}{towards}. {next}Position is {fresh} ({age}s old).",
        "bus_missing": "Bus {num} is not in the live BMTC feed right now.",
        "towards": ", heading towards {dest}",
        "next": "Next stop: {stop}. ",
        "route": "Route {route}: {origin} ⇄ {dest}. {dirs}{live}",
        "dir": "Towards {dest}: {n} stops. ",
        "route_live": "{n} bus(es) on this route are in the live feed now.",
        "route_nolive": "No buses on this route are in the live feed right now.",
        "route_timing": " BMTC doesn't publish arrival predictions to us, so I can't give times — the map shows where this route's buses are right now.",
        "route_unknown": "I couldn't find route {route} in the BMTC network.",
        "journey": "Options from {a} to {b} (scheduled network):",
        "plan": "• {routes} — {stops} stops, about {mins} min{transfer}",
        "transfer": ", 1 change",
        "no_journey": "I couldn't find a BMTC journey from {a} to {b}. Try a nearby stop name.",
        "fare": "Fare from {a} to {b} by {routes}: {dist} → {cat_line}.{estimate}",
        "fare_dist": "{km} km (stage {stage})",
        "fare_cats": "Adult ₹{ADULT} · Child ₹{CHILD} · Senior ₹{SENIOR}",
        "fare_one": "{label} ₹{amount}",
        "fare_multi": " (per bus, {n} buses: total)",
        "fare_estimate": " This is an AC/special service, so the amount is an estimate, not the official BMTC fare.",
        "fare_free": " Verified women and approved student-pass holders travel free.",
        "fare_info": "BMTC ordinary fares go by distance in 2 km stages: {table}. Children pay about half and seniors (60+) less. "
                     "Ask “fare from A to B” for an exact fare.",
        "stops": "Stops matching “{q}”: {names}",
        "no_match": "I couldn't find a route, stop or bus called “{q}”.",
        "routes_at": "Buses that stop at {stop}: {routes}{more}.",
        "routes_to": "Buses that stop at {stop}: {routes}{more}. Tell me where you're starting (e.g. “Majestic to {q}”) for the best options.",
        "routes_more": " and {n} more",
        "no_routes": "I found {stop}, but no routes are listed for it.",
        "live_count": "{n} BMTC buses are reporting live positions right now, on {r} routes.",
        "near_me": "Open the map: it shows the bus stops around you, how far they are and which routes stop there.",
        "free": "Women with a verified Aadhaar (upload your UIDAI e-Aadhaar PDF in Namma Bus) travel free after a quick face check when "
                "taking the ticket. Without verification, the regular fare applies. Gender alone never makes a ticket free.",
        "student": "Students with a BMTC student bus pass approved by their college get free tickets. Upload your pass in Namma Bus; "
                   "your college verifies it. Until it's approved, the regular fare applies.",
        "buy": "To buy a ticket: choose the route, your boarding stop and destination, pick Adult / Child / Senior, then pay. "
               "The QR ticket works offline too.",
        "my_tickets": "Your tickets and their QR codes are in the Tickets tab (they work offline too).",
        "offline": "The BMTC network service is unavailable right now. Please try again shortly.",
    },
    "KN": {
        "help": "ನಾನು ನಿಜವಾದ BMTC ಮಾಹಿತಿಯಿಂದ ಉತ್ತರಿಸುತ್ತೇನೆ. ಹೀಗೆ ಕೇಳಿ: “Majestic to Hebbal”, “fare from Silk Board to Majestic”, "
                "“which bus goes to Whitefield”, “500-D”, “where is KA57F4578”, “buses at Shivajinagar”, ಅಥವಾ “ಮಹಿಳೆಯರಿಗೆ ಉಚಿತವೇ”.",
        "greeting": "ನಮಸ್ಕಾರ! 🙏 ನಾನು ನಮ್ಮ Bus ಸಹಾಯಕ. ಎಲ್ಲಿಗೆ ಹೋಗುವುದು ಹೇಗೆ, ದರ, ಮಾರ್ಗ ಅಥವಾ ಬಸ್ ಎಲ್ಲಿದೆ ಎಂದು ಕೇಳಿ.",
        "thanks": "ಸ್ವಾಗತ! ನಮ್ಮ Bus ನೊಂದಿಗೆ ಶುಭ ಪ್ರಯಾಣ. 🚌",
        "no_live": "ಲೈವ್ BMTC ಬಸ್ ಸ್ಥಳಗಳು ಈಗ ಲಭ್ಯವಿಲ್ಲ, ಆದ್ದರಿಂದ ಈಗ ಬಸ್‌ಗಳನ್ನು ಪತ್ತೆ ಮಾಡಲು ಸಾಧ್ಯವಿಲ್ಲ.",
        "bus_found": "ಬಸ್ {num} ಮಾರ್ಗ {route} ನಲ್ಲಿದೆ{towards}. {next}ಸ್ಥಳದ ಮಾಹಿತಿ {fresh} ({age} ಸೆ ಹಳೆಯದು).",
        "bus_missing": "ಬಸ್ {num} ಈಗ ಲೈವ್ BMTC ಮಾಹಿತಿಯಲ್ಲಿ ಇಲ್ಲ.",
        "towards": ", {dest} ಕಡೆಗೆ ಹೋಗುತ್ತಿದೆ",
        "next": "ಮುಂದಿನ ನಿಲ್ದಾಣ: {stop}. ",
        "route": "ಮಾರ್ಗ {route}: {origin} ⇄ {dest}. {dirs}{live}",
        "dir": "{dest} ಕಡೆಗೆ: {n} ನಿಲ್ದಾಣಗಳು. ",
        "route_live": "ಈ ಮಾರ್ಗದ {n} ಬಸ್(ಗಳು) ಈಗ ಲೈವ್ ಮಾಹಿತಿಯಲ್ಲಿವೆ.",
        "route_nolive": "ಈ ಮಾರ್ಗದ ಯಾವುದೇ ಬಸ್ ಈಗ ಲೈವ್ ಮಾಹಿತಿಯಲ್ಲಿ ಇಲ್ಲ.",
        "route_timing": " BMTC ಆಗಮನ ಸಮಯದ ಮುನ್ಸೂಚನೆ ನೀಡುವುದಿಲ್ಲ, ಆದ್ದರಿಂದ ಸಮಯ ಹೇಳಲಾಗದು — ಈ ಮಾರ್ಗದ ಬಸ್‌ಗಳು ಈಗ ಎಲ್ಲಿವೆ ಎಂದು ನಕ್ಷೆ ತೋರಿಸುತ್ತದೆ.",
        "route_unknown": "BMTC ಜಾಲದಲ್ಲಿ ಮಾರ್ಗ {route} ಸಿಗಲಿಲ್ಲ.",
        "journey": "{a} ಇಂದ {b} ಗೆ ಆಯ್ಕೆಗಳು (ವೇಳಾಪಟ್ಟಿ ಜಾಲ):",
        "plan": "• {routes} — {stops} ನಿಲ್ದಾಣಗಳು, ಸುಮಾರು {mins} ನಿಮಿಷ{transfer}",
        "transfer": ", 1 ಬದಲಾವಣೆ",
        "no_journey": "{a} ಇಂದ {b} ಗೆ BMTC ಪ್ರಯಾಣ ಸಿಗಲಿಲ್ಲ. ಹತ್ತಿರದ ನಿಲ್ದಾಣದ ಹೆಸರು ಪ್ರಯತ್ನಿಸಿ.",
        "fare": "{a} ಇಂದ {b} ಗೆ {routes} ಮೂಲಕ ದರ: {dist} → {cat_line}.{estimate}",
        "fare_dist": "{km} ಕಿ.ಮೀ (ಹಂತ {stage})",
        "fare_cats": "ವಯಸ್ಕರು ₹{ADULT} · ಮಕ್ಕಳು ₹{CHILD} · ಹಿರಿಯರು ₹{SENIOR}",
        "fare_one": "{label} ₹{amount}",
        "fare_multi": " (ಪ್ರತಿ ಬಸ್, {n} ಬಸ್‌ಗಳು: ಒಟ್ಟು)",
        "fare_estimate": " ಇದು AC/ವಿಶೇಷ ಸೇವೆ, ಆದ್ದರಿಂದ ಮೊತ್ತ ಅಂದಾಜು ಮಾತ್ರ, ಅಧಿಕೃತ BMTC ದರವಲ್ಲ.",
        "fare_free": " ಪರಿಶೀಲಿತ ಮಹಿಳೆಯರು ಮತ್ತು ಅನುಮೋದಿತ ವಿದ್ಯಾರ್ಥಿ ಪಾಸ್ ಹೊಂದಿರುವವರು ಉಚಿತವಾಗಿ ಪ್ರಯಾಣಿಸುತ್ತಾರೆ.",
        "fare_info": "BMTC ಸಾಮಾನ್ಯ ದರ 2 ಕಿ.ಮೀ ಹಂತಗಳಲ್ಲಿ ದೂರದ ಆಧಾರದಲ್ಲಿದೆ: {table}. ಮಕ್ಕಳಿಗೆ ಸುಮಾರು ಅರ್ಧ, ಹಿರಿಯರಿಗೆ (60+) ಕಡಿಮೆ. "
                     "ನಿಖರ ದರಕ್ಕೆ “fare from A to B” ಎಂದು ಕೇಳಿ.",
        "stops": "“{q}” ಗೆ ಹೊಂದುವ ನಿಲ್ದಾಣಗಳು: {names}",
        "no_match": "“{q}” ಎಂಬ ಮಾರ್ಗ, ನಿಲ್ದಾಣ ಅಥವಾ ಬಸ್ ಸಿಗಲಿಲ್ಲ.",
        "routes_at": "{stop} ನಲ್ಲಿ ನಿಲ್ಲುವ ಬಸ್‌ಗಳು: {routes}{more}.",
        "routes_to": "{stop} ನಲ್ಲಿ ನಿಲ್ಲುವ ಬಸ್‌ಗಳು: {routes}{more}. ಉತ್ತಮ ಆಯ್ಕೆಗಳಿಗೆ ನೀವು ಎಲ್ಲಿಂದ ಹೊರಡುತ್ತೀರಿ ಎಂದು ತಿಳಿಸಿ (ಉದಾ. “Majestic to {q}”).",
        "routes_more": " ಮತ್ತು ಇನ್ನೂ {n}",
        "no_routes": "{stop} ಸಿಕ್ಕಿತು, ಆದರೆ ಅದಕ್ಕೆ ಮಾರ್ಗಗಳ ಪಟ್ಟಿ ಇಲ್ಲ.",
        "live_count": "ಈಗ {n} BMTC ಬಸ್‌ಗಳು {r} ಮಾರ್ಗಗಳಲ್ಲಿ ಲೈವ್ ಸ್ಥಳ ಕಳುಹಿಸುತ್ತಿವೆ.",
        "near_me": "ನಕ್ಷೆ ತೆರೆಯಿರಿ: ನಿಮ್ಮ ಸುತ್ತಲಿನ ಬಸ್ ನಿಲ್ದಾಣಗಳು, ಅವುಗಳ ದೂರ ಮತ್ತು ಅಲ್ಲಿ ನಿಲ್ಲುವ ಮಾರ್ಗಗಳನ್ನು ಅದು ತೋರಿಸುತ್ತದೆ.",
        "free": "ಪರಿಶೀಲಿತ ಆಧಾರ್ ಹೊಂದಿರುವ ಮಹಿಳೆಯರು (ನಮ್ಮ Bus ನಲ್ಲಿ UIDAI e-Aadhaar PDF ಅಪ್‌ಲೋಡ್ ಮಾಡಿ) ಟಿಕೆಟ್ ಪಡೆಯುವಾಗ ತ್ವರಿತ ಮುಖ ಪರಿಶೀಲನೆಯ ನಂತರ "
                "ಉಚಿತವಾಗಿ ಪ್ರಯಾಣಿಸುತ್ತಾರೆ. ಪರಿಶೀಲನೆ ಇಲ್ಲದಿದ್ದರೆ ಸಾಮಾನ್ಯ ದರ. ಲಿಂಗದ ಆಧಾರದ ಮೇಲೆ ಮಾತ್ರ ಟಿಕೆಟ್ ಉಚಿತವಾಗುವುದಿಲ್ಲ.",
        "student": "ಕಾಲೇಜು ಅನುಮೋದಿಸಿದ BMTC ವಿದ್ಯಾರ್ಥಿ ಬಸ್ ಪಾಸ್ ಹೊಂದಿರುವವರಿಗೆ ಉಚಿತ ಟಿಕೆಟ್. ನಮ್ಮ Bus ನಲ್ಲಿ ಪಾಸ್ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ; ನಿಮ್ಮ ಕಾಲೇಜು ಪರಿಶೀಲಿಸುತ್ತದೆ. "
                   "ಅನುಮೋದನೆಯಾಗುವವರೆಗೆ ಸಾಮಾನ್ಯ ದರ.",
        "buy": "ಟಿಕೆಟ್ ಖರೀದಿಸಲು: ಮಾರ್ಗ, ಹತ್ತುವ ಮತ್ತು ಇಳಿಯುವ ನಿಲ್ದಾಣ ಆಯ್ಕೆಮಾಡಿ, ವಯಸ್ಕ / ಮಕ್ಕಳು / ಹಿರಿಯರು ಆರಿಸಿ, ನಂತರ ಪಾವತಿಸಿ. QR ಟಿಕೆಟ್ ಆಫ್‌ಲೈನ್‌ನಲ್ಲೂ ಕೆಲಸ ಮಾಡುತ್ತದೆ.",
        "my_tickets": "ನಿಮ್ಮ ಟಿಕೆಟ್‌ಗಳು ಮತ್ತು QR ಕೋಡ್‌ಗಳು ಟಿಕೆಟ್‌ಗಳು ಟ್ಯಾಬ್‌ನಲ್ಲಿವೆ (ಆಫ್‌ಲೈನ್‌ನಲ್ಲೂ ಕೆಲಸ ಮಾಡುತ್ತವೆ).",
        "offline": "BMTC ಜಾಲ ಸೇವೆ ಈಗ ಲಭ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಪ್ರಯತ್ನಿಸಿ.",
    },
}
FRESH = {"EN": {"LIVE": "live", "RECENT": "recent", "STALE": "stale"}, "KN": {"LIVE": "ಲೈವ್", "RECENT": "ಇತ್ತೀಚಿನ", "STALE": "ಹಳೆಯ"}}
CAT_LABEL = {"EN": {"ADULT": "Adult", "CHILD": "Child", "SENIOR": "Senior"}, "KN": {"ADULT": "ವಯಸ್ಕರು", "CHILD": "ಮಕ್ಕಳು", "SENIOR": "ಹಿರಿಯರು"}}
SOURCE = "BMTC GTFS network + live BMTC feed (via NammaRoute) + BMTC stage-fare chart"


class Sources:
    """Callables onto the real-data endpoints (injected so the assistant is testable)."""

    def __init__(self, vehicles: Callable[..., Awaitable[Any]], route: Callable[[str], Awaitable[Any]],
                 journey: Callable[[str, str], Awaitable[Any]], stops: Callable[[str], Awaitable[Any]],
                 stop_detail: Optional[Callable[[str], Awaitable[Any]]] = None,
                 fare: Optional[Callable[[str, str, str], Awaitable[Any]]] = None):
        self.vehicles, self.route, self.journey, self.stops = vehicles, route, journey, stops
        self.stop_detail, self.fare = stop_detail, fare


def _reply(text: str, actions: Optional[List[Dict[str, str]]] = None, kind: str = "answer", intent: str = "") -> Dict[str, Any]:
    return {"answer": text, "kind": kind, "intent": intent, "actions": actions or [], "source": SOURCE}


def _route_numbers(routes: Any) -> List[str]:
    """Route lists come as plain numbers or as route objects; return unique, readable route numbers."""
    out: List[str] = []
    for r in routes or []:
        num = r.get("routeNumber") if isinstance(r, dict) else r
        if num and isinstance(num, str) and not re.search(r"\btest\b", num, re.I) and num not in out:
            out.append(num)
    return out


def _real_stop_matches(stops: List[dict], q: str) -> List[dict]:
    """Only genuine matches (the stop search falls back to popular stops when nothing matches)."""
    ql = q.lower()
    out, seen = [], set()
    for s in stops or []:
        n = s.get("name") or ""
        kn = s.get("nameKannada") or ""
        if n and n not in seen and (ql in n.lower() or ql in kn.lower() or any(a and ql in str(a).lower() for a in (s.get("aliases") or []))):
            seen.add(n)
            out.append(s)
    return out


def _fare_table(lang: str) -> str:
    from ..access.fares import STAGE_FARES

    marks = [(1, 2), (2, 4), (3, 6), (5, 10), (7, 14), (10, 20), (20, 40), (25, 50)]
    km = "km" if lang != "KN" else "ಕಿ.ಮೀ"
    return ", ".join(f"≤{d} {km} ₹{STAGE_FARES[s - 1][0]}" for s, d in marks)


async def answer(message: str, lang: str, src: Sources) -> Dict[str, Any]:
    lang = "KN" if lang == "KN" else "EN"
    t = T[lang]
    intent = classify(message)
    slots = intent.slots
    name = intent.name

    if name in ("HELP", "UNKNOWN"):
        return _reply(t["help"], kind="help", intent=name)
    if name == "GREETING":
        return _reply(t["greeting"], [{"label": "map", "href": "/(tabs)/map"}], kind="smalltalk", intent=name)
    if name == "THANKS":
        return _reply(t["thanks"], kind="smalltalk", intent=name)
    if name == "FREE_TRAVEL":
        return _reply(t["free"], [{"label": "verify", "href": "/access/aadhaar"}, {"label": "ticket", "href": "/access/buy"}], intent=name)
    if name == "STUDENT_PASS":
        return _reply(t["student"], [{"label": "student", "href": "/access/student"}], intent=name)
    if name == "BUY_TICKET":
        return _reply(t["buy"], [{"label": "ticket", "href": "/access/buy"}], intent=name)
    if name == "MY_TICKETS":
        return _reply(t["my_tickets"], [{"label": "tickets", "href": "/(tabs)/tickets"}], intent=name)
    if name == "NEAR_ME":
        return _reply(t["near_me"], [{"label": "map", "href": "/(tabs)/map"}], intent=name)
    if name == "FARE_INFO":
        return _reply(t["fare_info"].format(table=_fare_table(lang)) + t["fare_free"], [{"label": "ticket", "href": "/access/buy"}], intent=name)

    if name == "LIVE_COUNT":
        data = await src.vehicles()
        if not data.live_connected:
            return _reply(t["no_live"], kind="unavailable", intent=name)
        routes = {v.route_number for v in data.vehicles if v.route_number}
        return _reply(t["live_count"].format(n=data.count, r=len(routes)), [{"label": "map", "href": "/(tabs)/map"}], intent=name)

    if name == "BUS_LOCATION":
        num = slots["reg"]
        data = await src.vehicles()
        if not data.live_connected:
            return _reply(t["no_live"], kind="unavailable", intent=name)
        bus = next((v for v in data.vehicles if (v.vehicle_number or "").replace(" ", "").upper() == num), None)
        if not bus:
            return _reply(t["bus_missing"].format(num=num), kind="not_found", intent=name)
        towards = t["towards"].format(dest=bus.destination) if bus.destination else ""
        nxt = t["next"].format(stop=bus.next_stop.stop_name) if bus.next_stop and bus.next_stop.stop_name else ""
        return _reply(
            t["bus_found"].format(num=num, route=bus.route_number or "—", towards=towards, next=nxt,
                                  fresh=FRESH[lang].get(bus.freshness, bus.freshness), age=bus.freshness_seconds or 0),
            [{"label": "map", "href": f"/(tabs)/map?vehicle={bus.vehicle_id}"}], intent=name,
        )

    if name in ("JOURNEY", "FARE"):
        a, b = slots["a"], slots["b"]
        body = await src.journey(a, b)
        plans = body.get("plans") or []
        if not plans:
            return _reply(t["no_journey"].format(a=a, b=b), kind="not_found", intent=name)
        if name == "FARE" and src.fare is not None:
            reply = await _fare_reply(t, lang, a, b, plans[0], slots.get("category", "ADULT"), src)
            if reply:
                return reply
        lines = [t["journey"].format(a=a, b=b)]
        actions = []
        for p in plans[:3]:
            legs = p.get("legs") or []
            routes = " → ".join(leg.get("routeNumber", "?") for leg in legs)
            stops = sum(int(leg.get("stopCount") or 0) for leg in legs)
            mins = int(p.get("totalDurationMinutes") or 0)
            lines.append(t["plan"].format(routes=routes, stops=stops, mins=mins, transfer=t["transfer"] if p.get("transferCount") else ""))
            if legs:
                actions.append({"label": legs[0].get("routeNumber", ""), "href": f"/network/route/{legs[0].get('routeNumber', '')}"})
        return _reply("\n".join(lines), actions, intent=name)

    if name in ("ROUTES_AT_STOP", "ROUTES_TO"):
        q = slots["place"]
        matches = _real_stop_matches(await src.stops(q), q)
        if not matches:
            return _reply(t["no_match"].format(q=q) + " " + t["help"], kind="not_found", intent=name)
        # Among the first few matches pick the stop served by the most routes (the main stand, not a depot or a
        # station's parent record whose routes sit on its platforms)
        stop, routes = matches[0], []
        for cand in matches[:5]:
            found = _route_numbers(cand.get("routes"))
            if not found and src.stop_detail is not None and cand.get("id"):
                detail = await src.stop_detail(str(cand["id"])) or {}
                found = _route_numbers(detail.get("routesServing"))
            if len(found) > len(routes):
                stop, routes = cand, found
        if not routes:
            return _reply(t["no_routes"].format(stop=stop.get("name")), kind="not_found", intent=name)
        shown = routes[:12]
        more = t["routes_more"].format(n=len(routes) - len(shown)) if len(routes) > len(shown) else ""
        key = "routes_to" if name == "ROUTES_TO" else "routes_at"
        return _reply(t[key].format(stop=stop.get("name"), routes=", ".join(shown), more=more, q=q),
                      [{"label": r, "href": f"/(tabs)/map?route={r}"} for r in shown[:3]], intent=name)

    if name == "ROUTE_INFO":
        token = slots["route"]
        detail = await src.route(token)
        if not detail and token != token.replace("-", ""):
            detail = await src.route(token.replace("-", ""))
        if not detail:
            # maybe it was a place name with digits ("5th block") → stop search
            return await _stop_search(t, token, src, name)
        dirs = "".join(t["dir"].format(dest=d.get("destinationName") or "", n=d.get("stopCount") or "—") for d in (detail.get("directions") or []))
        route_no = detail.get("routeNumber") or token
        vdata = await src.vehicles(route_no)
        live = t["route_live"].format(n=vdata.count) if vdata.live_connected and vdata.count else t["route_nolive"]
        text = t["route"].format(route=route_no, origin=detail.get("origin") or "", dest=detail.get("destination") or "", dirs=dirs, live=live)
        if slots.get("sub") == "timing":
            text += t["route_timing"]
        return _reply(text, [{"label": route_no, "href": f"/network/route/{route_no}"}, {"label": "map", "href": f"/(tabs)/map?route={route_no}"},
                             {"label": "ticket", "href": f"/access/buy?route={route_no}"}], intent=name)

    if name == "STOP_SEARCH":
        return await _stop_search(t, slots["place"], src, name)

    return _reply(t["help"], kind="help", intent=name)


async def _stop_search(t: dict, q: str, src: Sources, intent: str) -> Dict[str, Any]:
    matches = _real_stop_matches(await src.stops(q), q)
    if matches:
        names = []
        for s in matches:
            if s["name"] not in names:
                names.append(s["name"])
        return _reply(t["stops"].format(q=q, names=", ".join(names[:6])), [{"label": "map", "href": "/(tabs)/map"}], intent=intent)
    return _reply(t["no_match"].format(q=q) + " " + t["help"], kind="not_found", intent=intent)


async def _fare_reply(t: dict, lang: str, a: str, b: str, plan: dict, category: str, src: Sources) -> Optional[Dict[str, Any]]:
    legs = plan.get("legs") or []
    totals = {"ADULT": 0, "CHILD": 0, "SENIOR": 0}
    km, stages, estimate = 0.0, [], False
    for leg in legs:
        route = leg.get("routeNumber")
        fs, ts = (leg.get("fromStop") or {}).get("id"), (leg.get("toStop") or {}).get("id")
        if not (route and fs and ts):
            return None
        try:
            q = await src.fare(route, str(fs), str(ts))
        except Exception:
            return None
        fares = getattr(q, "fares", None) or {}
        if not fares:
            estimate = True
            fares = {k: getattr(q, "unit_fare", 0) for k in totals}
        for k in totals:
            totals[k] += int(fares.get(k, 0))
        km += float(getattr(q, "distance_km", 0) or 0)
        if getattr(q, "stage", None):
            stages.append(str(q.stage))
    routes = " → ".join(leg.get("routeNumber", "?") for leg in legs)
    dist = t["fare_dist"].format(km=round(km, 1), stage="+".join(stages) or "—")
    if category == "ADULT":
        cat_line = t["fare_cats"].format(**totals)
    else:
        cat_line = t["fare_one"].format(label=CAT_LABEL[lang][category], amount=totals[category])
    if len(legs) > 1:
        cat_line += t["fare_multi"].format(n=len(legs))
    text = t["fare"].format(a=a, b=b, routes=routes, dist=dist, cat_line=cat_line, estimate=t["fare_estimate"] if estimate else "")
    text += t["fare_free"]
    first = legs[0].get("routeNumber", "")
    return _reply(text, [{"label": "ticket", "href": f"/access/buy?route={first}"}, {"label": first, "href": f"/network/route/{first}"}], intent="FARE")
