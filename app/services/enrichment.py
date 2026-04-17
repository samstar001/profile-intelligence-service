import asyncio
import httpx
from fastapi import HTTPException


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

    # Pick highest probability country
    top_country = max(countries, key=lambda c: c["probability"])

    return {
        "gender": genderize["gender"],
        "gender_probability": genderize["probability"],
        "sample_size": genderize["count"],
        "age": agify["age"],
        "age_group": classify_age_group(agify["age"]),
        "country_id": top_country["country_id"],
        "country_probability": top_country["probability"],
    }