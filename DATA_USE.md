# Data use and confidentiality

## What this repository contains

This repository publishes **methodology, code, configuration templates, and
aggregated written results** for the TUBITAK 2209-B project *Solar Performance
Improvement System (SPIS)*. It does **not** include Enerjisa proprietary SCADA
workbooks, washing logs, downtime records, inverter exports, or any other raw
operational plant data.

Derived numerical tables and figure CSV companions are generated locally from
gitignored inputs under `data/raw/` and `data/processed/` and are **not** redistributable
as Enerjisa data even when reproduced by third parties.

## Enerjisa partnership data

Raw Canakkale Hybrid GES operational data was accessed under the Enerjisa
partnership for academic research. Those files remain outside version control.
Public release of **derived** operational results is subject to the partner's
permission. Confirm release scope with the Enerjisa advisor before citing plant-specific
absolute production, capacity, or location details outside the partnership.

## Third-party reuse

| Asset | License / terms |
|---|---|
| SPIS **source code** | [MIT License](LICENSE) |
| Enerjisa-derived **data or results** | **Not licensed** — do not copy, publish, or redistribute |
| Public external datasets (NASA POWER, CAMS, DKASC, PVDAQ, EPIAS CSVs you fetch yourself) | Follow each provider's terms |

You may reuse, modify, and redistribute the **code** under MIT. You may **not**
treat any Enerjisa-derived dataset or reproduced plant metrics as open data.

## Local configuration

Precise Canakkale plant coordinates belong in a local `.env` file (`PLANT_LAT`,
`PLANT_LON`) and are not committed. See `.env.example`.

## Citation

If you use the SPIS code or methods, cite:

> Eren ATA (2026). *Solar Performance Improvement System (SPIS)* — TUBITAK 2209-B
> research engine for PV soiling analysis and washing-schedule optimization.
> https://github.com/ErenAta16/Tubitak-EnerjiSA-SPIS

Adjust the URL if the repository moves.
