# P4 Washing Schedule Optimization

## Production units

SCADA `production` (GUNLUK TOTAL URETIM) is **kWh/day**.
production is kWh/day: peak-day production/irradiation implied kW ~2748 matches 11x250 kW AC within measurement noise.
Plant AC capacity: 2750 kW (11 x SG250HX).

## Clean-baseline daily energy

Pooled clean-baseline energy (median of segment post-wash baselines): **11131 kWh/day**.

## Soiling model

Linear loss L(t)=r*t with P3.5 clear-sky pooled r=0.00125/day (CI band 0.00064..0.00185).
Observed r is a **lower bound** (irradiance-sensor co-soiling); true optimal
intervals may be **shorter** than model output.

## Central recommendation (ASSUMED costs until Enerjisa supplies values)

Wash cost: **150,000 TL** (ASSUMED plausible range for full-plant brush/robot wash (TBD from Enerjisa); 50k-300k TL spans ~18-109 TL/kW_AC for 2750 kW.).
PTF price: **2,000 TL/MWh** (ASSUMED Turkish day-ahead PTF range when EPTR credentials absent; replace with eptr2 monthly averages when EPTR_USERNAME/PASSWORD set.).

Optimal interval T* = **104 days** (rate CI: 85..145 days).

## Actual vs model cadence

Mean actual inter-wash gap: **79 days** (8 of 30 swept cost/price combos are near-optimal at point rate).

## Caveats

- Modest soiling rates; pollution not a daily driver (P3.5).
- Rain provides parallel natural cleaning (mean event recovery ~0).
- All wash costs and PTF prices in this run are ASSUMED sweeps.

## What flips the recommendation

- Lower wash cost or higher PTF -> shorter T* (wash more often).
- Higher wash cost or lower PTF -> longer T*.
- True soiling rate above P3.5 point estimate -> shorter T*.

## Assumptions logged

- `wash_cost_tl_sweep` = (50000.0, 100000.0, 150000.0, 200000.0, 300000.0) (ASSUMED): ASSUMED plausible range for full-plant brush/robot wash (TBD from Enerjisa); 50k-300k TL spans ~18-109 TL/kW_AC for 2750 kW.
- `wash_cost_tl_central` = 150000.0 (ASSUMED): ASSUMED plausible range for full-plant brush/robot wash (TBD from Enerjisa); 50k-300k TL spans ~18-109 TL/kW_AC for 2750 kW.
- `ptf_tl_mwh_sweep` = (1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 3500.0) (ASSUMED): ASSUMED Turkish day-ahead PTF range when EPTR credentials absent; replace with eptr2 monthly averages when EPTR_USERNAME/PASSWORD set.
- `ptf_tl_mwh_central` = 2000.0 (ASSUMED): ASSUMED Turkish day-ahead PTF range when EPTR credentials absent; replace with eptr2 monthly averages when EPTR_USERNAME/PASSWORD set.
- `linear_soiling_model` = L(t)=r*t (P3.5): Theil-Sen clear-sky pooled rate; loss fraction grows linearly with days since wash
- `sensor_co_soiling` = lower_bound (P3.5 caveat): Reference irradiance co-soiling cancels part of loss in PI; true r may be higher
