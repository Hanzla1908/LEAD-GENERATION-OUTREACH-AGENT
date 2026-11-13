# GeoNames city data

The city list used by the City field in business discovery comes from **GeoNames**.

- Source: https://www.geonames.org/ (downloads: https://download.geonames.org/export/dump/)
- Files used: `cities15000.zip` (every populated place with at least 15,000 people, plus seats of admin divisions) and `admin1CodesASCII.txt` (names of first-level divisions such as Punjab or New South Wales).
- Licence: Creative Commons Attribution 4.0 (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/
- Attribution (keep it wherever the data is shown): **City data © GeoNames (https://www.geonames.org/), licensed under CC BY 4.0.** The discovery form shows this line once the data is loaded.

The downloaded files are not committed (see `.gitignore`). Only this README is tracked.

## Set up

Run from the `backend` folder, with the backend virtual environment active (or use `.venv\Scripts\python.exe` on Windows):

```bash
python scripts/import_geonames.py --download
```

This downloads the files into this folder, applies database migrations, and loads the city tables. It takes about 15 seconds and about 40 MB of database space. Running it again replaces the GeoNames data with the same rows. Restaurants, leads and campaigns are not touched.

If the files are already here, run without `--download`:

```bash
python scripts/import_geonames.py
```

## What is stored

| Table | Contents |
| --- | --- |
| `geo_cities` | GeoNames id, country code (ISO alpha-2), name, ASCII name, admin division code and name, population, coordinates, feature code |
| `geo_city_alternate_names` | Latin-script alternate names, e.g. `Lyallpur` for Faisalabad, `NYC` for New York City |
| `geo_import_runs` | Each import: file checksum, counts, licence and time |

These tables hold open GeoNames data only. They do not reference restaurants, leads or Google Places records.

## Limits

- Only places with a population of 15,000 or more, plus seats of admin divisions, are included. Smaller towns are not in the list. Typing them still works: a typed city is searched exactly as typed.
- Alternate names come from the `cities15000` file. Non-Latin alternate names are skipped.
- Before the import has run, Pakistan still offers its built-in city list. Other countries show no suggestions until the import has run.
