-- DuckDB versions of the Energiewende-Monitor rpt views for the CI sample (sql/ddl/030_views.sql, monitor
-- commit b399d0144c22c355cf56e2284d61aac158ed0b5a). Differences: date_trunc instead of DATETRUNC, interval
-- arithmetic instead of DATEADD, 'Europe/Berlin' instead of the Windows zone name, coalesce instead of ISNULL.
-- Requires SET TimeZone = 'UTC' (set by sample.load_duckdb) so that AT TIME ZONE 'UTC' reads ts_utc as UTC.
CREATE SCHEMA IF NOT EXISTS rpt;

CREATE OR REPLACE VIEW rpt.v_dim_datum AS
SELECT datum_key, datum, jahr, quartal, monat, monat_name_de, monat_name_en, jahr_monat, iso_jahr, iso_woche, tag,
       wochentag_nr, wochentag_de, wochentag_en, ist_wochenende, saison_de, viertelstunden
FROM dw.dim_datum;

CREATE OR REPLACE VIEW rpt.v_dim_zeit AS
SELECT zeit_key, uhrzeit, stunde, viertelstunde, tageszeit_de, tageszeit_en FROM dw.dim_zeit;

CREATE OR REPLACE VIEW rpt.v_dim_energietraeger AS
SELECT energietraeger_key, smard_filter_id, name_de, name_en, kategorie_de, kategorie_en, sortierung, farbe_hex
FROM dw.dim_energietraeger;

CREATE OR REPLACE VIEW rpt.v_dim_region AS
SELECT region_key, smard_code, name_de, name_en, typ_de, typ_en FROM dw.dim_region;

CREATE OR REPLACE VIEW rpt.v_dim_bundesland AS
SELECT bundesland_key, name_de, rtrim(kuerzel) AS kuerzel, ist_awz FROM dw.dim_bundesland;

CREATE OR REPLACE VIEW rpt.v_erzeugung AS
SELECT region_key, energietraeger_key, ts_utc, datum_key, zeit_key, aufloesung_min, erzeugung_mwh
FROM dw.fact_erzeugung;

CREATE OR REPLACE VIEW rpt.v_last AS
SELECT region_key, ts_utc, datum_key, zeit_key, aufloesung_min, netzlast_mwh, residuallast_mwh, pumpspeicher_verbrauch_mwh
FROM dw.fact_last;

CREATE OR REPLACE VIEW rpt.v_preis AS
SELECT region_key, ts_utc, datum_key, zeit_key, day_ahead_eur_mwh FROM dw.fact_preis;

CREATE OR REPLACE VIEW rpt.v_last_stunde AS
SELECT region_key,
       date_trunc('hour', ts_utc) AS stunde_utc,
       MIN(datum_key) AS datum_key,
       MIN(zeit_key) AS zeit_key,
       COUNT(netzlast_mwh) AS viertelstunden_netzlast_mwh,
       COUNT(residuallast_mwh) AS viertelstunden_residuallast_mwh,
       COUNT(pumpspeicher_verbrauch_mwh) AS viertelstunden_pumpspeicher_verbrauch_mwh,
       CASE WHEN COUNT(netzlast_mwh) = 4 THEN SUM(netzlast_mwh) END AS netzlast_mwh,
       CASE WHEN COUNT(residuallast_mwh) = 4 THEN SUM(residuallast_mwh) END AS residuallast_mwh,
       CASE WHEN COUNT(pumpspeicher_verbrauch_mwh) = 4 THEN SUM(pumpspeicher_verbrauch_mwh) END AS pumpspeicher_verbrauch_mwh
FROM dw.fact_last
WHERE aufloesung_min = 15
GROUP BY region_key, date_trunc('hour', ts_utc);

CREATE OR REPLACE VIEW rpt.v_preis_last_stunde AS
SELECT p.region_key, p.ts_utc AS stunde_utc, p.datum_key, p.zeit_key, p.day_ahead_eur_mwh,
       l.netzlast_mwh, l.residuallast_mwh
