"""
Held-out questions: written AFTER the classifier was tuned on assistant_eval_set.py and never used to tune it.
Its score is the honest measure of how well the assistant generalises; the test requires >= 85%.
"""

HOLDOUT_SET = [
    ("hebbal to majestic", "JOURNEY", {"a": "Hebbala", "b": "Kempegowda Bus Station"}),
    ("from whitefield to kr puram", "JOURNEY", {"a": "White Field", "b": "K R Puram"}),
    ("best way to get from jayanagar to airport", "JOURNEY", {"a": "Jayanagar", "b": "Kempegowda International Airport"}),
    ("i need to go to marathahalli from silk board", "JOURNEY", {"a": "Central Silk Board", "b": "Marathahalli"}),
    ("koramangala inda indiranagar ge", "JOURNEY", {"a": "Koramangala", "b": "Indiranagara"}),
    ("ಶಿವಾಜಿ ನಗರ ದಿಂದ ಮೆಜೆಸ್ಟಿಕ್ ಗೆ", "JOURNEY", {"a": "Shivajinagara Bus Station", "b": "Kempegowda Bus Station"}),
    ("ecity to btm", "JOURNEY", {"a": "Electronic City", "b": "BTM Layout"}),
    ("how much from hebbal to yeshwanthpur", "FARE", {"a": "Hebbala", "b": "Yeshwanthapura"}),
    ("fare for kids from btm to jayanagar", "FARE", {"category": "CHILD"}),
    ("whats the price of a ticket from majestic to kengeri", "FARE", {"a": "Kempegowda Bus Station", "b": "Kengeri"}),
    ("how much does the bus cost", "FARE_INFO", {}),
    ("which bus goes to majestic", "ROUTES_TO", {"place": "Kempegowda Bus Station"}),
    ("is there a bus to kengeri", "ROUTES_TO", {"place": "Kengeri"}),
    ("airport ge yav bus", "ROUTES_TO", {"place": "Kempegowda International Airport"}),
    ("which buses stop at hebbal", "ROUTES_AT_STOP", {"place": "Hebbala"}),
    ("routes through kr puram", "ROUTES_AT_STOP", {"place": "K R Puram"}),
    ("info on 500-D", "ROUTE_INFO", {"route": "500-D"}),
    ("when does 365P come", "ROUTE_INFO", {"route": "365-P", "sub": "timing"}),
    ("where are the 335E buses", "ROUTE_INFO", {"route": "335-E", "sub": "live"}),
    ("find bus KA57F4578", "BUS_LOCATION", {"reg": "KA57F4578"}),
    ("how many buses are live", "LIVE_COUNT", {}),
    ("bus stop nearby", "NEAR_ME", {}),
    ("do women travel free", "FREE_TRAVEL", {}),
    ("aadhaar verification", "FREE_TRAVEL", {}),
    ("students free pass", "STUDENT_PASS", {}),
    ("i want to book ticket", "BUY_TICKET", {}),
    ("where are my tickets", "MY_TICKETS", {}),
    ("hey there", "GREETING", {}),
    ("thanks a lot", "THANKS", {}),
    ("Banashankari stop", "STOP_SEARCH", {"place": "Banashankari"}),
]
