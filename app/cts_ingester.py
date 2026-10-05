import csv
import hashlib
import shutil
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

# Database schema version for the new record/history model.
DATABASE_SCHEMA_VERSION = 2


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

        required = {
            "canonical_name",
            "alias"
        }

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
# DATABASE HELPERS
# ============================================================

def table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,)
    ).fetchone()

    return row is not None


def table_columns(conn, table_name):
    return {
        row[1]
        for row in conn.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()
    }


def get_database_schema_version(conn):
    return conn.execute(
        "PRAGMA user_version"
    ).fetchone()[0]


def set_database_schema_version(conn, version):
    conn.execute(
        f"PRAGMA user_version = {int(version)}"
    )


# ============================================================
# DATABASE SCHEMA
# ============================================================

def create_current_schema(conn):
    """
    Create the current database schema.

    records:
        Current top-10 state only.
        One row per (map_id, rank).

    record_history:
        Every state that became current.
        One row per (scrape_id, map_id, rank).
    """

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


        /*
         * CURRENT STATE
         *
         * Exactly one row for each map/rank.
         *
         * Example:
         *
         * map 41 / rank 1
         * map 41 / rank 2
         * ...
         * map 41 / rank 10
         */
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            map_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,

            time_text TEXT NOT NULL,
            time_seconds REAL,

            player_alias_id INTEGER NOT NULL,

            FOREIGN KEY (map_id)
                REFERENCES maps(id),

            FOREIGN KEY (player_alias_id)
                REFERENCES player_aliases(id),

            UNIQUE (
                map_id,
                rank
            )
        );


        /*
         * HISTORICAL RECORD STATES
         *
         * A row is created whenever the record occupying
         * a particular map/rank changes.
         *
         * The first scrape establishes the initial state.
         *
         * Example:
         *
         * scrape 10 / map 41 / rank 1 / Alice / 10.27
         * scrape 15 / map 41 / rank 1 / Alice / 10.10
         * scrape 20 / map 41 / rank 1 / Bob   /  9.95
         */
        CREATE TABLE IF NOT EXISTS record_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            scrape_id INTEGER NOT NULL,
            map_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,

            player_alias_id INTEGER NOT NULL,

            time_text TEXT NOT NULL,
            time_seconds REAL,

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


        CREATE INDEX IF NOT EXISTS idx_records_map
            ON records(map_id);


        CREATE INDEX IF NOT EXISTS idx_records_player_alias
            ON records(player_alias_id);


        CREATE INDEX IF NOT EXISTS idx_records_map_rank
            ON records(map_id, rank);


        CREATE INDEX IF NOT EXISTS idx_history_scrape
            ON record_history(scrape_id);


        CREATE INDEX IF NOT EXISTS idx_history_map
            ON record_history(map_id);


        CREATE INDEX IF NOT EXISTS idx_history_map_rank
            ON record_history(map_id, rank);


        CREATE INDEX IF NOT EXISTS idx_history_player_alias
            ON record_history(player_alias_id);


        CREATE INDEX IF NOT EXISTS idx_scrapes_date
            ON scrapes(scraped_at);
    """)


# ============================================================
# DATABASE MIGRATION
# ============================================================

def backup_database():
    """
    Create a physical backup before migrating the old database.

    Example:
        cts.db
        cts_pre_migration_2026-10-05_18-30-00.db
    """

    if not DATABASE_FILE.exists():
        return None

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    backup_file = (
        BASE_DIR
        / f"cts_pre_migration_{timestamp}.db"
    )

    shutil.copy2(
        DATABASE_FILE,
        backup_file
    )

    print()
    print(
        f"Database backup created:"
    )
    print(
        f"  {backup_file}"
    )

    return backup_file


def records_are_legacy(conn):
    """
    The old records table has scrape_id.

    The new records table deliberately does not.
    """

    if not table_exists(conn, "records"):
        return False

    columns = table_columns(
        conn,
        "records"
    )

    return "scrape_id" in columns


def record_value_changed(previous, current):
    """
    Determine whether a record changed.

    Player alias changes count as a change.

    Time changes count as a change.

    time_seconds is preferred for time comparison because:

        0:10.2
        0:10.20

    represent the same time.

    The text is used as a fallback if seconds are NULL.
    """

    if previous is None:
        return True

    (
        previous_player,
        previous_time_text,
        previous_time_seconds
    ) = previous

    (
        current_player,
        current_time_text,
        current_time_seconds
    ) = current

    if previous_player != current_player:
        return True

    if (
        previous_time_seconds is not None
        and current_time_seconds is not None
    ):
        return (
            previous_time_seconds
            != current_time_seconds
        )

    return (
        previous_time_text
        != current_time_text
    )


def migrate_legacy_database(conn):
    """
    Migrate the old schema to the new model.

    OLD:

        records
            scrape_id
            map_id
            rank
            player_alias_id
            time_text
            time_seconds

        top1_changes

    NEW:

        records
            map_id
            rank
            player_alias_id
            time_text
            time_seconds

        record_history
            scrape_id
            map_id
            rank
            player_alias_id
            time_text
            time_seconds

    The old records table contains complete snapshots for every
    scrape, so it is sufficient to reconstruct the complete
    history without relying on top1_changes.
    """

    print()
    print("=" * 60)
    print("DATABASE MIGRATION")
    print("=" * 60)

    legacy_count = conn.execute(
        "SELECT COUNT(*) FROM records"
    ).fetchone()[0]

    scrape_count = conn.execute(
        "SELECT COUNT(*) FROM scrapes"
    ).fetchone()[0]

    print(
        f"Legacy records: {legacy_count:,}"
    )

    print(
        f"Scrapes:        {scrape_count:,}"
    )

    print()
    print(
        "Reconstructing historical top-10 changes..."
    )

    # --------------------------------------------------------
    # Everything below is one transaction.
    #
    # If anything fails, the migration is rolled back.
    # --------------------------------------------------------

    conn.execute("BEGIN IMMEDIATE")

    try:

        # ----------------------------------------------------
        # Remove old record indexes.
        #
        # They will be recreated for the new schema.
        # ----------------------------------------------------

        conn.executescript("""
            DROP INDEX IF EXISTS idx_records_scrape;
            DROP INDEX IF EXISTS idx_records_map;
            DROP INDEX IF EXISTS idx_records_player_alias;
            DROP INDEX IF EXISTS idx_records_map_rank;
        """)

        # ----------------------------------------------------
        # Rename the old records table.
        # ----------------------------------------------------

        conn.execute(
            """
            ALTER TABLE records
            RENAME TO records_legacy
            """
        )

        # ----------------------------------------------------
        # Create the new tables/indexes.
        # ----------------------------------------------------

        create_current_schema(
            conn
        )

        # ----------------------------------------------------
        # Reconstruct history.
        #
        # We process the old snapshots in chronological
        # scrape order.
        #
        # current_state represents the previous scrape.
        #
        # The key is:
        #
        #     (map_id, rank)
        #
        # The value is:
        #
        #     (player_alias_id, time_text, time_seconds)
        # ----------------------------------------------------

        previous_state = {}
        current_state = {}

        previous_scrape_id = None

        history_count = 0

        legacy_cursor = conn.execute(
            """
            SELECT
                scrape_id,
                map_id,
                rank,
                player_alias_id,
                time_text,
                time_seconds
            FROM records_legacy
            ORDER BY
                scrape_id ASC,
                map_id ASC,
                rank ASC
            """
        )

        for row in legacy_cursor:

            (
                scrape_id,
                map_id,
                rank,
                player_alias_id,
                time_text,
                time_seconds
            ) = row

            # ------------------------------------------------
            # We have reached a new scrape.
            # The state accumulated for the previous scrape
            # becomes the comparison baseline.
            # ------------------------------------------------

            if (
                previous_scrape_id is not None
                and scrape_id != previous_scrape_id
            ):

                previous_state = (
                    current_state
                )

                current_state = {}

            # ------------------------------------------------
            # First row ever.
            # ------------------------------------------------

            if previous_scrape_id is None:

                previous_state = {}

                current_state = {}

            key = (
                map_id,
                rank
            )

            current = (
                player_alias_id,
                time_text,
                time_seconds
            )

            previous = previous_state.get(
                key
            )

            # ------------------------------------------------
            # This position is new or changed.
            # ------------------------------------------------

            if record_value_changed(
                previous,
                current
            ):

                conn.execute(
                    """
                    INSERT INTO record_history (
                        scrape_id,
                        map_id,
                        rank,
                        player_alias_id,
                        time_text,
                        time_seconds
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scrape_id,
                        map_id,
                        rank,
                        player_alias_id,
                        time_text,
                        time_seconds
                    )
                )

                history_count += 1

            current_state[key] = current

            previous_scrape_id = scrape_id

        # ----------------------------------------------------
        # If there was no data, current_state is empty.
        # Otherwise it contains the final scrape's state.
        # ----------------------------------------------------

        print(
            f"Created {history_count:,} history rows."
        )

        # ----------------------------------------------------
        # Populate the new current records table from the
        # final state.
        # ----------------------------------------------------

        current_record_count = 0

        for (
            map_id,
            rank
        ), (
            player_alias_id,
            time_text,
            time_seconds
        ) in current_state.items():

            conn.execute(
                """
                INSERT INTO records (
                    map_id,
                    rank,
                    player_alias_id,
                    time_text,
                    time_seconds
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    map_id,
                    rank,
                    player_alias_id,
                    time_text,
                    time_seconds
                )
            )

            current_record_count += 1

        print(
            f"Created {current_record_count:,} "
            "current records."
        )

        # ----------------------------------------------------
        # Verification
        # ----------------------------------------------------

        actual_history_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM record_history
            """
        ).fetchone()[0]

        if actual_history_count != history_count:
            raise RuntimeError(
                "History row count verification failed."
            )

        actual_current_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM records
            """
        ).fetchone()[0]

        if actual_current_count != current_record_count:
            raise RuntimeError(
                "Current record count verification failed."
            )

        # ----------------------------------------------------
        # Verify there are no duplicate current positions.
        # ----------------------------------------------------

        duplicate_positions = conn.execute(
            """
            SELECT
                map_id,
                rank,
                COUNT(*)
            FROM records
            GROUP BY
                map_id,
                rank
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()

        if duplicate_positions is not None:
            raise RuntimeError(
                "Duplicate (map_id, rank) found "
                "in new records table: "
                f"{duplicate_positions}"
            )

        # ----------------------------------------------------
        # Verify foreign keys.
        # ----------------------------------------------------

        foreign_key_errors = conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if foreign_key_errors:
            raise RuntimeError(
                "Foreign key verification failed: "
                f"{foreign_key_errors[:10]}"
            )

        # ----------------------------------------------------
        # The migration has successfully reconstructed the
        # new model.
        #
        # Remove the old snapshot table.
        # ----------------------------------------------------

        conn.execute(
            """
            DROP TABLE records_legacy
            """
        )

        # ----------------------------------------------------
        # top1_changes is now obsolete.
        #
        # We deliberately keep it instead of dropping it.
        #
        # This makes the migration non-destructive and gives
        # you the opportunity to verify the new history before
        # removing the old table manually.
        #
        # The new application never writes to it.
        # ----------------------------------------------------

        set_database_schema_version(
            conn,
            DATABASE_SCHEMA_VERSION
        )

        conn.commit()

    except Exception:

        conn.rollback()

        print()
        print(
            "DATABASE MIGRATION FAILED."
        )

        print(
            "The SQLite transaction was rolled back."
        )

        raise

    print()
    print(
        "Database migration completed successfully."
    )

    print(
        f"Schema version: {DATABASE_SCHEMA_VERSION}"
    )

    print(
        f"Current records: {current_record_count:,}"
    )

    print(
        f"History records: {history_count:,}"
    )

    print()
    print(
        "The old top1_changes table was preserved."
    )

    print(
        "It is no longer used by this application."
    )


