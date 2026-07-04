# Washing Schedule Optimization

## Production units

SCADA `production` (GUNLUK TOTAL URETIM) is **kWh/day**.
production is kWh/day: peak-day production/irradiation implied kW is consistent with installed AC nameplate within measurement noise.
Plant AC capacity is derived from inverter nameplate at runtime (absolute kW withheld; proprietary).

## Clean-baseline daily energy

Pooled clean-baseline daily energy is computed per segment from SCADA at runtime (absolute value withheld; proprietary).

## Soiling model

Linear loss L(t)=r*t with clear-sky pooled r=0.00125/day (CI band 0.00064..0.00185).
Observed r is a **lower bound** (irradiance-sensor co-soiling); true optimal
intervals may be **shorter** than model output.

## Central recommendation

Wash cost: **150,000 TL** (ASSUMED; Enerjisa pending).
PTF price: **2,189.30 TL/MWh** (real_2023; 2023 annual mean).

Optimal interval T* = **99 days** (rate CI: 81..139 days).

### vs previous assumed 2000 TL/MWh central price

Previous T* at assumed 2000 TL/MWh: **104 days**.
Real 2023 price T*: **99 days** (delta -5 days).

## Price and wash-cost caveats

(a) PTF is **2023-only, nominal TL, single-year**; 2024-2025 not supplied.
(b) Wash cost remains **ASSUMED**; if Enerjisa supplies a current-TL figure without rebasing the 2023 PTF, the nominal 2023 price biases T* **longer** (cautious verdict on over/under-washing).
Sensitivity sweep over ASSUMED PTF range 1000-3500 TL/MWh covers missing years.

## Actual vs model cadence

Mean actual inter-wash gap: **79 days** (8 of 30 swept cost/price combos are near-optimal at point rate).

## Caveats

- Modest soiling rates; pollution is not supported as a daily driver.
- Rain provides parallel natural cleaning (mean event recovery ~0).
- Wash cost ASSUMED; PTF central is real 2023 only.

## What flips the recommendation

- Lower wash cost or higher PTF -> shorter T* (wash more often).
- Higher wash cost or lower PTF -> longer T*.
- True soiling rate above the clear-sky pooled point estimate -> shorter T*.

## Assumptions logged

- `wash_cost_tl_sweep` = (50000.0, 100000.0, 150000.0, 200000.0, 300000.0) (ASSUMED): ASSUMED plausible range for full-plant brush/robot wash (TBD from Enerjisa); 50k-300k TL spans a plausible TL/kW_AC range for nominal plant AC capacity.
- `wash_cost_tl_central` = 150000.0 (ASSUMED): ASSUMED plausible range for full-plant brush/robot wash (TBD from Enerjisa); 50k-300k TL spans a plausible TL/kW_AC range for nominal plant AC capacity.
- `ptf_tl_mwh_sweep` = (1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 3500.0) (ASSUMED): ASSUMED sensitivity range for 2024-2025 when only 2023 PTF CSV is available; sweep grid points are not realized prices.
- `ptf_tl_mwh_central_legacy_assumed` = 2000.0 (ASSUMED): Previous central price before real 2023 PTF ingest
- `ptf_tl_mwh_central` = 2189.302656392694 (real_2023): REAL 2023 annual-mean PTF from EPIAS CSV in data/external/epias_ptf/; 2023-only nominal TL; 2024-2025 not supplied. If wash cost is later given in current TL without rebasing, the 2023 nominal price biases T* longer.
- `linear_soiling_model` = L(t)=r*t: Theil-Sen clear-sky pooled rate; loss fraction grows linearly with days since wash
- `sensor_co_soiling` = lower_bound: Reference irradiance co-soiling cancels part of loss in PI; true r may be higher
