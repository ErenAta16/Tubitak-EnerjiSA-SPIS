# Field visit support pack

Checklist for on-site verification at Canakkale Hybrid GES. Balikesir section is a placeholder until Enerjisa supplies operational data.

## Priority field action — reference irradiance sensor

**CRITICAL:** Inspect and clean the **reference irradiance sensor** and verify whether it soils at the same rate as the PV modules. SPIS soiling rates are a **lower bound** when the sensor co-soils with modules; confirming sensor condition directly bounds how conservative the modeled wash interval is.

- [ ] Visual inspection of reference sensor glass/soiling
- [ ] Compare sensor reading to a clean handheld reference on a clear day
- [ ] Log last sensor cleaning date; photograph condition
- [ ] Note whether sensor is co-located with soiled module strings

## Canakkale — inverter inspection priorities (P6 descriptive ranking)

Threshold: median relative performance < 0.95 vs daily peer median (not fault diagnosis).

### Inspect first (lowest median relative performance)

- [ ] **INV2**: expected peer median = 1.00, observed median = 0.941 **candidate underperformer**
- [ ] **INV4**: expected peer median = 1.00, observed median = 0.996
- [ ] **INV3**: expected peer median = 1.00, observed median = 0.997

### All flagged candidate underperformers

- [ ] **INV2** median relative 0.941

## Canakkale — soiling / washing context (P4)

- Model-optimal wash interval **T* = 99 days** (rate CI band 81..139 days).
- Compare actual inter-wash gaps in the washing log to T*.
- Remember: true soiling may exceed model if the reference sensor co-soils.

## Canakkale — general checklist

- [ ] Confirm washing method used on last event matches log (brush vs robot).
- [ ] Check for string/feeder imbalance between EFLATUN and HIPOKRAT.
- [ ] Review inverter fault alarms for units ranked below peer median.
- [ ] Note any curtailment or grid events during low relative-performance days.

## Balikesir — pending (PROVISIONAL)

- Coordinates: **PROVISIONAL** (39.748, 27.996) — PROVISIONAL placeholder for Balikesir RES area pending KMZ confirmation; no operational SCADA files present under data/raw/balikesir/.
- Environmental comparison only until operational data supplied.

### Checklist when Balikesir data is available

- [ ] Confirm coordinates from KMZ / as-built layout
- [ ] Collect production + irradiance workbook (Canakkale-equivalent schema)
- [ ] Collect downtime log and washing dates
- [ ] Repeat reference irradiance sensor soiling check
- [ ] Run full SPIS pipeline with `operational_data_available=True`

## Site registry

- **canakkale** (Canakkale Hybrid GES): lat=39.86857, lon=26.24152, panel=Jinko JKM535 bifacial, operational_data=True, status=CONFIRMED
- **balikesir** (Balikesir RES (provisional)): lat=39.748, lon=27.996, panel=Jinko JKM535 bifacial, operational_data=False, status=PROVISIONAL
