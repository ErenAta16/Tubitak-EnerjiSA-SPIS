# PVDAQ 2107 public real-site snapshot

This directory contains a compact, processed snapshot of **public NREL/OEDI PVDAQ
system 2107** data for the SPIS public dashboard. The source is the U.S. Department
of Energy [Open Energy Data Initiative PVDAQ archive](https://data.openei.org/submissions/4568);
system 2107 is documented in the
[OEDI PVDAQ data guide](https://github.com/openEDI/documentation/blob/main/pvdaq.md).

The snapshot reuses the PVDAQ 2107 processing and validation from the project's
external-validation study in `reports/EXTERNAL_VALIDATION.md`. It is
safe for public distribution and contains no Enerjisa data or fields, no Enerjisa
production figures, and no Canakkale coordinates.

Regenerate from the locally cached public OEDI inputs and validated processed output:

```bash
python scripts/generate_public_examples.py
```
