import csv
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
from lxml import etree


# ============================================================
# CONFIGURATION
# ============================================================

URL = "https://cts.rexuiz.com/"

BASE_DIR = Path(__file__).resolve().parent

HTML_FILE = BASE_DIR / "cts.html"
CSV_FOLDER = BASE_DIR / "csv"
CSV_FILE = BASE_DIR / "cts_records.csv"
DATABASE_FILE = BASE_DIR / "cts.db"
ALIAS_FILE = BASE_DIR / "player_aliases.csv"


# ============================================================
# HASH
# ============================================================

def calculate_sha256(filename):
    sha256 = hashlib.sha256()

    with filename.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest()


# ============================================================
# DOWNLOAD
# ============================================================

def download_page():
    print(f"Downloading {URL}...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        )
    }

    with requests.get(
        URL,
        headers=headers,
        stream=True,
        timeout=120
    ) as response:

        response.raise_for_status()

        with HTML_FILE.open("wb") as f:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    f.write(chunk)

    print(
        f"Downloaded {HTML_FILE.stat().st_size:,} bytes"
    )


# ============================================================
# ALIASES
# ============================================================

def load_aliases():
    aliases = {}

    if not ALIAS_FILE.exists():
        print(
            f"No {ALIAS_FILE} found. "
            "Player names will be treated independently."
        )
        return aliases

    with ALIAS_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        required = {"canonical_name", "alias"}

        if not required.issubset(
            reader.fieldnames or set()
        ):
            raise ValueError(
                f"{ALIAS_FILE} must contain "
                "canonical_name,alias"
            )

        for row in reader:
            canonical = (
                row["canonical_name"] or ""
            ).strip()

            alias = (
                row["alias"] or ""
            ).strip()

            if not canonical or not alias:
                continue

            if alias in aliases:
                if aliases[alias] != canonical:
                    raise ValueError(
                        f"Alias '{alias}' is assigned to "
                        f"both '{aliases[alias]}' and "
                        f"'{canonical}'."
                    )

            aliases[alias] = canonical

    print(
        f"Loaded {len(aliases):,} alias mappings."
    )

    return aliases


# ============================================================
# DATABASE
# ============================================================