def ensure_database_schema(conn):
    """
    Detect whether this is:

    1. A brand-new database.
    2. The old database schema.
    3. The new database schema.
    """

    if not table_exists(
        conn,
        "records"
    ):

        print(
            "No existing database schema found."
        )

        print(
            "Creating new database..."
        )

        create_current_schema(
            conn
        )

        set_database_schema_version(
            conn,
            DATABASE_SCHEMA_VERSION
        )

        conn.commit()

        print(
            "New database schema created."
        )

        return

    # --------------------------------------------------------
    # Existing old database.
    # --------------------------------------------------------

    if records_are_legacy(conn):

        print(
            "Legacy records schema detected."
        )

        backup_database()

        migrate_legacy_database(
            conn
        )

        return

    # --------------------------------------------------------
    # Existing new database.
    # --------------------------------------------------------

    print(
        "Current database schema detected."
    )

    create_current_schema(
        conn
    )

    set_database_schema_version(
        conn,
        DATABASE_SCHEMA_VERSION
    )

    conn.commit()


# ============================================================
# HASH CHECK
# ============================================================

def hash_already_exists(
    conn,
    content_hash
):

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

    text = "".join(
        element.itertext()
    )

    text = unquote(text)

    return text.strip()


# ============================================================
# TIME
# ============================================================

