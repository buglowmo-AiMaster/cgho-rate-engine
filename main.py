-- ============================================================
-- CGHO Rate Engine — Complete Setup
-- Run this once in Railway's PostgreSQL console
-- ============================================================

-- Tables
CREATE TABLE IF NOT EXISTS insurers (
    id         SERIAL PRIMARY KEY,
    code       VARCHAR(20) UNIQUE NOT NULL,
    name       VARCHAR(100) NOT NULL,
    active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS products (
    id         SERIAL PRIMARY KEY,
    insurer_id INT REFERENCES insurers(id),
    code       VARCHAR(50) NOT NULL,
    name       VARCHAR(100) NOT NULL,
    plan_tier  VARCHAR(20),
    active     BOOLEAN DEFAULT TRUE,
    UNIQUE(insurer_id, code)
);

CREATE TABLE IF NOT EXISTS rating_areas (
    id     SERIAL PRIMARY KEY,
    code   VARCHAR(50) UNIQUE NOT NULL,
    name   VARCHAR(100) NOT NULL,
    region VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS countries (
    id                      SERIAL PRIMARY KEY,
    name                    VARCHAR(100) UNIQUE NOT NULL,
    iso_code                CHAR(2),
    rating_area_location    INT REFERENCES rating_areas(id),
    rating_area_citizenship INT REFERENCES rating_areas(id),
    rating_area_costshare   INT REFERENCES rating_areas(id),
    premium_tax_rate        NUMERIC(6,4) DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rate_rules (
    id                      BIGSERIAL PRIMARY KEY,
    insurer_id              INT REFERENCES insurers(id) NOT NULL,
    product_id              INT REFERENCES products(id) NOT NULL,
    age_min                 SMALLINT NOT NULL,
    age_max                 SMALLINT NOT NULL,
    age_band                VARCHAR(20),
    rating_area_location    INT REFERENCES rating_areas(id),
    rating_area_citizenship INT REFERENCES rating_areas(id),
    rating_area_costshare   INT REFERENCES rating_areas(id),
    aoc                     VARCHAR(20) NOT NULL,
    deductible_usd          NUMERIC(10,2) NOT NULL,
    coinsurance_pct         NUMERIC(5,2) NOT NULL,
    oop_max_usd             NUMERIC(10,2),
    hw_coverage             BOOLEAN DEFAULT FALSE,
    dv_coverage             BOOLEAN DEFAULT FALSE,
    ev_coverage             BOOLEAN DEFAULT FALSE,
    underwriting            VARCHAR(20) DEFAULT 'Standard',
    frequency               VARCHAR(20) DEFAULT 'Monthly',
    currency                CHAR(3) DEFAULT 'USD',
    base_premium            NUMERIC(12,4) NOT NULL,
    effective_date          DATE NOT NULL DEFAULT '2026-02-15',
    expiry_date             DATE,
    source_file             VARCHAR(200),
    loaded_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rate_quote ON rate_rules (
    rating_area_location, aoc, age_min, deductible_usd, coinsurance_pct
);

-- ── Seed: Insurer ──────────────────────────────────────────────────────────

INSERT INTO insurers (code, name) VALUES
    ('CIGNA_CGHO', 'Cigna Global Health Options')
ON CONFLICT (code) DO NOTHING;

-- ── Seed: Rating areas ─────────────────────────────────────────────────────
-- (All 19 Cigna CGHO zones — 3 confirmed by rate verification)

INSERT INTO rating_areas (code, name, region) VALUES
    ('AFRICA_HIGH',       'Africa - High',       'Africa'),
    ('AFRICA_LOW',        'Africa - Low',         'Africa'),
    ('AMERICAS_HIGH',     'Americas - High',      'Americas'),
    ('AMERICAS_MID_HIGH', 'Americas - Mid-High',  'Americas'),
    ('AMERICAS_MIDDLE',   'Americas - Middle',    'Americas'),
    ('AMERICAS_LOW',      'Americas - Low',       'Americas'),
    ('ASIA_HIGH',         'Asia - High',          'Asia'),
    ('ASIA_MID_HIGH',     'Asia - Mid-High',      'Asia'),
    ('ASIA_MIDDLE',       'Asia - Middle',        'Asia'),
    ('ASIA_MID_LOW',      'Asia - Mid-Low',       'Asia'),
    ('ASIA_LOW',          'Asia - Low',           'Asia'),
    ('EUROPE_HIGH',       'Europe - High',        'Europe'),
    ('EUROPE_MID_HIGH',   'Europe - Mid-High',    'Europe'),
    ('EUROPE_MIDDLE',     'Europe - Middle',      'Europe'),
    ('EUROPE_MID_LOW',    'Europe - Mid-Low',     'Europe'),
    ('EUROPE_LOW',        'Europe - Low',         'Europe'),
    ('MIDDLE_EAST',       'Middle East',          'Middle East'),
    ('OCEANIA',           'Oceania',              'Oceania'),
    ('UNITED_STATES',     'United States',        'United States')
ON CONFLICT (code) DO NOTHING;

-- ── Seed: Products ─────────────────────────────────────────────────────────

INSERT INTO products (insurer_id, code, name, plan_tier)
SELECT id, 'CGHO_SILVER',   'CGHO Silver',   'Silver'   FROM insurers WHERE code = 'CIGNA_CGHO'
ON CONFLICT (insurer_id, code) DO NOTHING;

INSERT INTO products (insurer_id, code, name, plan_tier)
SELECT id, 'CGHO_GOLD',     'CGHO Gold',     'Gold'     FROM insurers WHERE code = 'CIGNA_CGHO'
ON CONFLICT (insurer_id, code) DO NOTHING;

INSERT INTO products (insurer_id, code, name, plan_tier)
SELECT id, 'CGHO_PLATINUM', 'CGHO Platinum', 'Platinum' FROM insurers WHERE code = 'CIGNA_CGHO'
ON CONFLICT (insurer_id, code) DO NOTHING;

-- ── Seed: Countries (verified zones) ──────────────────────────────────────

INSERT INTO countries (name, iso_code, rating_area_location, rating_area_citizenship, rating_area_costshare)
VALUES
    ('Hong Kong',       'HK', (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),     (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),     (SELECT id FROM rating_areas WHERE code='ASIA_HIGH')),
    ('Singapore',       'SG', (SELECT id FROM rating_areas WHERE code='ASIA_MID_HIGH'), (SELECT id FROM rating_areas WHERE code='ASIA_MID_HIGH'), (SELECT id FROM rating_areas WHERE code='ASIA_MID_HIGH')),
    ('Thailand',        'TH', (SELECT id FROM rating_areas WHERE code='ASIA_MID_LOW'),  (SELECT id FROM rating_areas WHERE code='ASIA_MID_LOW'),  (SELECT id FROM rating_areas WHERE code='ASIA_MID_LOW')),
    ('France',          'FR', (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),   (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),   (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH')),
    ('United Kingdom',  'GB', (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),   (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),   (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH')),
    ('China',           'CN', (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),     (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),     (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'))
ON CONFLICT (name) DO NOTHING;

-- ── Seed: Verified rates (confirmed against Cigna quote tool, March 2026) ──
-- Plan: Silver | Inpatient only | WWE-USA | 0% coinsurance | Monthly | USD
-- Citizenship confirmed irrelevant — location zone drives pricing

INSERT INTO rate_rules (
    insurer_id, product_id,
    age_min, age_max, age_band,
    rating_area_location, rating_area_citizenship, rating_area_costshare,
    aoc, deductible_usd, coinsurance_pct, oop_max_usd,
    hw_coverage, dv_coverage, ev_coverage,
    underwriting, frequency, currency,
    base_premium, effective_date, source_file
)

-- Age 51 | HK | $0 ded → $728.06
SELECT i.id, p.id, 51, 51, '50 to 59',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 728.06, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 51 | HK | $10,000 ded → $409.01
SELECT i.id, p.id, 51, 51, '50 to 59',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 10000, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 409.01, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 53 | HK | $0 ded → $761.07
SELECT i.id, p.id, 53, 53, '50 to 59',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 761.07, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 53 | Singapore | $0 ded → $609.99
SELECT i.id, p.id, 53, 53, '50 to 59',
    (SELECT id FROM rating_areas WHERE code='ASIA_MID_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_MID_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 609.99, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 53 | Thailand | $0 ded → $373.14
SELECT i.id, p.id, 53, 53, '50 to 59',
    (SELECT id FROM rating_areas WHERE code='ASIA_MID_LOW'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_MID_LOW'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 373.14, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 60 | HK | $0 ded → $1,024.32
SELECT i.id, p.id, 60, 60, '60 to 69',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 1024.32, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 65 | HK | $0 ded → $1,338.58
SELECT i.id, p.id, 65, 65, '60 to 69',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 1338.58, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Ages 70-74 | HK | $0 ded → $1,864.76 (flat band — confirmed ages 70 and 72)
SELECT i.id, p.id, 70, 74, '70 to 74',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 1864.76, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 75 | HK | $0 ded → $2,323.82
SELECT i.id, p.id, 75, 75, '75 to 79',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 2323.82, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 77 | HK | $0 ded → $2,513.40
SELECT i.id, p.id, 77, 77, '75 to 79',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 2513.40, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 80 | HK | $0 ded → $2,827.49
SELECT i.id, p.id, 80, 80, '80 to 84',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 2827.49, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO'

UNION ALL

-- Age 85 | HK | $0 ded → $3,386.21
SELECT i.id, p.id, 85, 85, '85 to 89',
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    (SELECT id FROM rating_areas WHERE code='EUROPE_HIGH'),
    (SELECT id FROM rating_areas WHERE code='ASIA_HIGH'),
    'WWE-USA', 0, 0, NULL, false, false, false,
    'Standard', 'Monthly', 'USD', 3386.21, '2026-02-15', 'verified_mar2026'
FROM insurers i JOIN products p ON p.insurer_id=i.id AND p.code='CGHO_SILVER' WHERE i.code='CIGNA_CGHO';

-- ── Verify ─────────────────────────────────────────────────────────────────
SELECT age_min, ra.name AS zone, deductible_usd, base_premium
FROM rate_rules r
JOIN rating_areas ra ON r.rating_area_location = ra.id
ORDER BY ra.name, age_min, deductible_usd;
