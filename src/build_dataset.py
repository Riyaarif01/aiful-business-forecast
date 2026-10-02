"""
build_dataset.py
----------------
Turns AIFUL's 15 "Monthly Data" PDFs (FY2012-FY2026) into ONE clean monthly table.

Run from the repo root:
    python src/build_dataset.py

Output:
    data/processed/aiful_monthly.csv   (one row per month, one column per metric)

Source: Muninova Holdings (former AIFUL Group) IR site, "Monthly Data"
        https://www.muninova.co.jp/en/ir/finance/monthly_data.html
"""

from pathlib import Path
import re

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]          # repo root, wherever you run from
RAW_DIR = ROOT / "data" / "raw"
OUT_FILE = ROOT / "data" / "processed" / "aiful_monthly.csv"

# ---------------------------------------------------------------------------
# 1. Dictionary: Japanese row label  ->  our English column name
#    The PDFs changed wording in FY2024 (e.g. 無担保ローン -> 個人向け無担保),
#    so several Japanese labels map to the same column.
#    The same label (e.g. 無担保ローン) appears twice: once in ¥ million
#    (loan balance) and once in '000 (number of accounts). So the key is
#    (label, unit), not just the label.
# ---------------------------------------------------------------------------
LABEL_MAP = {
    # --- balances, ¥ million ---
    ("営業債権合計", "¥mil"): "total_receivables_jpy_mn",
    ("営業貸付金残高", "¥mil"): "loans_outstanding_jpy_mn",
    ("ローン事業（営業貸付金残高）", "¥mil"): "loans_outstanding_jpy_mn",
    ("無担保ローン", "¥mil"): "unsecured_loans_jpy_mn",
    ("個人向け無担保", "¥mil"): "unsecured_loans_jpy_mn",
    ("有担保ローン", "¥mil"): "secured_loans_jpy_mn",
    ("有担保", "¥mil"): "secured_loans_jpy_mn",
    ("事業者ローン", "¥mil"): "small_business_loans_jpy_mn",
    ("事業者向け無担保", "¥mil"): "small_business_loans_jpy_mn",
    ("支払承諾見返等", "¥mil"): "guarantee_balance_jpy_mn",
    ("信用保証事業等（支払承諾見返等）", "¥mil"): "guarantee_balance_jpy_mn",
    # --- customer accounts with a balance, thousands ---
    ("口座数（残高あり）", "'000"): "customer_accounts_k",
    ("無担保ローン", "'000"): "unsecured_accounts_k",
    ("個人向け無担保", "'000"): "unsecured_accounts_k",
    # --- new-customer funnel (unsecured personal loans) ---
    ("申込件数", "num"): "applications",
    ("新規獲得件数", "num"): "new_accounts",
    ("無担保新規成約率", "％"): "contract_rate_pct",
    ("新規成約率", "％"): "contract_rate_pct",
    # --- credit quality / legacy issues ---
    ("無担保解約発生率", "％"): "delinquent_loan_ratio_pct",
    ("利息返還請求件数", "num"): "interest_refund_claims",
}

# A data line looks like:  <Japanese label> [*1] <unit> <numbers...>
LINE_RE = re.compile(r"^(?P<label>\S+?)\s*(?:\*\d\s*)?\s(?P<unit>¥mil|'000|num|％)\s+(?P<vals>.+)$")


def to_number(token: str):
    """'1,055,073' -> 1055073.0 ; '-' or '#DIV/0!' -> None"""
    token = token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return None


def keep_12_months(values: list) -> list:
    """
    Older PDFs (FY2012-FY2024) have 15 columns:
        Apr..Sep, [H1 total], Oct..Mar, [H2 total], [Full-year total]
    Newer PDFs (FY2025+) have 12 month columns (+1 cumulative total for flows).
    We keep only the 12 monthly values.
    """
    if len(values) == 15:
        return values[0:6] + values[7:13]      # drop H1 (idx 6), H2 (13), FY (14)
    if len(values) in (12, 13):
        return values[0:12]                     # drop the trailing cumulative total
    return None                                  # unexpected shape -> refuse to guess


def parse_one_pdf(path: Path) -> pd.DataFrame:
    """Read one fiscal-year PDF and return a 12-row DataFrame (Apr..Mar)."""
    fiscal_year = int(re.search(r"FY(\d{4})", path.name).group(1))   # FY2012 = Apr-2012..Mar-2013
    months = pd.date_range(f"{fiscal_year}-04-01", periods=12, freq="MS")

    with pdfplumber.open(path) as pdf:
        lines = pdf.pages[0].extract_text().split("\n")

    # In FY2025+ the delinquency label sits on its own line and the numbers on the
    # next line ("％ 0.574 0.759 ..."). Glue such pairs back into one line.
    glued = []
    for line in lines:
        if glued and line.startswith("％ ") and re.fullmatch(r"\S+\s*\*\d", glued[-1].strip()):
            glued[-1] = glued[-1].strip() + " " + line
        else:
            glued.append(line)

    data = {}
    for line in glued:
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        key = (m.group("label"), m.group("unit"))
        col = LABEL_MAP.get(key)
        if col is None or col in data:          # unknown row, or already captured
            continue
        values = keep_12_months([to_number(v) for v in m.group("vals").split()])
        if values is None:
            print(f"  ! {path.name}: '{key[0]}' has an unexpected number of values - skipped")
            continue
        data[col] = values

    df = pd.DataFrame(data, index=months)
    df["source_file"] = path.name
    return df