def time_to_seconds(time_text):

    if not time_text:
        return None

    try:

        minutes, seconds = (
            time_text.split(
                ":",
                1
            )
        )

        return (
            int(minutes) * 60
            + float(seconds)
        )

    except (
        ValueError,
        AttributeError
    ):

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

    print(
        "Parsing HTML..."
    )

    with CSV_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as csv_file:

        writer = csv.writer(
            csv_file
        )

        writer.writerow(
            headers
        )

        context = etree.iterparse(
            str(HTML_FILE),
            events=("end",),
            tag="tr",
            html=True,
            recover=True,
            huge_tree=True
        )

        for _, row in context:

            cells = row.xpath(
                "./th | ./td"
            )

            if not cells:

                row.clear()

                continue

            if cells[0].tag.lower() == "th":

                row.clear()

                continue

            map_name = clean_text(
                cells[0]
            )

            if not map_name:

                row.clear()

                continue

            output = (
                [map_name]
                + [""] * 20
            )

            for i, cell in enumerate(
                cells[1:21]
            ):

                output[i + 1] = (
                    clean_text(cell)
                )

            writer.writerow(
                output
            )

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

def get_map_id(
    conn,
    map_name
):

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
# RECORD COMPARISON
# ============================================================

def get_current_record(
    conn,
    map_id,
    rank
):
    return conn.execute(
        """
        SELECT
            player_alias_id,
            time_text,
            time_seconds
        FROM records
        WHERE map_id = ?
          AND rank = ?
        """,
        (
            map_id,
            rank
        )
    ).fetchone()


