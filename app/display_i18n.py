"""Localized display helpers for the Streamlit UI (no Streamlit imports)."""

from __future__ import annotations

import re

from app.models import SAMPLE_UPLOAD_KEY, DashboardSnapshot
from spis.demo_plant import DEMO_PLANT_KEY
from spis.external_validation import ALICE_SPRINGS_SITE_KEY
from spis.sites import DEFAULT_SITE

BACKEND_MESSAGES: dict[str, tuple[str, str]] = {
    "Synthetic demo plant loaded (no real plant data).": (
        "Synthetic demo plant loaded (no real plant data).",
        "Sentetik demo santral yüklendi (gerçek santral verisi yok).",
    ),
    (
        "Built-in sample upload (120 days, synthetic soiling ~0.15%/day). "
        "Upload your own CSV in the sidebar to replace this preview."
    ): (
        "Built-in sample upload (120 days, synthetic soiling ~0.15%/day). "
        "Upload your own CSV in the sidebar to replace this preview.",
        "Gömülü örnek yükleme (120 gün, sentetik kirlenme ~%0,15/gün). "
        "Önizlemeyi değiştirmek için sidebar'dan kendi CSV'nizi yükleyin.",
    ),
    "Canakkale example loaded from local processed SPIS outputs.": (
        "Canakkale example loaded from local processed SPIS outputs.",
        "Çanakkale örneği yerel SPIS çıktılarından yüklendi.",
    ),
    "Alice Springs example loaded from local external validation outputs.": (
        "Alice Springs example loaded from local external validation outputs.",
        "Alice Springs örneği yerel dış doğrulama çıktılarından yüklendi.",
    ),
    "Example data not built yet. Run the SPIS pipeline locally first.": (
        "Example data not built yet. Run the SPIS pipeline locally first.",
        "Örnek veri henüz üretilmedi. Önce SPIS pipeline'ını yerelde çalıştırın.",
    ),
    "Uploaded file is empty.": (
        "Uploaded file is empty.",
        "Yüklenen dosya boş.",
    ),
    "Could not read the CSV file. Save as UTF-8 comma-separated text.": (
        "Could not read the CSV file. Save as UTF-8 comma-separated text.",
        "CSV okunamadı. UTF-8 ve virgülle ayrılmış metin olarak kaydedin.",
    ),
    "Some date values could not be parsed (use YYYY-MM-DD).": (
        "Some date values could not be parsed (use YYYY-MM-DD).",
        "Bazı tarihler çözümlenemedi (YYYY-MM-DD kullanın).",
    ),
    "production and irradiation must be numeric on all rows.": (
        "production and irradiation must be numeric on all rows.",
        "production ve irradiation tüm satırlarda sayısal olmalı.",
    ),
    "production and irradiation must be >= 0.": (
        "production and irradiation must be >= 0.",
        "production ve irradiation >= 0 olmalı.",
    ),
    "Zero irradiation days are not allowed (performance index would divide by zero).": (
        "Zero irradiation days are not allowed (performance index would divide by zero).",
        "Sıfır ışınım günlerine izin verilmez (performans endeksi sıfıra böler).",
    ),
    "validated_rows": (
        "Validated {count} daily rows.",
        "{count} günlük satır doğrulandı.",
    ),
    "missing_columns": (
        "Missing required columns: {columns}. Expected: date, production, irradiation.",
        "Eksik sütunlar: {columns}. Beklenen: date, production, irradiation.",
    ),
    "too_few_rows": (
        "Only {count} rows after parsing; provide at least 30 daily rows.",
        "Ayrıştırma sonrası yalnızca {count} satır; en az 30 günlük satır girin.",
    ),
    "Upload CSV has no pollution columns; daily HAC pollution test was not run.": (
        "Upload CSV has no pollution columns; daily HAC pollution test was not run.",
        "Yüklenen CSV'de kirlilik sütunu yok; günlük HAC kirlilik testi çalıştırılmadı.",
    ),
    (
        "Synthetic pollution series has no designed causal link to PI; "
        "daily HAC p>0.05 (demo only)."
    ): (
        "Synthetic pollution series has no designed causal link to PI; "
        "daily HAC p>0.05 (demo only).",
        "Sentetik kirlilik serisinin PI ile tasarlanmış nedensel bağı yok; "
        "günlük HAC p>0,05 (yalnızca demo).",
    ),
}


