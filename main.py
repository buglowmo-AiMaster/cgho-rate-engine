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
    aoc: str = "WWE-USA"
    deductible_usd: float = 0
    coinsurance_pct: float = 0
    frequency: str = "Monthly"
    plan_tier: Optional[str] = None

@app.get("/")
def root():
    return {"api": "CGHO Rate Engine", "version": "1.0.0", "docs": "/docs", "health": "/health", "setup": "/setup?key=cgho-setup-2026"}

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
        return {"status": "no_data", "message": "Run /setup?key=cgho-setup-2026 first"}

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
    rates = [(51,51,'50 to 59','ASIA_HIGH',0,728.06),(51,51,'50 to 59','ASIA_HIGH',10000,409.01),(53,53,'50 to 59','ASIA_HIGH',0,761.07),(53,53,'50 to 59','ASIA_MID_HIGH',0,609.99),(53,53,'50 to 59','ASIA_MID_LOW',0,373.14),(60,60,'60 to 69','ASIA_HIGH',0,1024.32),(65,65,'60 to 69','ASIA_HIGH',0,1338.58),(70,74,'70 to 74','ASIA_HIGH',0,1864.76),(75,75,'75 to 79','ASIA_HIGH',0,2323.82),(77,77,'75 to 79','ASIA_HIGH',0,2513.40),(80,80,'80 to 84','ASIA_HIGH',0,2827.49),(85,85,'85 to 89','ASIA_HIGH',0,3386.21)]
    for age_min, age_max, band, zone, ded, prem in rates:
        cur.execute("INSERT INTO rate_rules (insurer_id,product_id,age_min,age_max,age_band,rating_area_location,rating_area_citizenship,rating_area_costshare,aoc,deductible_usd,coinsurance_pct,hw_coverage,dv_coverage,ev_coverage,underwriting,frequency,currency,base_premium,effective_date,source_file) SELECT i.id,p.id,%s,%s,%s,ra.id,(SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),ra.id,'WWE-USA',%s,0,false,false,false,'Standard','Monthly','USD',%s,'2026-02-15','verified_mar2026' FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' JOIN rating_areas ra ON ra.code=%s WHERE i.code='CIGNA_CGHO'", (age_min, age_max, band, ded, prem, zone))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Setup complete", "rates_loaded": len(rates)}