def save_record_change(
    conn,
    scrape_id,
    map_id,
    rank,
    player_alias_id,
    time_text,
    time_seconds
):
    """
    Save a newly established record to history and
    replace the current state.

    Both operations occur inside the caller's transaction.
    """

    conn.execute(
        """
        INSERT INTO record_history (
            scrape_id,
            map_id,
            rank,
            player_alias_id,
            time_text,
            time_seconds
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            scrape_id,
            map_id,
            rank,
            player_alias_id,
            time_text,
            time_seconds
        )
    )

    conn.execute(
        """
        INSERT INTO records (
            map_id,
            rank,
            player_alias_id,
            time_text,
            time_seconds
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(map_id, rank)
        DO UPDATE SET
            player_alias_id = excluded.player_alias_id,
            time_text = excluded.time_text,
            time_seconds = excluded.time_seconds
        """,
        (
            map_id,
            rank,
            player_alias_id,
            time_text,
            time_seconds
        )
    )


# ============================================================
# IMPORT
# ============================================================

def import_csv(
    conn,
    content_hash,
    manual_aliases
):

    timestamp = datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )

    # --------------------------------------------------------
    # Everything related to this scrape is transactional.
    #
    # If anything fails, the scrape itself, its history and
    # current-record changes are rolled back together.
    # --------------------------------------------------------

    conn.execute(
        "BEGIN IMMEDIATE"
    )

    try:

        # ----------------------------------------------------
        # Create scrape
        # ----------------------------------------------------

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
        changes = 0

        # ----------------------------------------------------
        # Import CSV
        # ----------------------------------------------------

        with CSV_FILE.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as f:

            reader = csv.DictReader(
                f
            )

            for row in reader:

                map_name = (
                    row["Map"] or ""
                ).strip()

                if not map_name:
                    continue

                map_count += 1

                # --------------------------------------------
                # Map cache
                # --------------------------------------------

                if map_name not in map_cache:

                    map_cache[map_name] = (
                        get_map_id(
                            conn,
                            map_name
                        )
                    )

                map_id = (
                    map_cache[map_name]
                )

                # --------------------------------------------
                # Process top 10
                # --------------------------------------------

                for rank in range(
                    1,
                    11
                ):

                    time_text = (
                        row.get(
                            f"Time #{rank}",
                            ""
                        )
                        or ""
                    ).strip()

                    player_name = (
                        row.get(
                            f"Player #{rank}",
                            ""
                        )
                        or ""
                    ).strip()

                    # Empty position.
                    if (
                        not time_text
                        and not player_name
                    ):
                        continue

                    # Invalid/incomplete position.
                    if (
                        not time_text
                        or not player_name
                    ):
                        continue

                    # ----------------------------------------
                    # Alias cache
                    # ----------------------------------------

                    if (
                        player_name
                        not in alias_cache
                    ):

                        alias_cache[player_name] = (
                            get_player_alias_id(
                                conn,
                                player_name,
                                manual_aliases,
                                timestamp
                            )
                        )

                    alias_id = (
                        alias_cache[player_name]
                    )

                    time_seconds = (
                        time_to_seconds(
                            time_text
                        )
                    )

                    # ----------------------------------------
                    # Compare with current state.
                    # ----------------------------------------

                    previous = (
                        get_current_record(
                            conn,
                            map_id,
                            rank
                        )
                    )

                    current = (
                        alias_id,
                        time_text,
                        time_seconds
                    )

                    if record_value_changed(
                        previous,
                        current
                    ):

                        save_record_change(
                            conn,
                            scrape_id,
                            map_id,
                            rank,
                            alias_id,
                            time_text,
                            time_seconds
                        )

                        changes += 1

                    record_count += 1

        # ----------------------------------------------------
        # Commit the complete scrape.
        # ----------------------------------------------------

        conn.commit()

    except Exception:

        conn.rollback()

        print(
            "Import failed. "
            "The scrape transaction was rolled back."
        )

        raise

    print(
        f"Detected {changes:,} "
        "new/changed records."
    )

    print(
        f"Imported {map_count:,} maps "
        f"and {record_count:,} records."
    )

    archive_csv(
        timestamp,
        content_hash
    )


# ============================================================
# ARCHIVE CSV
# ============================================================

def archive_csv(
    timestamp,
    content_hash
):
    """
    Rename the imported CSV using the scrape timestamp
    and SHA-256 hash.

    Example:

        cts_records.csv

    becomes:

        2026-09-29_20-18-42_a1b2c3d4e5f6.csv
    """

    if not CSV_FILE.exists():
        return None

    dt = datetime.fromisoformat(
        timestamp
    )

    date_part = dt.strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    hash_part = content_hash[:16]

    archived_name = (
        f"{date_part}_{hash_part}.csv"
    )

    archived_file = (
        CSV_FOLDER / archived_name
    )

    counter = 1

    while archived_file.exists():

        archived_name = (
            f"{date_part}_{hash_part}_{counter}.csv"
        )

        archived_file = (
            CSV_FOLDER / archived_name
        )

        counter += 1

    CSV_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    CSV_FILE.rename(
        archived_file
    )

    print(
        f"Archived CSV: "
        f"{archived_file.name}"
    )

    return archived_file


# ============================================================
# MAIN
# ============================================================

def main():

    manual_aliases = load_aliases()

    conn = sqlite3.connect(
        DATABASE_FILE
    )

    try:

        # ----------------------------------------------------
        # Make sure the database is using the new model.
        #
        # This automatically performs the migration if the
        # existing database still uses the old records table.
        # ----------------------------------------------------

        ensure_database_schema(
            conn
        )

        # ----------------------------------------------------
        # Download current CTS data.
        # ----------------------------------------------------

        download_page()

        # ----------------------------------------------------
        # Calculate content hash.
        # ----------------------------------------------------

        print(
            "Calculating SHA-256..."
        )

        content_hash = (
            calculate_sha256(
                HTML_FILE
            )
        )

        print(
            f"SHA-256: {content_hash}"
        )

        # ----------------------------------------------------
        # Don't create a scrape if CTS has not changed.
        # ----------------------------------------------------

        existing = (
            hash_already_exists(
                conn,
                content_hash
            )
        )

        if existing:

            scrape_id, scraped_at = (
                existing
            )

            print()

            print(
                "No changes detected."
            )

            print(
                f"Identical to scrape "
                f"#{scrape_id}"
            )

            print(
                f"Previous scrape: "
                f"{scraped_at}"
            )

            print(
                "Skipping parsing and "
                "database import."
            )

            return

        # ----------------------------------------------------
        # New CTS content.
        # ----------------------------------------------------

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
