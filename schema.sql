-- Pametni sistem za upravljanje parking mestima -- Deo 1: relaciona sema
CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS sensor CASCADE;
DROP TABLE IF EXISTS payment CASCADE;
DROP TABLE IF EXISTS parking_session CASCADE;
DROP TABLE IF EXISTS vehicle CASCADE;
DROP TABLE IF EXISTS driver CASCADE;
DROP TABLE IF EXISTS parking_spot CASCADE;
DROP TABLE IF EXISTS parking_zone CASCADE;

-- 1. Parking zona (npr. "Zeleni venac", "Slavija")
CREATE TABLE parking_zone (
    zone_id            SERIAL PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    address             VARCHAR(200),
    city                VARCHAR(100) NOT NULL,
    total_capacity      INTEGER NOT NULL CHECK (total_capacity >= 0),
    hourly_rate         NUMERIC(6, 2) NOT NULL CHECK (hourly_rate >= 0),
    has_covered_spots   BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP NOT NULL DEFAULT now()
);

-- 2. Parking mesto unutar zone (sadrzi i geo-lokaciju za Deo 2)
CREATE TABLE parking_spot (
    spot_id         SERIAL PRIMARY KEY,
    zone_id         INTEGER NOT NULL REFERENCES parking_zone (zone_id) ON DELETE CASCADE,
    spot_number     VARCHAR(10) NOT NULL,
    spot_type       VARCHAR(20) NOT NULL CHECK (spot_type IN ('standard', 'invalidski', 'elektro', 'moto')),
    is_covered      BOOLEAN DEFAULT FALSE,
    status          VARCHAR(20) NOT NULL DEFAULT 'slobodno'
                        CHECK (status IN ('slobodno', 'zauzeto', 'rezervisano', 'van_upotrebe')),
    location        GEOGRAPHY(POINT, 4326),
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (zone_id, spot_number)
);

-- 3. Vozac
CREATE TABLE driver (
    driver_id           SERIAL PRIMARY KEY,
    first_name          VARCHAR(50) NOT NULL,
    last_name           VARCHAR(50) NOT NULL,
    email               VARCHAR(100) UNIQUE NOT NULL,
    phone               VARCHAR(30),
    license_number      VARCHAR(30) UNIQUE NOT NULL,
    registration_date   DATE NOT NULL DEFAULT CURRENT_DATE
);

-- 4. Vozilo
CREATE TABLE vehicle (
    vehicle_id      SERIAL PRIMARY KEY,
    driver_id       INTEGER NOT NULL REFERENCES driver (driver_id) ON DELETE CASCADE,
    license_plate   VARCHAR(20) UNIQUE NOT NULL,
    make            VARCHAR(50),
    model           VARCHAR(50),
    color           VARCHAR(30),
    vehicle_type    VARCHAR(20) NOT NULL DEFAULT 'automobil'
                        CHECK (vehicle_type IN ('automobil', 'motocikl', 'kombi', 'elektricno'))
);

-- 5. Sesija parkiranja (dolazak/odlazak vozila na konkretno mesto)
CREATE TABLE parking_session (
    session_id      SERIAL PRIMARY KEY,
    spot_id         INTEGER NOT NULL REFERENCES parking_spot (spot_id) ON DELETE CASCADE,
    vehicle_id      INTEGER NOT NULL REFERENCES vehicle (vehicle_id) ON DELETE CASCADE,
    check_in_time   TIMESTAMP NOT NULL,
    check_out_time  TIMESTAMP,
    status          VARCHAR(20) NOT NULL DEFAULT 'aktivna'
                        CHECK (status IN ('aktivna', 'zavrsena', 'otkazana')),
    total_amount    NUMERIC(8, 2)
);

-- 6. Placanje vezano za sesiju
CREATE TABLE payment (
    payment_id      SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES parking_session (session_id) ON DELETE CASCADE,
    amount          NUMERIC(8, 2) NOT NULL CHECK (amount >= 0),
    payment_method  VARCHAR(20) NOT NULL CHECK (payment_method IN ('kartica', 'gotovina', 'aplikacija')),
    payment_status  VARCHAR(20) NOT NULL DEFAULT 'placeno'
                        CHECK (payment_status IN ('placeno', 'na_cekanju', 'neuspesno')),
    payment_time    TIMESTAMP NOT NULL DEFAULT now()
);

-- 7. Senzor zauzetosti na parking mestu
CREATE TABLE sensor (
    sensor_id           SERIAL PRIMARY KEY,
    spot_id             INTEGER NOT NULL UNIQUE REFERENCES parking_spot (spot_id) ON DELETE CASCADE,
    sensor_type         VARCHAR(30) NOT NULL CHECK (sensor_type IN ('ultrazvucni', 'kamera', 'infracrveni')),
    install_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    battery_level       INTEGER CHECK (battery_level BETWEEN 0 AND 100),
    last_status         VARCHAR(20) CHECK (last_status IN ('slobodno', 'zauzeto', 'nepoznato')),
    last_reading_time   TIMESTAMP
);

CREATE INDEX idx_parking_spot_zone ON parking_spot (zone_id);
CREATE INDEX idx_vehicle_driver ON vehicle (driver_id);
CREATE INDEX idx_session_spot ON parking_session (spot_id);
CREATE INDEX idx_session_vehicle ON parking_session (vehicle_id);
CREATE INDEX idx_payment_session ON payment (session_id);
CREATE INDEX idx_sensor_spot ON sensor (spot_id);