FROM dw.fact_preis p
LEFT JOIN rpt.v_last_stunde l ON l.region_key = p.region_key AND l.stunde_utc = p.ts_utc;

CREATE OR REPLACE VIEW rpt.v_negative_preisphasen AS
WITH neg AS (
    SELECT region_key, ts_utc, datum_key, day_ahead_eur_mwh,
           ROW_NUMBER() OVER (PARTITION BY region_key ORDER BY ts_utc) AS rn
    FROM dw.fact_preis
    WHERE day_ahead_eur_mwh < 0
), grp AS (
    SELECT region_key, ts_utc, datum_key, day_ahead_eur_mwh, ts_utc - rn * INTERVAL 1 HOUR AS grp_key FROM neg
), phase AS (
    SELECT region_key, MIN(datum_key) AS start_datum_key, MIN(ts_utc) AS start_utc,
           MAX(ts_utc) + INTERVAL 1 HOUR AS ende_utc, COUNT(*) AS stunden,
           MIN(day_ahead_eur_mwh) AS min_preis_eur_mwh, AVG(day_ahead_eur_mwh) AS avg_preis_eur_mwh
    FROM grp
    GROUP BY region_key, grp_key
)
SELECT region_key, start_datum_key, start_utc, ende_utc,
       CAST((start_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Berlin' AS TIMESTAMP) AS start_lokal,
       CAST((ende_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Berlin' AS TIMESTAMP) AS ende_lokal,
       stunden, min_preis_eur_mwh, avg_preis_eur_mwh
FROM phase;

CREATE OR REPLACE VIEW rpt.v_dq_luecken AS
WITH span AS (
    SELECT region_key, energietraeger_key, MIN(datum_key) AS von, MAX(datum_key) AS bis
    FROM dw.fact_erzeugung WHERE aufloesung_min = 15
    GROUP BY region_key, energietraeger_key
), erwartet AS (
    SELECT s.region_key, s.energietraeger_key, d.jahr_monat, SUM(d.viertelstunden) AS erwartet
    FROM span s JOIN dw.dim_datum d ON d.datum_key BETWEEN s.von AND s.bis
    GROUP BY s.region_key, s.energietraeger_key, d.jahr_monat
), vorhanden AS (
    SELECT f.region_key, f.energietraeger_key, d.jahr_monat, COUNT(f.erzeugung_mwh) AS vorhanden
    FROM dw.fact_erzeugung f JOIN dw.dim_datum d ON d.datum_key = f.datum_key
    WHERE f.aufloesung_min = 15
    GROUP BY f.region_key, f.energietraeger_key, d.jahr_monat
)
SELECT r.smard_code AS region, e.name_de AS energietraeger, x.jahr_monat, x.erwartet,
       coalesce(v.vorhanden, 0) AS vorhanden, x.erwartet - coalesce(v.vorhanden, 0) AS fehlend
FROM erwartet x
LEFT JOIN vorhanden v ON v.region_key = x.region_key AND v.energietraeger_key = x.energietraeger_key
                     AND v.jahr_monat = x.jahr_monat
JOIN dw.dim_region r ON r.region_key = x.region_key
JOIN dw.dim_energietraeger e ON e.energietraeger_key = x.energietraeger_key;

CREATE OR REPLACE VIEW rpt.v_kapazitaet AS
SELECT k.datum_key, d.jahr_monat, k.bundesland_key, k.energietraeger_key, k.zubau_mw, k.anzahl_zubau, k.abgang_mw,
       k.anzahl_abgang, k.anfangsbestand_mw, k.anfangsbestand_anzahl, k.bestand_mw, k.bestand_anzahl
FROM dw.fact_kapazitaet k
JOIN dw.dim_datum d ON d.datum_key = k.datum_key;