def create_database(conn):

    conn.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS scrapes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scraped_at TEXT NOT NULL,
            source_url TEXT NOT NULL,
            content_hash TEXT NOT NULL UNIQUE
        );


        CREATE TABLE IF NOT EXISTS maps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );


        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL UNIQUE
        );


        CREATE TABLE IF NOT EXISTS player_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            name TEXT NOT NULL UNIQUE,
            first_seen TEXT,
            last_seen TEXT,

            FOREIGN KEY (player_id)
                REFERENCES players(id)
                ON DELETE CASCADE
        );


        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            scrape_id INTEGER NOT NULL,
            map_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,

            time_text TEXT,
            time_seconds REAL,

            player_alias_id INTEGER,

            FOREIGN KEY (scrape_id)
                REFERENCES scrapes(id)
                ON DELETE CASCADE,

            FOREIGN KEY (map_id)
                REFERENCES maps(id),

            FOREIGN KEY (player_alias_id)
                REFERENCES player_aliases(id),

            UNIQUE (
                scrape_id,
                map_id,
                rank
            )
        );


        /*
         * A row is created whenever the #1 record of a map
         * changes between two scrapes.
         */
        CREATE TABLE IF NOT EXISTS top1_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            scrape_id INTEGER NOT NULL,
            map_id INTEGER NOT NULL,

            player_alias_id INTEGER NOT NULL,

            time_text TEXT NOT NULL,
            time_seconds REAL,

            FOREIGN KEY (scrape_id)
                REFERENCES scrapes(id)
                ON DELETE CASCADE,

            FOREIGN KEY (map_id)
                REFERENCES maps(id),

            FOREIGN KEY (player_alias_id)
                REFERENCES player_aliases(id)
        );


        CREATE INDEX IF NOT EXISTS idx_records_scrape
            ON records(scrape_id);

        CREATE INDEX IF NOT EXISTS idx_records_map
            ON records(map_id);

        CREATE INDEX IF NOT EXISTS idx_records_player_alias
            ON records(player_alias_id);

        CREATE INDEX IF NOT EXISTS idx_records_map_rank
            ON records(map_id, rank);

        CREATE INDEX IF NOT EXISTS idx_scrapes_date
            ON scrapes(scraped_at);

        CREATE INDEX IF NOT EXISTS idx_top1_changes_scrape
            ON top1_changes(scrape_id);

        CREATE INDEX IF NOT EXISTS idx_top1_changes_map
            ON top1_changes(map_id);

        CREATE INDEX IF NOT EXISTS idx_top1_changes_date
            ON top1_changes(scrape_id);
    """)

    conn.commit()


# ============================================================
# HASH CHECK
# ============================================================

def hash_already_exists(conn, content_hash):

    return conn.execute(
        """
        SELECT id, scraped_at
        FROM scrapes
        WHERE content_hash = ?
        """,
        (content_hash,)
    ).fetchone()


# ============================================================
# HTML TEXT
# ============================================================

def clean_text(element):
    """
    lxml decodes HTML entities automatically.

    Examples:

        &#134;  -> †
        &#9728; -> ☀

    urllib.unquote handles:

        %23 -> #
        %20 -> space
    """

    text = "".join(element.itertext())

    text = unquote(text)

    return text.strip()


# ============================================================
# TIME
# ============================================================

def time_to_seconds(time_text):

    if not time_text:
        return None

    try:
        minutes, seconds = time_text.split(":", 1)

        return (
            int(minutes) * 60
            + float(seconds)
        )

    except (ValueError, AttributeError):
        return None


# ============================================================
# PARSE HTML -> CSV
# ============================================================

def parse_html_to_csv():

    headers = [
        "Map",
        "Time #1", "Player #1",
        "Time #2", "Player #2",
        "Time #3", "Player #3",
        "Time #4", "Player #4",
        "Time #5", "Player #5",
        "Time #6", "Player #6",
        "Time #7", "Player #7",
        "Time #8", "Player #8",
        "Time #9", "Player #9",
        "Time #10", "Player #10",
    ]

    row_count = 0

    print("Parsing HTML...")

    with CSV_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as csv_file:

        writer = csv.writer(csv_file)
        writer.writerow(headers)

        context = etree.iterparse(
            str(HTML_FILE),
            events=("end",),
            tag="tr",
            html=True,
            recover=True,
            huge_tree=True
        )

        for _, row in context:

            cells = row.xpath("./th | ./td")

            if not cells:
                row.clear()
                continue

            if cells[0].tag.lower() == "th":
                row.clear()
                continue

            map_name = clean_text(cells[0])

            if not map_name:
                row.clear()
                continue

            output = [map_name] + [""] * 20

            for i, cell in enumerate(cells[1:21]):
                output[i + 1] = clean_text(cell)

            writer.writerow(output)

            row_count += 1

            row.clear()

            while row.getprevious() is not None:
                del row.getparent()[0]

    print(
        f"Parsed {row_count:,} maps."
    )


# ============================================================
# MAP
# ============================================================

def get_map_id(conn, map_name):

    conn.execute(
        """
        INSERT INTO maps (name)
        VALUES (?)
        ON CONFLICT(name) DO NOTHING
        """,
        (map_name,)
    )

    return conn.execute(
        """
        SELECT id
        FROM maps
        WHERE name = ?
        """,
        (map_name,)
    ).fetchone()[0]


# ============================================================
# PLAYER
# ============================================================

def get_player_alias_id(
    conn,
    observed_name,
    manual_aliases,
    timestamp
):

    canonical_name = manual_aliases.get(
        observed_name,
        observed_name
    )

    conn.execute(
        """
        INSERT INTO players (
            canonical_name
        )
        VALUES (?)
        ON CONFLICT(canonical_name) DO NOTHING
        """,
        (canonical_name,)
    )

    player_id = conn.execute(
        """
        SELECT id
        FROM players
        WHERE canonical_name = ?
        """,
        (canonical_name,)
    ).fetchone()[0]

    conn.execute(
        """
        INSERT INTO player_aliases (
            player_id,
            name,
            first_seen,
            last_seen
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(name) DO UPDATE SET
            last_seen = excluded.last_seen
        """,
        (
            player_id,
            observed_name,
            timestamp,
            timestamp
        )
    )

    return conn.execute(
        """
        SELECT id
        FROM player_aliases
        WHERE name = ?
        """,
        (observed_name,)
    ).fetchone()[0]


# ============================================================
# IMPORT
# ============================================================

def archive_csv(timestamp, content_hash):
    """
    Rename the imported CSV using the scrape timestamp
    and SHA-256 hash.

    Example:

        cts_records.csv

    becomes:

        2026-09-29_20-18-42_a1b2c3d4.csv
    """

    if not CSV_FILE.exists():
        return None

    dt = datetime.fromisoformat(timestamp)

    date_part = dt.strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    # First 8 characters are enough to identify the file
    # while keeping the filename reasonably short.
    hash_part = content_hash[:16]

    archived_name = (
        f"{date_part}_{hash_part}.csv"
    )

    archived_file = (
        CSV_FOLDER / archived_name
    )

    # Extremely unlikely, but avoid overwriting
    # an existing archive.
    counter = 1

    while archived_file.exists():

        archived_name = (
            f"{date_part}_{hash_part}_{counter}.csv"
        )

        archived_file = (
            CSV_FOLDER / archived_name
        )

        counter += 1

    CSV_FILE.rename(
        archived_file
    )

    print(
        f"Archived CSV: {archived_file.name}"
    )

    return archived_file

def import_csv(
    conn,
    content_hash,
    manual_aliases
):

    timestamp = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    # --------------------------------------------------------
    # Identify previous scrape BEFORE inserting the new one.
    # --------------------------------------------------------

    previous_scrape = conn.execute(
        """
        SELECT id
        FROM scrapes
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    previous_scrape_id = (
        previous_scrape[0]
        if previous_scrape
        else None
    )

    # --------------------------------------------------------
    # Create scrape
    # --------------------------------------------------------

    cursor = conn.execute(
        """
        INSERT INTO scrapes (
            scraped_at,
            source_url,
            content_hash
        )
        VALUES (?, ?, ?)
        """,
        (
            timestamp,
            URL,
            content_hash
        )
    )

    scrape_id = cursor.lastrowid

    print(
        f"Created scrape #{scrape_id}"
    )

    map_cache = {}
    alias_cache = {}

    record_count = 0
    map_count = 0

    # --------------------------------------------------------
    # Import CSV
    # --------------------------------------------------------

    with CSV_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            map_name = (
                row["Map"] or ""
            ).strip()

            if not map_name:
                continue

            map_count += 1

            if map_name not in map_cache:
                map_cache[map_name] = get_map_id(
                    conn,
                    map_name
                )

            map_id = map_cache[map_name]

            for rank in range(1, 11):

                time_text = (
                    row.get(
                        f"Time #{rank}",
                        ""
                    ) or ""
                ).strip()

                player_name = (
                    row.get(
                        f"Player #{rank}",
                        ""
                    ) or ""
                ).strip()

                if not time_text and not player_name:
                    continue

                if not time_text or not player_name:
                    continue

                if player_name not in alias_cache:

                    alias_cache[player_name] = (
                        get_player_alias_id(
                            conn,
                            player_name,
                            manual_aliases,
                            timestamp
                        )
                    )

                alias_id = alias_cache[player_name]

                time_seconds = time_to_seconds(
                    time_text
                )

                conn.execute(
                    """
                    INSERT INTO records (
                        scrape_id,
                        map_id,
                        rank,
                        time_text,
                        time_seconds,
                        player_alias_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scrape_id,
                        map_id,
                        rank,
                        time_text,
                        time_seconds,
                        alias_id
                    )
                )

                record_count += 1

    # --------------------------------------------------------
    # Detect #1 changes
    # --------------------------------------------------------

    if previous_scrape_id is not None:

        current_top1 = conn.execute(
            """
            SELECT
                r.map_id,
                r.player_alias_id,
                r.time_text,
                r.time_seconds
            FROM records r
            WHERE r.scrape_id = ?
              AND r.rank = 1
            """,
            (scrape_id,)
        ).fetchall()

        previous_top1 = {
            row[0]: row[1:]
            for row in conn.execute(
                """
                SELECT
                    r.map_id,
                    r.player_alias_id,
                    r.time_text,
                    r.time_seconds
                FROM records r
                WHERE r.scrape_id = ?
                  AND r.rank = 1
                """,
                (previous_scrape_id,)
            ).fetchall()
        }

        changes = 0

        for (
            map_id,
            player_alias_id,
            time_text,
            time_seconds
        ) in current_top1:

            previous = previous_top1.get(map_id)

            current = (
                player_alias_id,
                time_text,
                time_seconds
            )

            if previous == current:
                continue

            conn.execute(
                """
                INSERT INTO top1_changes (
                    scrape_id,
                    map_id,
                    player_alias_id,
                    time_text,
                    time_seconds
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    scrape_id,
                    map_id,
                    player_alias_id,
                    time_text,
                    time_seconds
                )
            )

            changes += 1

        print(
            f"Detected {changes:,} #1 record changes."
        )

    else:

        current_top1 = conn.execute(
        """
        SELECT
            r.map_id,
            r.player_alias_id,
            r.time_text,
            r.time_seconds
        FROM records r
        WHERE r.scrape_id = ?
          AND r.rank = 1
        """,
        (scrape_id,)
        ).fetchall()

        for (
        map_id,
        player_alias_id,
        time_text,
        time_seconds
        ) in current_top1:

            conn.execute(
            """
            INSERT INTO top1_changes (
                scrape_id,
                map_id,
                player_alias_id,
                time_text,
                time_seconds
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                scrape_id,
                map_id,
                player_alias_id,
                time_text,
                time_seconds
            )
        )

    print(
        "First scrape: recorded initial #1 records."
    )


    conn.commit()

    print(
        f"Imported {map_count:,} maps "
        f"and {record_count:,} records."
    )

    archive_csv(
        timestamp,
        content_hash
    )


# ============================================================
# MAIN
# ============================================================

def main():

    manual_aliases = load_aliases()

    conn = sqlite3.connect(
        DATABASE_FILE
    )

    try:

        create_database(conn)

        download_page()

        print("Calculating SHA-256...")

        content_hash = calculate_sha256(
            HTML_FILE
        )

        print(
            f"SHA-256: {content_hash}"
        )

        existing = hash_already_exists(
            conn,
            content_hash
        )

        if existing:

            scrape_id, scraped_at = existing

            print()
            print(
                "No changes detected."
            )

            print(
                f"Identical to scrape #{scrape_id}"
            )

            print(
                f"Previous scrape: {scraped_at}"
            )

            print(
                "Skipping parsing and database import."
            )

            return

        print(
            "New content detected."
        )

        parse_html_to_csv()

        import_csv(
            conn,
            content_hash,
            manual_aliases
        )

        print()
        print(
            "Scrape completed successfully."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
