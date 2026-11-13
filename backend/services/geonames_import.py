"""Load GeoNames city data into geo_cities and geo_city_alternate_names.

Input files (see backend/data/geonames/README.md):
- cities15000.txt     every populated place with population of at least 15,000, plus seats of admin divisions
- admin1CodesASCII.txt names of first-level divisions, keyed "CC.code" (e.g. "PK.04" is Punjab)

The import is idempotent. Each run replaces the whole geo_* dataset in one transaction, so re-running with the same
files gives the same rows, and a failed run leaves the previous data in place.
"""
import hashlib
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from models.database import get_engine
from services import countries
from services.geonames import ATTRIBUTION, LICENCE, SOURCE, SOURCE_URL, clear_cache, normalize_search

BASE_URL = "https://download.geonames.org/export/dump/"
CITIES_ZIP = "cities15000.zip"
CITIES_TXT = "cities15000.txt"
ADMIN1_TXT = "admin1CodesASCII.txt"
README_TXT = "readme.txt"
USER_AGENT = "LeadGenerationAgent-GeoImport/1.0"
BATCH_SIZE = 5000

# Alternate names are kept only when they are Latin letters, spaces and common punctuation, 2 to 60 characters.
# This keeps search useful in English and in the Latin spellings used in other countries, and skips non-Latin scripts.
_LATIN_NAME = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ .'’\-]{1,59}")

_INSERT_CITY = text(
    "INSERT INTO geo_cities (id, country_code, name, ascii_name, search_name, admin1_code, admin1_name, "
    "population, latitude, longitude, feature_code) VALUES (:id, :cc, :name, :ascii, :search, :a1code, :a1name, "
    ":population, :lat, :lon, :feature)"
)
_INSERT_ALT = text(
    "INSERT INTO geo_city_alternate_names (city_id, country_code, alt_name, search_name) "
    "VALUES (:city_id, :cc, :alt, :search)"
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> Path:
    """Fetch one file. It is written to a temporary name first, so a failed download never leaves a partial file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    partial.replace(destination)
    return destination


def extract_cities(zip_path: Path, destination_dir: Path) -> Path:
    """Unpack cities15000.txt from the zip. Only that one fixed member name is read."""
    with zipfile.ZipFile(zip_path) as archive:
        archive.extract(CITIES_TXT, destination_dir)
    return destination_dir / CITIES_TXT


def read_admin1_names(path: Path) -> dict[str, str]:
    """{"PK.04": "Punjab", ...}. Columns: code, name, ascii name, geonameid."""
    names = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            names[parts[0]] = parts[1]
    return names


def _alt_names(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_cities(path: Path, admin1_names: dict[str, str]):
    """Yield (city_row, alternate_name_list, skipped) for each line. skipped counts rows with an unknown country."""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 15:
                yield None, [], True
                continue
            geonameid, name, ascii_name, alternates = parts[0], parts[1].strip(), parts[2].strip(), parts[3]
            country_code = parts[8].strip().upper()
            if not name or not countries.is_known_country(country_code):
                yield None, [], True
                continue
            admin1_code = parts[10].strip() or None
            admin1_name = admin1_names.get(f"{country_code}.{admin1_code}") if admin1_code else None
            population = int(parts[14]) if parts[14].strip().isdigit() else 0
            latitude = float(parts[4]) if parts[4] else None
            longitude = float(parts[5]) if parts[5] else None
            row = {
                "id": int(geonameid), "cc": country_code, "name": name, "ascii": ascii_name or None,
                "search": normalize_search(name), "a1code": admin1_code, "a1name": admin1_name,
                "population": population, "lat": latitude, "lon": longitude, "feature": parts[7] or None,
            }
            yield row, _alt_names(alternates), False


def _latin_alternates(row: dict, names: list[str]) -> list[dict]:
    """Latin alternate names for one city, without duplicates and without the main name."""
    seen = {row["search"]}
    kept = []
    candidates = list(names)
    if row["ascii"]:
        candidates.append(row["ascii"])
    for name in candidates:
        if not _LATIN_NAME.fullmatch(name) or "  " in name:
            continue
        key = normalize_search(name)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append({"cc": row["cc"], "alt": name, "search": key})
    return kept


def import_from_files(cities_path: Path, admin1_path: Path, source_url: str = SOURCE_URL,
                      file_sha256: str | None = None) -> dict:
    """Replace all geo_* rows with the contents of the two files. Returns the counts that were written."""
    admin1_names = read_admin1_names(admin1_path)
    file_sha = file_sha256 or sha256_of(cities_path)

    city_count = alt_count = skipped = 0
    city_batch: list[dict] = []
    alt_batch: list[dict] = []
    engine = get_engine()
    with engine.begin() as conn:
        # Alternate names reference cities, so they are removed first.
        conn.execute(text("DELETE FROM geo_city_alternate_names"))
        conn.execute(text("DELETE FROM geo_cities"))

        def flush():
            nonlocal city_batch, alt_batch
            if city_batch:
                conn.execute(_INSERT_CITY, city_batch)
                city_batch = []
            if alt_batch:
                conn.execute(_INSERT_ALT, alt_batch)
                alt_batch = []

        for row, names, is_skipped in parse_cities(cities_path, admin1_names):
            if is_skipped:
                skipped += 1
                continue
            city_batch.append(row)
            city_count += 1
            alternates = _latin_alternates(row, names)
            for alt in alternates:
                alt_batch.append({"city_id": row["id"], **alt})
            alt_count += len(alternates)
            if len(city_batch) >= BATCH_SIZE or len(alt_batch) >= BATCH_SIZE * 10:
                flush()
        flush()

        conn.execute(
            text("INSERT INTO geo_import_runs (source, source_url, file_sha256, city_count, alternate_name_count, "
                 "skipped_count, licence, imported_at) VALUES (:source, :url, :sha, :cities, :alts, :skipped, "
                 ":licence, :at)"),
            {"source": SOURCE, "url": source_url, "sha": file_sha, "cities": city_count, "alts": alt_count,
             "skipped": skipped, "licence": LICENCE, "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")},
        )
    clear_cache()
    return {"cities": city_count, "alternate_names": alt_count, "skipped": skipped, "attribution": ATTRIBUTION}
