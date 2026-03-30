import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.extras

app = FastAPI(title="CGHO Rate Engine", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.environ["DATABASE_URL"]
API_KEY = os.environ.get("API_KEY", "cgho-test-key")
SETUP_KEY = os.environ.get("SETUP_KEY", "cgho-setup-2026")

def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def auth(x_api_key: Optional[str] = Header(None)):
    if x_api_key and x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key.")

class QuoteRequest(BaseModel):
    age: int
    country_of_residence: str
    country_of_nationality: str = ""
    plan_tier: Optional[str] = None
    aoc: str = "WWE-USA"
    frequency: str = "Monthly"
    ip_deductible_usd: float = 0
    ip_coinsurance_pct: float = 0
    include_op: bool = False
    op_deductible_usd: float = 0
    op_coinsurance_pct: float = 0
    include_hw: bool = False
    include_dv: bool = False
    include_ev: bool = False

def get_rate(cur, loc_id, cs_id, age, aoc, deductible, coinsurance, cover_type, plan_tier, cit_tier, hw=False, dv=False, ev=False):
    # Try exact costshare match first — ORDER BY exact match DESC so exact cs match wins
    cur.execute("""
        SELECT r.base_premium FROM rate_rules r
        JOIN products p ON r.product_id = p.id
        WHERE r.rating_area_location = %s
          AND r.aoc = %s
          AND r.deductible_usd = %s AND r.coinsurance_pct = %s
          AND r.frequency = 'Monthly'
          AND r.hw_coverage = %s AND r.dv_coverage = %s AND r.ev_coverage = %s
          AND r.age_min = %s AND r.age_max = %s
          AND p.plan_tier = %s AND r.cover_type = %s AND r.citizenship_tier = %s
          AND (r.expiry_date IS NULL OR r.expiry_date > CURRENT_DATE)
        ORDER BY
            CASE WHEN r.rating_area_costshare = %s THEN 0 ELSE 1 END ASC,
            r.base_premium ASC
        LIMIT 1
    """, (loc_id, aoc, deductible, coinsurance, hw, dv, ev, age, age, plan_tier, cover_type, cit_tier, cs_id))
    row = cur.fetchone()
    return float(row["base_premium"]) if row else None

@app.get("/")
def root():
    return {"api": "CGHO Rate Engine", "version": "2.1.0", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health():
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM rate_rules")
        row = cur.fetchone()
        conn.close()
        return {"status": "ok", "rate_records": row["cnt"]}
    except:
        return {"status": "no_data"}

@app.get("/options")
def options():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT aoc FROM rate_rules WHERE cover_type='IP' AND hw_coverage=false ORDER BY aoc")
    aocs = [r["aoc"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT deductible_usd FROM rate_rules WHERE cover_type='IP' AND hw_coverage=false ORDER BY deductible_usd")
    ip_deds = [float(r["deductible_usd"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT deductible_usd FROM rate_rules WHERE cover_type='OP' AND hw_coverage=false ORDER BY deductible_usd")
    op_deds = [float(r["deductible_usd"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT coinsurance_pct FROM rate_rules WHERE cover_type='IP' AND hw_coverage=false ORDER BY coinsurance_pct")
    ip_cois = [float(r["coinsurance_pct"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT coinsurance_pct FROM rate_rules WHERE cover_type='OP' AND hw_coverage=false ORDER BY coinsurance_pct")
    op_cois = [float(r["coinsurance_pct"]) for r in cur.fetchall()]
    conn.close()
    return {
        "aoc_options": aocs,
        "ip_deductible_options": ip_deds,
        "ip_coinsurance_options": ip_cois,
        "op_deductible_options": op_deds,
        "op_coinsurance_options": op_cois,
        "op_oop_max_note": "OP OOP max is always $3,000 regardless of coinsurance",
        "frequency_options": ["Monthly","Quarterly","Annual"],
        "plan_tiers": ["Silver","Gold","Platinum"],
        "riders": ["HW","DV","EV"],
        "citizenship_tiers": ["High","Medium","Low","United States"]
    }

@app.get("/countries")
def countries():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.name, c.iso_code,
               loc.name AS location_zone,
               cs.name AS costshare_zone,
               COALESCE(c.citizenship_tier, 'Medium') AS citizenship_tier
        FROM countries c
        LEFT JOIN rating_areas loc ON c.rating_area_location = loc.id
        LEFT JOIN rating_areas cs ON c.rating_area_costshare = cs.id
        ORDER BY c.name
    """)
    rows = cur.fetchall()
    conn.close()
    return {"countries": rows}

@app.post("/quote")
def quote(req: QuoteRequest, x_api_key: Optional[str] = Header(None)):
    auth(x_api_key)
    conn = db()
    cur = conn.cursor()

    # Resolve residence → location + costshare zones
    cur.execute("""
        SELECT c.name,
               loc.id AS loc_id, loc.name AS loc_zone,
               cs.id AS cs_id, cs.name AS cs_zone
        FROM countries c
        JOIN rating_areas loc ON c.rating_area_location = loc.id
        LEFT JOIN rating_areas cs ON c.rating_area_costshare = cs.id
        WHERE LOWER(c.name) = LOWER(%s)
    """, (req.country_of_residence,))
    residence = cur.fetchone()
    if not residence:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Country '{req.country_of_residence}' not found.")

    loc_id = residence["loc_id"]
    cs_id = residence["cs_id"] or residence["loc_id"]

    # Resolve nationality → citizenship tier
    cit_tier = "Medium"
    if req.country_of_nationality and req.country_of_nationality.strip():
        cur.execute("SELECT COALESCE(citizenship_tier,'Medium') AS ct FROM countries WHERE LOWER(name)=LOWER(%s)", (req.country_of_nationality,))
        nat = cur.fetchone()
        if nat: cit_tier = nat["ct"]

    # Frequency loading
    freq_factor = 1.0
    try:
        cur.execute("SELECT factor FROM frequency_loadings WHERE LOWER(frequency)=LOWER(%s)", (req.frequency,))
        fl = cur.fetchone()
        if fl: freq_factor = float(fl["factor"])
    except: pass

    # Premium tax
    tax_rate = 0.0
    try:
        cur.execute("SELECT tax_rate FROM premium_tax WHERE LOWER(country)=LOWER(%s) ORDER BY tax_start_date DESC LIMIT 1", (req.country_of_residence,))
        pt = cur.fetchone()
        if pt: tax_rate = float(pt["tax_rate"])
    except: pass

    tiers = [req.plan_tier] if req.plan_tier else ["Silver","Gold","Platinum"]
    results = []

    for tier in tiers:
        ip_monthly = get_rate(cur, loc_id, cs_id, req.age, req.aoc, req.ip_deductible_usd, req.ip_coinsurance_pct, "IP", tier, cit_tier)
        if ip_monthly is None: continue

        op_monthly = get_rate(cur, loc_id, cs_id, req.age, req.aoc, req.op_deductible_usd, req.op_coinsurance_pct, "OP", tier, cit_tier) if req.include_op else None
        hw_monthly = get_rate(cur, loc_id, cs_id, req.age, req.aoc, 0, 0, "IP", tier, cit_tier, hw=True) if req.include_hw else None
        dv_monthly = get_rate(cur, loc_id, cs_id, req.age, req.aoc, 0, 0, "IP", tier, cit_tier, dv=True) if req.include_dv else None
        ev_monthly = get_rate(cur, loc_id, cs_id, req.age, req.aoc, 0, 0, "IP", tier, cit_tier, ev=True) if req.include_ev else None

        subtotal = ip_monthly + (op_monthly or 0) + (hw_monthly or 0) + (dv_monthly or 0) + (ev_monthly or 0)

        if req.frequency == "Monthly":
            period = subtotal * freq_factor; monthly_eq = period
        elif req.frequency == "Quarterly":
            period = subtotal * 3 * freq_factor; monthly_eq = period / 3
        elif req.frequency == "Annual":
            period = subtotal * 12 * freq_factor; monthly_eq = period / 12
        else:
            period = subtotal; monthly_eq = subtotal

        results.append({
            "plan_tier": tier,
            "insurer": "Cigna Global Health Options",
            "breakdown": {
                "ip_monthly":       round(ip_monthly, 2),
                "op_monthly":       round(op_monthly, 2) if op_monthly else None,
                "hw_monthly":       round(hw_monthly, 2) if hw_monthly else None,
                "dv_monthly":       round(dv_monthly, 2) if dv_monthly else None,
                "ev_monthly":       round(ev_monthly, 2) if ev_monthly else None,
                "subtotal_monthly": round(subtotal, 2),
            },
            "frequency": req.frequency,
            "frequency_factor": freq_factor,
            "tax_rate": tax_rate,
            "premium": round(period * (1 + tax_rate), 2),
            "monthly_equivalent": round(monthly_eq * (1 + tax_rate), 2),
            "annual_equivalent": round(monthly_eq * (1 + tax_rate) * 12, 2),
            "quote_parameters": {
                "aoc": req.aoc,
                "citizenship_tier": cit_tier,
                "location_zone": residence["loc_zone"],
                "costshare_zone": residence["cs_zone"],
                "ip_deductible_usd": req.ip_deductible_usd,
                "ip_coinsurance_pct": req.ip_coinsurance_pct,
                "op_included": req.include_op,
                "op_deductible_usd": req.op_deductible_usd if req.include_op else None,
                "op_coinsurance_pct": req.op_coinsurance_pct if req.include_op else None,
                "hw_included": req.include_hw,
                "dv_included": req.include_dv,
                "ev_included": req.include_ev,
            }
        })

    conn.close()
    tier_order = {"Silver":1,"Gold":2,"Platinum":3}
    results.sort(key=lambda x: tier_order.get(x["plan_tier"],9))

    return {
        "age": req.age,
        "country_of_residence": req.country_of_residence,
        "country_of_nationality": req.country_of_nationality or "Not specified (defaulted to Medium)",
        "citizenship_tier": cit_tier,
        "location_zone": residence["loc_zone"],
        "costshare_zone": residence["cs_zone"],
        "results_count": len(results),
        "results": results,
    }

@app.get("/quote")
def quote_get(
    age: int, country: str, nationality: str = "",
    aoc: str = "WWE-USA", frequency: str = "Monthly",
    plan_tier: Optional[str] = None,
    ip_deductible_usd: float = 0, ip_coinsurance_pct: float = 0,
    include_op: bool = False, op_deductible_usd: float = 0, op_coinsurance_pct: float = 0,
    include_hw: bool = False, include_dv: bool = False, include_ev: bool = False,
    x_api_key: Optional[str] = Header(None),
):
    return quote(QuoteRequest(
        age=age, country_of_residence=country, country_of_nationality=nationality,
        aoc=aoc, frequency=frequency, plan_tier=plan_tier,
        ip_deductible_usd=ip_deductible_usd, ip_coinsurance_pct=ip_coinsurance_pct,
        include_op=include_op, op_deductible_usd=op_deductible_usd, op_coinsurance_pct=op_coinsurance_pct,
        include_hw=include_hw, include_dv=include_dv, include_ev=include_ev,
    ), x_api_key=x_api_key)

@app.get("/setup")
def setup(key: str = ""):
    if key != SETUP_KEY:
        raise HTTPException(status_code=403, detail="Wrong setup key.")
    return {"status": "ok", "message": "Database already set up."}
