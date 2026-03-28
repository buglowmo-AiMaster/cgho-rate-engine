import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.extras

app = FastAPI(title="CGHO Rate Engine", version="1.0.0")
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
    plan_tier: Optional[str] = None        # Silver / Gold / Platinum — if None returns all 3
    aoc: str = "WWE-USA"                   # WW or WWE-USA
    frequency: str = "Monthly"             # Monthly / Quarterly / Annual

    # IP (core — always included)
    ip_deductible_usd: float = 0
    ip_coinsurance_pct: float = 0

    # OP (optional add-on)
    include_op: bool = False
    op_deductible_usd: float = 0
    op_coinsurance_pct: float = 0

    # Riders (optional)
    include_hw: bool = False
    include_dv: bool = False
    include_ev: bool = False


def get_rate(cur, loc_id: int, age: int, aoc: str, deductible: float,
             coinsurance: float, cover_type: str, plan_tier: str,
             hw: bool = False, dv: bool = False, ev: bool = False) -> Optional[float]:
    cur.execute("""
        SELECT r.base_premium
        FROM rate_rules r
        JOIN products p ON r.product_id = p.id
        WHERE r.rating_area_location = %s
          AND r.aoc = %s
          AND r.deductible_usd = %s
          AND r.coinsurance_pct = %s
          AND r.frequency = 'Monthly'
          AND r.hw_coverage = %s
          AND r.dv_coverage = %s
          AND r.ev_coverage = %s
          AND r.age_min <= %s
          AND r.age_max >= %s
          AND p.plan_tier = %s
          AND (r.cover_type = %s OR r.cover_type IS NULL)
          AND (r.expiry_date IS NULL OR r.expiry_date > CURRENT_DATE)
        ORDER BY r.base_premium ASC
        LIMIT 1
    """, (loc_id, aoc, deductible, coinsurance, hw, dv, ev, age, age, plan_tier, cover_type))
    row = cur.fetchone()
    return float(row["base_premium"]) if row else None


@app.get("/")
def root():
    return {"api": "CGHO Rate Engine", "version": "1.0.0", "docs": "/docs", "health": "/health"}

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
        return {"status": "no_data", "message": "Database not ready"}

