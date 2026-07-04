-- Tabela za ML detekcije parking mjesta
CREATE TABLE IF NOT EXISTS ml_detection (
    detection_id  SERIAL PRIMARY KEY,
    image_source  VARCHAR(200) NOT NULL DEFAULT 'upload',
    detected_at   TIMESTAMP    NOT NULL DEFAULT now(),
    status        VARCHAR(20)  NOT NULL DEFAULT 'zauzeto'
                      CHECK (status IN ('slobodno', 'zauzeto', 'nepoznato')),
    confidence    FLOAT        CHECK (confidence BETWEEN 0 AND 1),
    vehicle_class VARCHAR(30)  DEFAULT 'car',
    bbox_x1       INT,
    bbox_y1       INT,
    bbox_x2       INT,
    bbox_y2       INT,
    img_width     INT,
    img_height    INT,
    location      GEOGRAPHY(POINT, 4326),
    zone_ref      INTEGER REFERENCES parking_zone(zone_id) ON DELETE SET NULL,
    notes         TEXT         DEFAULT '',
    verified      BOOLEAN      DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_ml_location ON ml_detection USING GIST(CAST(location AS geometry));
CREATE INDEX IF NOT EXISTS idx_ml_status   ON ml_detection(status);
CREATE INDEX IF NOT EXISTS idx_ml_detected ON ml_detection(detected_at);
