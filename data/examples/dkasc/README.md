# DKASC Alice Springs public real-site snapshot

This directory contains a compact, processed snapshot of **DKASC Alice Springs
array 14** (Kyocera fixed-tilt research array), selected because it has the narrowest
confidence interval among the four arrays in the project's external-validation
study. The source is Desert Knowledge Australia Solar Centre's public
[Alice Springs data download](https://www.dkasolarcentre.com.au/download?location=alice-springs);
reuse remains subject to the provider's
[terms and citation requirements](https://dkasolarcentre.com.au/download/terms-conditions).

The snapshot reuses the validation workflow from the project's external-validation
study documented in `reports/EXTERNAL_VALIDATION.md`. It is public data and contains no Enerjisa data or
fields, no Enerjisa production figures, and no Canakkale coordinates.

Regenerate from the locally cached public DKASC, NASA POWER, and CAMS inputs:

```bash
python scripts/generate_public_examples.py
```
