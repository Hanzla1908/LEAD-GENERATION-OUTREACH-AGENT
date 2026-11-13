"""Load the GeoNames city database into the app's database.

Run from the backend folder:

    python scripts/import_geonames.py --download     # fetch the files into data/geonames, then import
    python scripts/import_geonames.py                # import files already in data/geonames

The database is the one in DATABASE_URL (SQLite restaurant_outreach.db by default). Migrations are applied first.
Re-running replaces the GeoNames tables with the same data. Restaurants, leads and campaigns are not touched.

City data is © GeoNames (https://www.geonames.org/), licensed under CC BY 4.0. Keep the attribution with the data.
"""
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Same .env files as main.py, so the import writes to the database the app uses (DATABASE_URL).
from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=BACKEND_DIR / ".env")
load_dotenv(dotenv_path=BACKEND_DIR.parent / ".env")

from models.database import init_db  # noqa: E402
from services import geonames_import as gi  # noqa: E402

DEFAULT_DATA_DIR = BACKEND_DIR / "data" / "geonames"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Import GeoNames cities (CC BY 4.0).")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="folder holding cities15000.txt and admin1CodesASCII.txt")
    parser.add_argument("--download", action="store_true",
                        help=f"download the files from {gi.BASE_URL} before importing")
    args = parser.parse_args()

    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / gi.CITIES_ZIP
    cities_path = data_dir / gi.CITIES_TXT
    admin1_path = data_dir / gi.ADMIN1_TXT
    sha_source = None

    if args.download:
        print("Downloading GeoNames city and division files…")
        gi.download(gi.BASE_URL + gi.CITIES_ZIP, zip_path)
        gi.download(gi.BASE_URL + gi.ADMIN1_TXT, admin1_path)
        gi.download(gi.BASE_URL + gi.README_TXT, data_dir / gi.README_TXT)
        sha_source = gi.sha256_of(zip_path)
        gi.extract_cities(zip_path, data_dir)

    if not cities_path.exists() or not admin1_path.exists():
        print(f"Missing {gi.CITIES_TXT} or {gi.ADMIN1_TXT} in {data_dir}. Run with --download, or copy the files there.")
        return 1
    if sha_source is None:
        sha_source = gi.sha256_of(zip_path) if zip_path.exists() else None

    init_db()
    summary = gi.import_from_files(cities_path, admin1_path, file_sha256=sha_source)
    print(f"Imported {summary['cities']} cities and {summary['alternate_names']} alternate names "
          f"(skipped {summary['skipped']} rows for unknown countries).")
    print(summary["attribution"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
