"""
CGHO Rate Engine API
Cigna Global Health Options — Real-time Quote API
"""

import os
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.extras

app = FastAPI(
    title="CGHO Rate Engine",
    description="Real-time Cigna Global Health Options pricing API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ["DATABASE_URL"]
API_KEY      = os.environ.get("API_KEY", "cgho-test-key")


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def auth(x_api_key: Optional[str] = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key. Pass X-API-Key header.")


# ── Models ─────────────────────────────────────────────────────────────────

class QuoteRequest(BaseModel):
    age:                  int
    country_of_residence: str
    aoc:                  str    = "WWE-USA"
    deductible_usd:       float  = 0
    coinsurance_pct:      float  = 0
    frequency:            str    = "Monthly"
    plan_tier:            Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "api":     "CGHO Rate Engine",
        "version": "1.0.0",
        "docs":    "/docs",
        "health":  "/health"
    }


@app.get("/health")
def health():
    try:
        conn = db()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM rate_rules")
        row = cur.fetchone()
        conn.close()
        return {"status": "ok", "rate_records": row["cnt"]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/options")
def options():
    """All valid input values for building a quote form."""
    conn = db()
    cur  = conn.cursor()
    cur.execute("SELECT DISTINCT aoc FROM rate_rules ORDER BY aoc")
    aocs = [r["aoc"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT deductible_usd FROM rate_rules ORDER BY deductible_usd")
    deds = [float(r["deductible_usd"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT coinsurance_pct FROM rate_rules ORDER BY coinsurance_pct")
    cois = [float(r["coinsurance_pct"]) for r in cur.fetchall()]
    conn.close()
    return {
        "aoc_options":         aocs,
        "deductible_options":  deds,
        "coinsurance_options": cois,
        "frequency_options":   ["Monthly", "Quarterly", "Annual"],
        "plan_tiers":          ["Silver", "Gold", "Platinum"],
    }


@app.get("/countries")
def countries():
    """All countries with their rating zones."""
    conn = db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT c.name, c.iso_code, ra.name AS rating_zone
        FROM countries c
        LEFT JOIN rating_areas ra ON c.rating_area_location = ra.id
        ORDER BY c.name
    """)
    rows = cur.fetchall()
    conn.close()
    return {"countries": rows}


@app.post("/quote")
def quote(req: QuoteRequest, x_api_key: Optional[str] = Header(None)):
    auth(x_api_key)

    conn = db()
    cur  = conn.cursor()

    # Resolve country → rating area
    cur.execute("""
        SELECT c.name, ra.id AS loc_id, ra.name AS loc_zone
        FROM countries c
        JOIN rating_areas ra ON c.rating_area_location = ra.id
        WHERE LOWER(c.name) = LOWER(%s)
    """, (req.country_of_residence,))
    country = cur.fetchone()

    if not country:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail=f"Country '{req.country_of_residence}' not found. Check /countries for valid names."
        )

    # Age lookup — exact age for <70, band for 70+
    if req.age < 70:
        age_clause = "AND r.age_min = %s"
        age_param  = req.age
    else:
        age_clause = "AND r.age_min = 70"
        age_param  = None

    sql = f"""
        SELECT
            i.name           AS insurer,
            p.name           AS plan,
            p.plan_tier,
            r.aoc,
            r.deductible_usd,
            r.coinsurance_pct,
            r.oop_max_usd,
            r.hw_coverage,
            r.dv_coverage,
            r.ev_coverage,
            r.frequency,
            r.currency,
            r.base_premium
        FROM rate_rules r
        JOIN products     p ON r.product_id          = p.id
        JOIN insurers     i ON r.insurer_id           = i.id
        WHERE r.rating_area_location = %s
          AND r.aoc                  = %s
          AND r.deductible_usd       = %s
          AND r.coinsurance_pct      = %s
          AND r.frequency            = %s
          {age_clause}
          AND (r.expiry_date IS NULL OR r.expiry_date > CURRENT_DATE)
          {'AND p.plan_tier = %s' if req.plan_tier else ''}
        ORDER BY r.base_premium ASC
    """

    params = [
        country["loc_id"],
        req.aoc,
        req.deductible_usd,
        req.coinsurance_pct,
        req.frequency,
    ]
    if age_param is not None:
        params.append(age_param)
    if req.plan_tier:
        params.append(req.plan_tier)

    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    results = []
    for r in rows:
        monthly = float(r["base_premium"])
        if r["frequency"] == "Quarterly": monthly = monthly / 3
        if r["frequency"] == "Annual":    monthly = monthly / 12
        results.append({
            **dict(r),
            "base_premium":       float(r["base_premium"]),
            "monthly_equivalent": round(monthly, 2),
            "annual_equivalent":  round(monthly * 12, 2),
        })

    return {
        "age":          req.age,
        "country":      req.country_of_residence,
        "rating_zone":  country["loc_zone"],
        "results_count": len(results),
        "results":      results,
    }


@app.get("/quote")
def quote_get(
    age: int,
    country: str,
    aoc: str = "WWE-USA",
    deductible_usd: float = 0,
    coinsurance_pct: float = 0,
    frequency: str = "Monthly",
    plan_tier: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
):
    """GET version — easier for testing in a browser."""
    return quote(QuoteRequest(
        age=age,
        country_of_residence=country,
        aoc=aoc,
        deductible_usd=deductible_usd,
        coinsurance_pct=coinsurance_pct,
        frequency=frequency,
        plan_tier=plan_tier,
    ), x_api_key=x_api_key)
