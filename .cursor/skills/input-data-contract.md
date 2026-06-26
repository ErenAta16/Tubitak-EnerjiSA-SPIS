# Skill: input-data-contract

Authoritative description of the raw inputs. Treat as ground truth so you never
re-profile the files from scratch. Verify these assumptions once in the loader,
then rely on them.

## Files in `data/raw/`

1. `Canakkale_Uretim_isinim_verileri.xlsx`  (sheet "Canakkale Hibrit GES ")
   The backbone. 1026 daily rows, 2023-01-01 .. 2025-10-22, no missing dates.
   Columns (Turkish header -> meaning):
   - TARIH                  date (daily)
   - EFLATUN OG NET URETIM  feeder-1 net production (only ~333 recent rows populated)
   - HIPOKRAT OG NET URETIM feeder-2 net production (only ~333 recent rows populated)
   - GUNLUK TOTAL URETIM    daily total production  (COMPLETE, all 1026 rows)
   - ISINIM                 daily integrated irradiation (COMPLETE, all 1026 rows)
   - DURUM                  empty, ignore
   Use GUNLUK TOTAL URETIM and ISINIM as the primary pair. PI = production / irradiation.

2. `Canakkale_Hibrit_GES_Duruslar.xlsx`  (sheet "Gerceklesen Duruslar")
   88 downtime events, 2023-02-20 .. 2025-10-22. Key columns:
   Baslangic Tarihi, Bitis Tarihi, Durus S.(sa) [hours, comma decimal],
   Durus Nedeni in {Planli Calisma, Harici Mucbir, Yillik Bakim, Plansiz Calisma,
   Dahili Mucbir, Kisitlama, Ariza}, Curtailment Degeri, Durusa Neden Olan Sistemler.
   Use to flag/exclude affected days from soiling fits.

3. `Canakkale-1_Hibrit_GES_gunluk_inverter_uretimi.xlsx` (sheet "ÇANAKKALE 1")
   11 inverters (INV1..INV11) daily active power + one meteo irradiance column,
   2024-11-26 .. 2025-10-23. WARNING: rows before 2025-01-23 are all zeros
   (commissioning). Effective data starts 2025-01-23. Use only for recent
   inverter-level underperformance / anomaly detection, not for the long PI series.

4. `Panel_yikama_tarihleri.txt`  7 washing events, 2023-09-18 .. 2025-03-21.
   Format: "<n>. yikama <start>-<end> <method>" where method is
   "Fircali-Solusyonlu" (brush + solution) or "Robot-Solusyonsuz" (robot, no solution).
   Defines inter-wash segments. NOTE: the file labels two events as "5." (data entry
   slip); order by date, not by the printed index.

## Physical constants (put in config.py)
- Module: Jinko JKM525-545M, Pmax temp coeff -0.35 %/degC, NOCT 45 degC, ref 25 degC.
- Inverter: Sungrow SG250HX, 250 kVA AC, 11 units. Two feeders: EFLATUN, HIPOKRAT.
- Location: set PLANT_LAT/PLANT_LON in local .env (precise coords not committed; coarse public default otherwise).

## Decimal/locale traps
Some numeric cells use comma as decimal separator (e.g. "7,65"). Coerce explicitly.