def site_label(site_key: str, default: str):
    """Return a function that maps site_key to localized display name."""

    labels: dict[str, tuple[str, str]] = {
        DEMO_PLANT_KEY: ("Demo Plant (synthetic)", "Demo Santral (sentetik)"),
        SAMPLE_UPLOAD_KEY: ("Sample CSV (built-in)", "Örnek CSV (gömülü)"),
        DEFAULT_SITE: ("Canakkale Hybrid GES (local)", "Çanakkale Hibrit GES (yerel)"),
        ALICE_SPRINGS_SITE_KEY: (
            "Alice Springs / DKASC (local)",
            "Alice Springs / DKASC (yerel)",
        ),
        "upload": ("Uploaded data", "Yüklenen veri"),
    }

    def _label(lang: str) -> str:
        en, tr = labels.get(site_key, (default, default))
        return tr if lang == "TR" else en

    return _label


def format_headline_rate(rate_pct_per_day: float | None, *, na: str) -> str:
    """Format pooled soiling rate for KPI cards (2 decimals, sign preserved)."""
    if rate_pct_per_day is None:
        return na
    return f"{rate_pct_per_day:.2f} %/day"


def format_headline_ci(lower: float | None, upper: float | None, *, na: str) -> str:
    """Format confidence interval for KPI cards."""
    if lower is None or upper is None:
        return na
    return f"{lower:.2f} .. {upper:.2f}"


def format_t_star_days(days: float, *, unit: str) -> str:
    """Format optimal wash interval for display."""
    return f"{days:.0f} {unit}"


def translate_backend_message(message: str, lang: str) -> str:
    """Map a known backend English status string to the active UI language."""
    return translate_backend_message_with_catalog(message, lang, catalog=BACKEND_MESSAGES)


def translate_backend_message_with_catalog(
    message: str, lang: str, *, catalog: dict[str, tuple[str, str]]
) -> str:
    if message in catalog:
        en, tr = catalog[message]
        return tr if lang == "TR" else en
    validated = re.fullmatch(r"Validated (\d+) daily rows\.", message)
    if validated:
        template = catalog["validated_rows"]
        en, tr = template
        text = tr if lang == "TR" else en
        return text.format(count=validated.group(1))
    missing_cols = re.fullmatch(
        r"Missing required columns: (.+)\. Expected columns: date, production, irradiation\.",
        message,
    )
    if missing_cols:
        template = catalog["missing_columns"]
        en, tr = template
        text = tr if lang == "TR" else en
        return text.format(columns=missing_cols.group(1))
    only_rows = re.fullmatch(
        r"Only (\d+) rows after parsing; provide at least 30 daily rows\.",
        message,
    )
    if only_rows:
        template = catalog["too_few_rows"]
        en, tr = template
        text = tr if lang == "TR" else en
        return text.format(count=only_rows.group(1))
    return message


def snapshot_status_line(snapshot: DashboardSnapshot, lang: str) -> str:
    """Localized site name and status message for dashboard banners."""
    name = site_label(snapshot.site_key, snapshot.site_name)(lang)
    message = translate_backend_message(snapshot.message, lang)
    return f"{name} — {message}"


def translate_pollution_verdict(verdict: str, lang: str) -> str:
    """Localize known pollution-test verdict strings."""
    if not verdict:
        return ""
    if verdict in BACKEND_MESSAGES:
        en, tr = BACKEND_MESSAGES[verdict]
        return tr if lang == "TR" else en
    return verdict