def build() -> pd.DataFrame:
    files = sorted(RAW_DIR.glob("aiful_monthly_FY*.pdf"))
    print(f"Found {len(files)} PDF files")
    df = pd.concat([parse_one_pdf(f) for f in files])
    df.index.name = "month"

    # Future months in the current-year file are filled with 0 -> drop them.
    df = df[df["total_receivables_jpy_mn"].fillna(0) > 0]

    # Delinquency ratio of exactly 0.000 for an unpublished month = missing.
    df.loc[df["delinquent_loan_ratio_pct"] == 0, "delinquent_loan_ratio_pct"] = None

    # Integer columns where it makes sense (counts & ¥ million)
    count_cols = [c for c in df.columns if c.endswith(("_jpy_mn", "_k")) or c in ("applications", "new_accounts", "interest_refund_claims")]
    df[count_cols] = df[count_cols].astype("Int64")

    # Keep the audit-trail column (which PDF each row came from) at the far right
    df = df[[c for c in df.columns if c != "source_file"] + ["source_file"]]
    df = df.sort_index()
    return df


def validate(df: pd.DataFrame) -> None:
    """Sanity checks. If any fails, the script stops - better than silently wrong data."""
    # 1. One row per month, no gaps
    expected = pd.date_range(df.index.min(), df.index.max(), freq="MS")
    assert df.index.is_unique, "duplicate months"
    assert len(df) == len(expected), "missing months in the series"

    # 2. Contract rate should equal new accounts / applications
    implied = df["new_accounts"] / df["applications"] * 100
    gap = (implied - df["contract_rate_pct"]).abs()
    assert gap.max() < 0.2, f"contract rate mismatch, max gap {gap.max():.2f}pp"

    # 3. Loan balance should equal unsecured + secured + small business (rounding = a few ¥mn)
    parts = df[["unsecured_loans_jpy_mn", "secured_loans_jpy_mn", "small_business_loans_jpy_mn"]].sum(axis=1)
    diff = (df["loans_outstanding_jpy_mn"] - parts).abs()
    assert diff.max() <= 5, f"loan components don't add up, max diff ¥{diff.max()}mn"

    # 4. Known value check straight from the latest PDF (Aug-2026)
    assert df.loc["2026-08-01", "unsecured_loans_jpy_mn"] == 663_982

    # 5. Strongest check: AIFUL prints its own YoY % in each PDF. If our columns were
    #    shifted by even one month, our computed YoY would not match theirs.
    published = published_yoy("Loans Outstanding yoy")
    ours = df["loans_outstanding_jpy_mn"].astype(float).pct_change(12) * 100
    gap = (ours - published.reindex(df.index)).abs().dropna()
    assert gap.max() < 0.1, f"YoY mismatch vs AIFUL's published figures, max gap {gap.max():.2f}pp"
    print(f"YoY check: {len(gap)} months match AIFUL's published YoY (max gap {gap.max():.2f}pp)")

    print(f"All checks passed: {len(df)} months, {df.index.min():%b-%Y} to {df.index.max():%b-%Y}")


def published_yoy(english_label: str) -> pd.Series:
    """Read AIFUL's own printed YoY % row (e.g. 'Loans Outstanding yoy ％ 9.5 8.8 ...')."""
    out = {}
    for path in sorted(RAW_DIR.glob("aiful_monthly_FY*.pdf")):
        fiscal_year = int(re.search(r"FY(\d{4})", path.name).group(1))
        with pdfplumber.open(path) as pdf:
            lines = pdf.pages[0].extract_text().split("\n")
        for line in lines:
            if line.startswith(english_label):
                tokens = [t for t in line.split() if re.match(r"^-?[\d,.]+$|^-$|^#", t)]
                values = keep_12_months([to_number(t) for t in tokens])
                months = pd.date_range(f"{fiscal_year}-04-01", periods=12, freq="MS")
                out.update(dict(zip(months, values)))
                break
    return pd.Series(out)


if __name__ == "__main__":
    monthly = build()
    validate(monthly)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(OUT_FILE)
    print(f"Saved -> {OUT_FILE}")