@app.get("/options")
def options():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT aoc FROM rate_rules WHERE cover_type='IP' ORDER BY aoc")
    aocs = [r["aoc"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT deductible_usd FROM rate_rules WHERE cover_type='IP' ORDER BY deductible_usd")
    ip_deds = [float(r["deductible_usd"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT deductible_usd FROM rate_rules WHERE cover_type='OP' ORDER BY deductible_usd")
    op_deds = [float(r["deductible_usd"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT coinsurance_pct FROM rate_rules WHERE cover_type='IP' ORDER BY coinsurance_pct")
    ip_cois = [float(r["coinsurance_pct"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT coinsurance_pct FROM rate_rules WHERE cover_type='OP' ORDER BY coinsurance_pct")
    op_cois = [float(r["coinsurance_pct"]) for r in cur.fetchall()]
    conn.close()
    return {
        "aoc_options": aocs,
        "ip_deductible_options": ip_deds,
        "ip_coinsurance_options": ip_cois,
        "op_deductible_options": op_deds,
        "op_coinsurance_options": op_cois,
        "op_oop_max_note": "OP OOP max is always $3,000 regardless of coinsurance chosen",
        "frequency_options": ["Monthly", "Quarterly", "Annual"],
        "plan_tiers": ["Silver", "Gold", "Platinum"],
        "riders": ["HW (Health & Wellness)", "DV (Dental & Vision)", "EV (Evacuation)"]
    }

@app.get("/countries")
def countries():
    conn = db()
    cur = conn.cursor()
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
    cur = conn.cursor()

    # Resolve country → rating zone
    cur.execute("""
        SELECT c.name, ra.id AS loc_id, ra.name AS loc_zone
        FROM countries c
        JOIN rating_areas ra ON c.rating_area_location = ra.id
        WHERE LOWER(c.name) = LOWER(%s)
    """, (req.country_of_residence,))
    country = cur.fetchone()
    if not country:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Country '{req.country_of_residence}' not found. Check /countries.")

    # Frequency loading factor
    freq_factor = 1.0
    try:
        cur.execute("SELECT factor FROM frequency_loadings WHERE LOWER(frequency) = LOWER(%s)", (req.frequency,))
        fl = cur.fetchone()
        if fl: freq_factor = float(fl["factor"])
    except: pass

    # Premium tax
    tax_rate = 0.0
    try:
        cur.execute("SELECT tax_rate FROM premium_tax WHERE LOWER(country) = LOWER(%s) ORDER BY tax_start_date DESC LIMIT 1", (req.country_of_residence,))
        pt = cur.fetchone()
        if pt: tax_rate = float(pt["tax_rate"])
    except: pass

    loc_id = country["loc_id"]
    tiers = [req.plan_tier] if req.plan_tier else ["Silver", "Gold", "Platinum"]
    results = []

    for tier in tiers:
        # ── IP base (always required) ──────────────────────────────────────
        ip_monthly = get_rate(cur, loc_id, req.age, req.aoc,
                              req.ip_deductible_usd, req.ip_coinsurance_pct,
                              "IP", tier)
        if ip_monthly is None:
            continue  # No rate found for this tier/zone/age combination

        # ── OP add-on (optional) ───────────────────────────────────────────
        op_monthly = None
        if req.include_op:
            op_monthly = get_rate(cur, loc_id, req.age, req.aoc,
                                  req.op_deductible_usd, req.op_coinsurance_pct,
                                  "OP", tier)

        # ── Riders (optional) ─────────────────────────────────────────────
        hw_monthly = None
        dv_monthly = None
        ev_monthly = None

        if req.include_hw:
            hw_monthly = get_rate(cur, loc_id, req.age, req.aoc,
                                  0, 0, "IP", tier, hw=True, dv=False, ev=False)

        if req.include_dv:
            dv_monthly = get_rate(cur, loc_id, req.age, req.aoc,
                                  0, 0, "IP", tier, hw=False, dv=True, ev=False)

        if req.include_ev:
            ev_monthly = get_rate(cur, loc_id, req.age, req.aoc,
                                  0, 0, "IP", tier, hw=False, dv=False, ev=True)

        # ── Calculate total ───────────────────────────────────────────────
        subtotal_monthly = ip_monthly
        if op_monthly: subtotal_monthly += op_monthly
        if hw_monthly: subtotal_monthly += hw_monthly
        if dv_monthly: subtotal_monthly += dv_monthly
        if ev_monthly: subtotal_monthly += ev_monthly

        # Apply frequency factor
        if req.frequency == "Monthly":
            period_amount = subtotal_monthly * freq_factor
            monthly_equiv = period_amount
        elif req.frequency == "Quarterly":
            period_amount = subtotal_monthly * 3 * freq_factor
            monthly_equiv = period_amount / 3
        elif req.frequency == "Annual":
            period_amount = subtotal_monthly * 12 * freq_factor
            monthly_equiv = period_amount / 12
        else:
            period_amount = subtotal_monthly
            monthly_equiv = subtotal_monthly

        # Apply tax
        period_with_tax = round(period_amount * (1 + tax_rate), 2)
        monthly_with_tax = round(monthly_equiv * (1 + tax_rate), 2)
        annual_with_tax = round(monthly_with_tax * 12, 2)

        results.append({
            "plan_tier": tier,
            "insurer": "Cigna Global Health Options",

            # Premium breakdown
            "breakdown": {
                "ip_monthly": round(ip_monthly, 2),
                "op_monthly": round(op_monthly, 2) if op_monthly else None,
                "hw_monthly": round(hw_monthly, 2) if hw_monthly else None,
                "dv_monthly": round(dv_monthly, 2) if dv_monthly else None,
                "ev_monthly": round(ev_monthly, 2) if ev_monthly else None,
                "subtotal_monthly": round(subtotal_monthly, 2),
            },

            # What was applied
            "frequency": req.frequency,
            "frequency_factor": freq_factor,
            "tax_rate": tax_rate,

            # Final amounts
            "premium": period_with_tax,
            "monthly_equivalent": monthly_with_tax,
            "annual_equivalent": annual_with_tax,

            # Quote parameters
            "aoc": req.aoc,
            "ip_deductible_usd": req.ip_deductible_usd,
            "ip_coinsurance_pct": req.ip_coinsurance_pct,
            "op_included": req.include_op,
            "op_deductible_usd": req.op_deductible_usd if req.include_op else None,
            "op_coinsurance_pct": req.op_coinsurance_pct if req.include_op else None,
            "hw_included": req.include_hw,
            "dv_included": req.include_dv,
            "ev_included": req.include_ev,
        })

    conn.close()

    tier_order = {"Silver": 1, "Gold": 2, "Platinum": 3}
    results.sort(key=lambda x: tier_order.get(x["plan_tier"], 9))

    return {
        "age": req.age,
        "country": req.country_of_residence,
        "rating_zone": country["loc_zone"],
        "results_count": len(results),
        "results": results,
    }

@app.get("/quote")
def quote_get(
    age: int,
    country: str,
    aoc: str = "WWE-USA",
    frequency: str = "Monthly",
    plan_tier: Optional[str] = None,
    ip_deductible_usd: float = 0,
    ip_coinsurance_pct: float = 0,
    include_op: bool = False,
    op_deductible_usd: float = 0,
    op_coinsurance_pct: float = 0,
    include_hw: bool = False,
    include_dv: bool = False,
    include_ev: bool = False,
    x_api_key: Optional[str] = Header(None),
):
    return quote(QuoteRequest(
        age=age,
        country_of_residence=country,
        aoc=aoc,
        frequency=frequency,
        plan_tier=plan_tier,
        ip_deductible_usd=ip_deductible_usd,
        ip_coinsurance_pct=ip_coinsurance_pct,
        include_op=include_op,
        op_deductible_usd=op_deductible_usd,
        op_coinsurance_pct=op_coinsurance_pct,
        include_hw=include_hw,
        include_dv=include_dv,
        include_ev=include_ev,
    ), x_api_key=x_api_key)

@app.get("/setup")
def setup(key: str = ""):
    if key != SETUP_KEY:
        raise HTTPException(status_code=403, detail="Wrong setup key.")
    conn = db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS insurers (id SERIAL PRIMARY KEY, code VARCHAR(20) UNIQUE NOT NULL, name VARCHAR(100) NOT NULL, active BOOLEAN DEFAULT TRUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS products (id SERIAL PRIMARY KEY, insurer_id INT REFERENCES insurers(id), code VARCHAR(50) NOT NULL, name VARCHAR(100) NOT NULL, plan_tier VARCHAR(20), active BOOLEAN DEFAULT TRUE, UNIQUE(insurer_id, code))")
    cur.execute("CREATE TABLE IF NOT EXISTS rating_areas (id SERIAL PRIMARY KEY, code VARCHAR(50) UNIQUE NOT NULL, name VARCHAR(100) NOT NULL, region VARCHAR(50))")
    cur.execute("CREATE TABLE IF NOT EXISTS countries (id SERIAL PRIMARY KEY, name VARCHAR(100) UNIQUE NOT NULL, iso_code CHAR(2), rating_area_location INT REFERENCES rating_areas(id), rating_area_citizenship INT REFERENCES rating_areas(id), rating_area_costshare INT REFERENCES rating_areas(id))")
    cur.execute("CREATE TABLE IF NOT EXISTS rate_rules (id BIGSERIAL PRIMARY KEY, insurer_id INT REFERENCES insurers(id) NOT NULL, product_id INT REFERENCES products(id) NOT NULL, age_min SMALLINT NOT NULL, age_max SMALLINT NOT NULL, age_band VARCHAR(20), rating_area_location INT REFERENCES rating_areas(id), rating_area_citizenship INT REFERENCES rating_areas(id), rating_area_costshare INT REFERENCES rating_areas(id), aoc VARCHAR(20) NOT NULL, deductible_usd NUMERIC(10,2) NOT NULL, coinsurance_pct NUMERIC(5,2) NOT NULL, oop_max_usd NUMERIC(10,2), hw_coverage BOOLEAN DEFAULT FALSE, dv_coverage BOOLEAN DEFAULT FALSE, ev_coverage BOOLEAN DEFAULT FALSE, underwriting VARCHAR(20) DEFAULT 'Standard', frequency VARCHAR(20) DEFAULT 'Monthly', currency CHAR(3) DEFAULT 'USD', base_premium NUMERIC(12,4) NOT NULL, effective_date DATE NOT NULL DEFAULT '2026-02-15', expiry_date DATE, source_file VARCHAR(200), loaded_at TIMESTAMPTZ DEFAULT NOW())")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rate_quote ON rate_rules (rating_area_location, aoc, age_min, age_max, deductible_usd, coinsurance_pct)")
    cur.execute("INSERT INTO insurers (code, name) VALUES ('CIGNA_CGHO','Cigna Global Health Options') ON CONFLICT (code) DO NOTHING")
    areas = [('AFRICA_HIGH','Africa - High','Africa'),('AFRICA_LOW','Africa - Low','Africa'),('AMERICAS_HIGH','Americas - High','Americas'),('AMERICAS_MID_HIGH','Americas - Mid-High','Americas'),('AMERICAS_MIDDLE','Americas - Middle','Americas'),('AMERICAS_LOW','Americas - Low','Americas'),('ASIA_HIGH','Asia - High','Asia'),('ASIA_MID_HIGH','Asia - Mid-High','Asia'),('ASIA_MIDDLE','Asia - Middle','Asia'),('ASIA_MID_LOW','Asia - Mid-Low','Asia'),('ASIA_LOW','Asia - Low','Asia'),('EUROPE_HIGH','Europe - High','Europe'),('EUROPE_MID_HIGH','Europe - Mid-High','Europe'),('EUROPE_MIDDLE','Europe - Middle','Europe'),('EUROPE_MID_LOW','Europe - Mid-Low','Europe'),('EUROPE_LOW','Europe - Low','Europe'),('MIDDLE_EAST','Middle East','Middle East'),('OCEANIA','Oceania','Oceania'),('UNITED_STATES','United States','United States')]
    for code, name, region in areas:
        cur.execute("INSERT INTO rating_areas (code,name,region) VALUES (%s,%s,%s) ON CONFLICT (code) DO NOTHING", (code, name, region))
    for code, name, tier in [('CGHO_SILVER','CGHO Silver','Silver'),('CGHO_GOLD','CGHO Gold','Gold'),('CGHO_PLATINUM','CGHO Platinum','Platinum')]:
        cur.execute("INSERT INTO products (insurer_id,code,name,plan_tier) SELECT id,%s,%s,%s FROM insurers WHERE code='CIGNA_CGHO' ON CONFLICT (insurer_id,code) DO NOTHING", (code, name, tier))
    for cname, iso, zone in [('Hong Kong','HK','ASIA_HIGH'),('Singapore','SG','ASIA_MID_HIGH'),('Thailand','TH','ASIA_MID_LOW'),('France','FR','EUROPE_HIGH'),('United Kingdom','GB','EUROPE_HIGH'),('China','CN','ASIA_HIGH')]:
        cur.execute("INSERT INTO countries (name,iso_code,rating_area_location,rating_area_citizenship,rating_area_costshare) SELECT %s,%s,ra.id,ra.id,ra.id FROM rating_areas ra WHERE ra.code=%s ON CONFLICT (name) DO NOTHING", (cname, iso, zone))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Setup complete"}
