import asyncio
import httpx
from fastapi import HTTPException

COUNTRY_NAMES = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AO": "Angola",
    "AR": "Argentina", "AM": "Armenia", "AU": "Australia", "AT": "Austria",
    "AZ": "Azerbaijan", "BH": "Bahrain", "BD": "Bangladesh", "BY": "Belarus",
    "BE": "Belgium", "BJ": "Benin", "BO": "Bolivia", "BA": "Bosnia and Herzegovina",
    "BW": "Botswana", "BR": "Brazil", "BG": "Bulgaria", "BF": "Burkina Faso",
    "BI": "Burundi", "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada",
    "CF": "Central African Republic", "TD": "Chad", "CL": "Chile", "CN": "China",
    "CO": "Colombia", "CD": "Congo", "CR": "Costa Rica", "HR": "Croatia",
    "CU": "Cuba", "CY": "Cyprus", "CZ": "Czech Republic", "DK": "Denmark",
    "DJ": "Djibouti", "DO": "Dominican Republic", "EC": "Ecuador", "EG": "Egypt",
    "SV": "El Salvador", "GQ": "Equatorial Guinea", "ER": "Eritrea",
    "EE": "Estonia", "ET": "Ethiopia", "FI": "Finland", "FR": "France",
    "GA": "Gabon", "GM": "Gambia", "GE": "Georgia", "DE": "Germany",
    "GH": "Ghana", "GR": "Greece", "GT": "Guatemala", "GN": "Guinea",
    "GW": "Guinea-Bissau", "HT": "Haiti", "HN": "Honduras", "HU": "Hungary",
    "IN": "India", "ID": "Indonesia", "IR": "Iran", "IQ": "Iraq",
    "IE": "Ireland", "IL": "Israel", "IT": "Italy", "CI": "Ivory Coast",
    "JM": "Jamaica", "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan",
    "KE": "Kenya", "KW": "Kuwait", "KG": "Kyrgyzstan", "LA": "Laos",
    "LV": "Latvia", "LB": "Lebanon", "LS": "Lesotho", "LR": "Liberia",
    "LY": "Libya", "LT": "Lithuania", "LU": "Luxembourg", "MG": "Madagascar",
    "MW": "Malawi", "MY": "Malaysia", "ML": "Mali", "MR": "Mauritania",
    "MX": "Mexico", "MD": "Moldova", "MA": "Morocco", "MZ": "Mozambique",
    "MM": "Myanmar", "NA": "Namibia", "NP": "Nepal", "NL": "Netherlands",
    "NZ": "New Zealand", "NI": "Nicaragua", "NE": "Niger", "NG": "Nigeria",
    "NO": "Norway", "OM": "Oman", "PK": "Pakistan", "PA": "Panama",
    "PY": "Paraguay", "PE": "Peru", "PH": "Philippines", "PL": "Poland",
    "PT": "Portugal", "QA": "Qatar", "RO": "Romania", "RU": "Russia",
    "RW": "Rwanda", "SA": "Saudi Arabia", "SN": "Senegal", "RS": "Serbia",
    "SL": "Sierra Leone", "SO": "Somalia", "ZA": "South Africa",
    "SS": "South Sudan", "ES": "Spain", "LK": "Sri Lanka", "SD": "Sudan",
    "SE": "Sweden", "CH": "Switzerland", "SY": "Syria", "TW": "Taiwan",
    "TJ": "Tajikistan", "TZ": "Tanzania", "TH": "Thailand", "TG": "Togo",
    "TN": "Tunisia", "TR": "Turkey", "TM": "Turkmenistan", "UG": "Uganda",
    "UA": "Ukraine", "AE": "United Arab Emirates", "GB": "United Kingdom",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan",
    "VE": "Venezuela", "VN": "Vietnam", "YE": "Yemen", "ZM": "Zambia",
    "ZW": "Zimbabwe", "CD": "Democratic Republic of Congo",
    "MK": "North Macedonia", "ME": "Montenegro", "XK": "Kosovo",
    "TL": "Timor-Leste", "PG": "Papua New Guinea", "FJ": "Fiji",
    "KR": "South Korea", "KP": "North Korea", "MN": "Mongolia",
    "NP": "Nepal", "LK": "Sri Lanka", "MM": "Myanmar", "KH": "Cambodia",
    "VN": "Vietnam", "TH": "Thailand", "LA": "Laos", "MY": "Malaysia",
    "SG": "Singapore", "BN": "Brunei", "PH": "Philippines", "ID": "Indonesia",
    "TL": "Timor-Leste", "PW": "Palau", "FM": "Micronesia",
}


def classify_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    else:
        return "senior"


async def fetch_enrichment_data(name: str) -> dict:
    """
    Calls all 3 external APIs in parallel.
    Returns processed dict ready for DB storage.
    Raises 502 if any API returns null/invalid data.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            genderize_res, agify_res, nationalize_res = await asyncio.gather(
                client.get(f"https://api.genderize.io?name={name}"),
                client.get(f"https://api.agify.io?name={name}"),
                client.get(f"https://api.nationalize.io?name={name}"),
            )
        except httpx.RequestError:
            raise HTTPException(
                status_code=502,
                detail={
                    "status": "error",
                    "message": "Failed to reach external APIs"
                }
            )

    # --- Genderize ---
    genderize = genderize_res.json()
    if not genderize.get("gender") or genderize.get("count", 0) == 0:
        raise HTTPException(
            status_code=502,
            detail={
                "status": "502",
                "message": "Genderize returned an invalid response"
            }
        )

    # --- Agify ---
    agify = agify_res.json()
    if agify.get("age") is None:
        raise HTTPException(
            status_code=502,
            detail={
                "status": "502",
                "message": "Agify returned an invalid response"
            }
        )

    # --- Nationalize ---
    nationalize = nationalize_res.json()
    countries = nationalize.get("country", [])
    if not countries:
        raise HTTPException(
            status_code=502,
            detail={
                "status": "502",
                "message": "Nationalize returned an invalid response"
            }
        )

    top_country = max(countries, key=lambda c: c["probability"])
    country_code = top_country["country_id"]

    # Look up full country name, fall back to country code if not found
    country_name = COUNTRY_NAMES.get(country_code, country_code)

    return {
        "gender": genderize["gender"],
        "gender_probability": genderize["probability"],
        "sample_size": genderize["count"],
        "age": agify["age"],
        "age_group": classify_age_group(agify["age"]),
        "country_id": country_code,
        "country_name": country_name,
        "country_probability": top_country["probability"],
    }