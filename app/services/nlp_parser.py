import re
from typing import Optional

COUNTRY_NAME_TO_CODE = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ", "angola": "AO",
    "argentina": "AR", "armenia": "AM", "australia": "AU", "austria": "AT",
    "bangladesh": "BD", "belarus": "BY", "belgium": "BE", "benin": "BJ",
    "botswana": "BW", "brazil": "BR", "bulgaria": "BG", "burkina faso": "BF",
    "burundi": "BI", "cambodia": "KH", "cameroon": "CM", "canada": "CA",
    "chad": "TD", "chile": "CL", "china": "CN", "colombia": "CO",
    "congo": "CD", "drc": "CD", "democratic republic of congo": "CD",
    "croatia": "HR", "cuba": "CU", "denmark": "DK", "djibouti": "DJ",
    "ecuador": "EC", "egypt": "EG", "eritrea": "ER", "estonia": "EE",
    "ethiopia": "ET", "finland": "FI", "france": "FR", "gabon": "GA",
    "gambia": "GM", "georgia": "GE", "germany": "DE", "ghana": "GH",
    "greece": "GR", "guatemala": "GT", "guinea": "GN", "haiti": "HT",
    "honduras": "HN", "hungary": "HU", "india": "IN", "indonesia": "ID",
    "iran": "IR", "iraq": "IQ", "ireland": "IE", "israel": "IL",
    "italy": "IT", "ivory coast": "CI", "jamaica": "JM", "japan": "JP",
    "jordan": "JO", "kazakhstan": "KZ", "kenya": "KE", "kuwait": "KW",
    "latvia": "LV", "lebanon": "LB", "lesotho": "LS", "liberia": "LR",
    "libya": "LY", "lithuania": "LT", "luxembourg": "LU", "madagascar": "MG",
    "malawi": "MW", "malaysia": "MY", "mali": "ML", "mauritania": "MR",
    "mexico": "MX", "moldova": "MD", "morocco": "MA", "mozambique": "MZ",
    "myanmar": "MM", "namibia": "NA", "nepal": "NP", "netherlands": "NL",
    "new zealand": "NZ", "nicaragua": "NI", "niger": "NE", "nigeria": "NG",
    "norway": "NO", "oman": "OM", "pakistan": "PK", "panama": "PA",
    "paraguay": "PY", "peru": "PE", "philippines": "PH", "poland": "PL",
    "portugal": "PT", "qatar": "QA", "romania": "RO", "russia": "RU",
    "rwanda": "RW", "saudi arabia": "SA", "senegal": "SN", "serbia": "RS",
    "sierra leone": "SL", "somalia": "SO", "south africa": "ZA",
    "south sudan": "SS", "spain": "ES", "sri lanka": "LK", "sudan": "SD",
    "sweden": "SE", "switzerland": "CH", "syria": "SY", "taiwan": "TW",
    "tajikistan": "TJ", "tanzania": "TZ", "thailand": "TH", "togo": "TG",
    "tunisia": "TN", "turkey": "TR", "turkmenistan": "TM", "uganda": "UG",
    "ukraine": "UA", "united arab emirates": "AE", "uae": "AE",
    "united kingdom": "GB", "uk": "GB", "england": "GB",
    "united states": "US", "usa": "US", "america": "US",
    "uruguay": "UY", "uzbekistan": "UZ", "venezuela": "VE",
    "vietnam": "VN", "yemen": "YE", "zambia": "ZM", "zimbabwe": "ZW",
    "south korea": "KR", "north korea": "KP", "mongolia": "MN",
    "singapore": "SG", "north macedonia": "MK", "montenegro": "ME",
    "kosovo": "XK",
}


def parse_natural_language_query(q: str) -> Optional[dict]:
    if not q or not q.strip():
        return None

    text = q.lower().strip()
    filters = {}

    has_male = bool(re.search(r'\b(male|males|man|men|boy|boys)\b', text))
    has_female = bool(re.search(r'\b(female|females|woman|women|girl|girls)\b', text))

    if has_male and not has_female:
        filters["gender"] = "male"
    elif has_female and not has_male:
        filters["gender"] = "female"

    if re.search(r'\b(child|children|kids|kid)\b', text):
        filters["age_group"] = "child"
    elif re.search(r'\b(teenager|teenagers|teen|teens|teenage)\b', text):
        filters["age_group"] = "teenager"
    elif re.search(r'\b(adult|adults)\b', text):
        filters["age_group"] = "adult"
    elif re.search(r'\b(senior|seniors|elderly|elder)\b', text):
        filters["age_group"] = "senior"

    if re.search(r'\byoung\b', text):
        filters["min_age"] = 16
        filters["max_age"] = 24

    between_match = re.search(r'\bbetween\s+(\d+)\s+and\s+(\d+)\b', text)
    if between_match:
        filters["min_age"] = int(between_match.group(1))
        filters["max_age"] = int(between_match.group(2))

    above_match = re.search(
        r'\b(?:above|over|older than|at least|greater than|more than)\s+(\d+)\b',
        text
    )
    if above_match:
        filters["min_age"] = int(above_match.group(1))

    below_match = re.search(
        r'\b(?:below|under|younger than|at most|less than)\s+(\d+)\b',
        text
    )
    if below_match:
        filters["max_age"] = int(below_match.group(1))

    for country_name, code in sorted(
        COUNTRY_NAME_TO_CODE.items(), key=lambda x: -len(x[0])
    ):
        if re.search(r'\b' + re.escape(country_name) + r'\b', text):
            filters["country_id"] = code
            break

    if not filters:
        return None

    return filters