@app.get("/options")
def options():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT aoc FROM rate_rules WHERE hw_coverage=false AND dv_coverage=false AND ev_coverage=false ORDER BY aoc")
    aocs = [r["aoc"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT deductible_usd FROM rate_rules WHERE hw_coverage=false AND dv_coverage=false AND ev_coverage=false ORDER BY deductible_usd")
    deds = [float(r["deductible_usd"]) for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT coinsurance_pct FROM rate_rules WHERE hw_coverage=false AND dv_coverage=false AND ev_coverage=false ORDER BY coinsurance_pct")
    cois = [float(r["coinsurance_pct"]) for r in cur.fetchall()]
    conn.close()
    return {"aoc_options": aocs, "deductible_options": deds, "coinsurance_options": cois, "frequency_options": ["Monthly","Quarterly","Annual"], "plan_tiers": ["Silver","Gold","Platinum"]}

@app.get("/countries")
def countries():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT c.name, c.iso_code, ra.name AS rating_zone FROM countries c LEFT JOIN rating_areas ra ON c.rating_area_location = ra.id ORDER BY c.name")
    rows = cur.fetchall()
    conn.close()
    return {"countries": rows}

@app.post("/quote")
def quote(req: QuoteRequest, x_api_key: Optional[str] = Header(None)):
    auth(x_api_key)
    conn = db()
    cur = conn.cursor()

    # Get country rating zone
    cur.execute("SELECT c.name, ra.id AS loc_id, ra.name AS loc_zone FROM countries c JOIN rating_areas ra ON c.rating_area_location = ra.id WHERE LOWER(c.name) = LOWER(%s)", (req.country_of_residence,))
    country = cur.fetchone()
    if not country:
        conn.close()
        raise HTTPException(status_code=404, detail="Country not found. Check /countries.")

    # Get frequency loading factor (default 1.0 if table doesn't exist)
    freq_factor = 1.0
    try:
        cur.execute("SELECT factor FROM frequency_loadings WHERE LOWER(frequency) = LOWER(%s)", (req.frequency,))
        fl = cur.fetchone()
        if fl:
            freq_factor = float(fl["factor"])
    except:
        pass

    # Get premium tax rate for country (default 0 if not found)
    tax_rate = 0.0
    try:
        cur.execute("SELECT tax_rate FROM premium_tax WHERE LOWER(country) = LOWER(%s) ORDER BY tax_start_date DESC LIMIT 1", (req.country_of_residence,))
        pt = cur.fetchone()
        if pt:
            tax_rate = float(pt["tax_rate"])
    except:
        pass

    plan_clause = "AND p.plan_tier = %s" if req.plan_tier else ""
    plan_params = [req.plan_tier] if req.plan_tier else []

    cur.execute("""
        SELECT DISTINCT ON (p.plan_tier, r.aoc, r.deductible_usd, r.coinsurance_pct, r.source_file)
            i.name AS insurer, p.name AS plan, p.plan_tier,
            r.aoc, r.deductible_usd, r.coinsurance_pct, r.oop_max_usd,
            r.hw_coverage, r.dv_coverage, r.ev_coverage,
            r.frequency, r.currency, r.base_premium, r.age_band
        FROM rate_rules r
        JOIN products p ON r.product_id = p.id
        JOIN insurers i ON r.insurer_id = i.id
        WHERE r.rating_area_location = %s
          AND r.aoc = %s
          AND r.deductible_usd = %s
          AND r.coinsurance_pct = %s
          AND r.frequency = 'Monthly'
          AND r.hw_coverage = false
          AND r.dv_coverage = false
          AND r.ev_coverage = false
          AND r.age_min <= %s
          AND r.age_max >= %s
          AND (r.expiry_date IS NULL OR r.expiry_date > CURRENT_DATE)
          """ + plan_clause + """
        ORDER BY p.plan_tier, r.aoc, r.deductible_usd, r.coinsurance_pct, r.source_file, r.base_premium ASC
    """, [country["loc_id"], req.aoc, req.deductible_usd, req.coinsurance_pct,
          req.age, req.age] + plan_params)

    rows = cur.fetchall()
    conn.close()

    results = []
    for r in rows:
        base = float(r["base_premium"])

        # Apply frequency loading
        # All rates stored as Monthly — apply factor for quarterly/annual
        if req.frequency == "Monthly":
            period_premium = base * freq_factor
            monthly_equiv = period_premium
        elif req.frequency == "Quarterly":
            period_premium = base * 3 * freq_factor
            monthly_equiv = period_premium / 3
        elif req.frequency == "Annual":
            period_premium = base * 12 * freq_factor
            monthly_equiv = period_premium / 12
        else:
            period_premium = base
            monthly_equiv = base

        # Apply premium tax
        period_premium_with_tax = round(period_premium * (1 + tax_rate), 2)
        monthly_equiv_with_tax = round(monthly_equiv * (1 + tax_rate), 2)
        annual_equiv_with_tax = round(monthly_equiv_with_tax * 12, 2)

        results.append({
            "insurer": r["insurer"],
            "plan": r["plan"],
            "plan_tier": r["plan_tier"],
            "aoc": r["aoc"],
            "deductible_usd": float(r["deductible_usd"]),
            "coinsurance_pct": float(r["coinsurance_pct"]),
            "oop_max_usd": float(r["oop_max_usd"]) if r["oop_max_usd"] else None,
            "frequency": req.frequency,
            "currency": r["currency"],
            "base_premium_monthly": round(base, 2),
            "frequency_factor": freq_factor,
            "tax_rate": tax_rate,
            "premium": period_premium_with_tax,
            "monthly_equivalent": monthly_equiv_with_tax,
            "annual_equivalent": annual_equiv_with_tax,
        })

    tier_order = {"Silver": 1, "Gold": 2, "Platinum": 3}
    results.sort(key=lambda x: (tier_order.get(x["plan_tier"], 9), x["premium"]))

    return {
        "age": req.age,
        "country": req.country_of_residence,
        "rating_zone": country["loc_zone"],
        "frequency": req.frequency,
        "frequency_factor": freq_factor,
        "tax_rate": tax_rate,
        "results_count": len(results),
        "results": results,
    }

@app.get("/quote")
def quote_get(age: int, country: str, aoc: str = "WWE-USA", deductible_usd: float = 0, coinsurance_pct: float = 0, frequency: str = "Monthly", plan_tier: Optional[str] = None, x_api_key: Optional[str] = Header(None)):
    return quote(QuoteRequest(age=age, country_of_residence=country, aoc=aoc, deductible_usd=deductible_usd, coinsurance_pct=coinsurance_pct, frequency=frequency, plan_tier=plan_tier), x_api_key=x_api_key)
