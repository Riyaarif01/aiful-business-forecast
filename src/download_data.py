"""
download_data.py
----------------
Downloads AIFUL's official Monthly Data PDFs (FY2012-FY2026) into data/raw/.

Why a script instead of committing the PDFs? Muninova's Terms of Use allow copying
for personal use/reference with the source cited, but not general republication,
so the repo ships this script and anyone can fetch the originals from the source.

Run from the repo root:
    python src/download_data.py

If a download fails, open https://www.muninova.co.jp/en/ir/finance/monthly_data.html
in a browser, download the file manually and save it under the name shown below.
"""

from pathlib import Path
import time

import requests

BASE_URL = "https://www.muninova.co.jp/ir/pdf/"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"   # repo root/data/raw

# fiscal year -> file name on the IR site (FY2012 = Apr-2012 .. Mar-2013)
FILES = {
    2012: "pdf-2158-datafile.pdf",
    2013: "pdf-2331-datafile.pdf",
    2014: "pdf-2477-datafile.pdf",
    2015: "MD201603.pdf",
    2016: "MD201703.pdf",
    2017: "MD201803.pdf",
    2018: "MD201903.pdf",
    2019: "MD202003.pdf",
    2020: "MD202103_rep.pdf",   # "_rep" = corrected version published by AIFUL
    2021: "MD202203.pdf",
    2022: "MD202303.pdf",
    2023: "MD202403.pdf",
    2024: "MD202503.pdf",
    2025: "MD202603.pdf",
    2026: "MD202608.pdf",       # current year, Apr-Aug 2026. Update the name as new months are published.
}


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (portfolio project; data from public IR page)"

    for fy, name in FILES.items():
        target = RAW_DIR / f"aiful_monthly_FY{fy}.pdf"
        if target.exists():
            print(f"FY{fy}: already downloaded")
            continue
        response = session.get(BASE_URL + name, timeout=30)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"FY{fy}: server did not return a PDF - download it manually")
        target.write_bytes(response.content)
        print(f"FY{fy}: saved {target} ({len(response.content):,} bytes)")
        time.sleep(1)  # be polite to the server


if __name__ == "__main__":
    main()
