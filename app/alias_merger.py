import argparse
import csv
import sqlite3
import sys
from pathlib import Path


DATABASE_FILE = Path("cts.db")


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_player(conn, player_id):
    return conn.execute(
        """
        SELECT id, canonical_name
        FROM players
        WHERE id = ?
        """,
        (player_id,)
    ).fetchone()


def get_alias(conn, alias_name):
    return conn.execute(
        """
        SELECT
            pa.id,
            pa.player_id,
            p.canonical_name
        FROM player_aliases pa
        JOIN players p
            ON p.id = pa.player_id
        WHERE pa.name = ?
        """,
        (alias_name,)
    ).fetchone()


def show_player(conn, player_id):
    """Display a player and all of their aliases."""

    player = get_player(conn, player_id)

    if not player:
        print(f"Player ID {player_id} does not exist.")
        return False

    print()
    print(f"Player #{player[0]}: {player[1]}")
    print("Aliases:")

    aliases = conn.execute(
        """
        SELECT id, name
        FROM player_aliases
        WHERE player_id = ?
        ORDER BY name
        """,
        (player_id,)
    ).fetchall()

    for alias_id, name in aliases:
        print(f"  [{alias_id}] {name}")

    print()

    return True


# ============================================================
# MERGE
# ============================================================

def merge_alias(
    conn,
    alias_name,
    target_player_id,
    confirm=False
):
    """
    Move an alias to an existing player.

    Returns:
        True  = merge performed
        False = merge skipped/failed
    """

    alias = get_alias(
        conn,
        alias_name
    )

    if not alias:

        print(
            f"SKIP: Alias '{alias_name}' does not exist."
        )

        return False

    alias_id, old_player_id, old_player_name = alias

    target = get_player(
        conn,
        target_player_id
    )

    if not target:

        print(
            f"SKIP: Target player #{target_player_id} "
            f"does not exist."
        )

        return False

    target_id, target_name = target

    # Already merged.
    if old_player_id == target_id:

        print(
            f"SKIP: '{alias_name}' already belongs to "
            f"Player #{target_id} ({target_name})."
        )

        return False

    print(
        f"  {alias_name}: "
        f"{old_player_name} -> {target_name}"
    )

    if confirm:

        answer = input(
            "  Continue? [y/N]: "
        ).strip().lower()

        if answer != "y":

            print("  Cancelled.")

            return False

    # --------------------------------------------------------
    # Move alias
    # --------------------------------------------------------

    conn.execute(
        """
        UPDATE player_aliases
        SET player_id = ?
        WHERE id = ?
        """,
        (
            target_id,
            alias_id
        )
    )

    # --------------------------------------------------------
    # Remove old player if there are no aliases left.
    # --------------------------------------------------------

    remaining = conn.execute(
        """
        SELECT COUNT(*)
        FROM player_aliases
        WHERE player_id = ?
        """,
        (old_player_id,)
    ).fetchone()[0]

    if remaining == 0:

        conn.execute(
            """
            DELETE FROM players
            WHERE id = ?
            """,
            (old_player_id,)
        )

        print(
            f"  Removed empty player "
            f"#{old_player_id} ({old_player_name})"
        )

    return True


# ============================================================
# BULK CSV
# ============================================================

def load_merge_file(filename):
    """
    Read:

        alias,player_id

    Example:

        0Kablaaa,1
        Kablaaa_2,1
        OldSaiel,2
    """

    merges = []

    with open(
        filename,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        required = {
            "alias",
            "player_id"
        }

        if not required.issubset(
            reader.fieldnames or set()
        ):

            raise ValueError(
                f"{filename} must contain "
                "columns: alias,player_id"
            )

        for line_number, row in enumerate(
            reader,
            start=2
        ):

            alias = (
                row["alias"] or ""
            ).strip()

            player_id_text = (
                row["player_id"] or ""
            ).strip()

            if not alias:
                continue

            try:

                player_id = int(
                    player_id_text
                )

            except ValueError:

                raise ValueError(
                    f"{filename}:{line_number}: "
                    f"invalid player_id "
                    f"'{player_id_text}'"
                )

            merges.append(
                (
                    alias,
                    player_id
                )
            )

    return merges


def bulk_merge(
    conn,
    merges,
    confirm=False
):
    """
    Execute a list of alias -> player merges.
    """

    print()
    print(
        f"Processing {len(merges)} merge(s)..."
    )
    print()

    successful = 0
    skipped = 0

    for alias_name, target_id in merges:

        result = merge_alias(
            conn,
            alias_name,
            target_id,
            confirm=confirm
        )

        if result:

            successful += 1

        else:

            skipped += 1

    conn.commit()

    print()
    print("Bulk merge complete.")
    print(
        f"  Merged:  {successful}"
    )
    print(
        f"  Skipped: {skipped}"
    )


# ============================================================
# INTERACTIVE MODE
# ============================================================

def interactive_merge(conn):

    print()
    print("=== CTS Player Alias Merger ===")
    print()

    players = conn.execute(
        """
        SELECT
            p.id,
            p.canonical_name,
            COUNT(pa.id) AS alias_count
        FROM players p
        LEFT JOIN player_aliases pa
            ON pa.player_id = p.id
        GROUP BY p.id
        ORDER BY p.canonical_name
        """
    ).fetchall()

    if not players:

        print("No players in database.")
        return

    print("Players:")
    print()

    for player_id, name, alias_count in players:

        print(
            f"  [{player_id}] "
            f"{name} "
            f"({alias_count} aliases)"
        )

    print()

    alias_name = input(
        "Alias/name to merge: "
    ).strip()

    if not alias_name:

        print("Nothing entered.")
        return

    alias = get_alias(
        conn,
        alias_name
    )

    if not alias:

        print(
            f"Alias '{alias_name}' was not found."
        )

        return

    _, current_player_id, current_player = alias

    print()
    print(
        f"'{alias_name}' currently belongs to "
        f"Player #{current_player_id} "
        f"({current_player})."
    )

    try:

        target_id = int(
            input(
                "Merge into player ID: "
            ).strip()
        )

    except ValueError:

        print("Invalid player ID.")
        return

    merge_alias(
        conn,
        alias_name,
        target_id,
        confirm=True
    )

    conn.commit()


# ============================================================
# COMMAND LINE
# ============================================================

def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Merge CTS player aliases into canonical "
            "player identities."
        )
    )

    parser.add_argument(
        "--db",
        default=str(DATABASE_FILE),
        help="SQLite database file."
    )

    parser.add_argument(
        "--alias",
        action="append",
        help=(
            "Alias to merge. Can be specified multiple "
            "times."
        )
    )

    parser.add_argument(
        "--into",
        type=int,
        help=(
            "Target player ID for --alias."
        )
    )

    parser.add_argument(
        "--file",
        type=str,
        help=(
            "CSV file containing alias,player_id "
            "merge instructions."
        )
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip confirmation prompts in bulk mode."
        )
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_arguments()

    database = Path(args.db)

    if not database.exists():

        print(
            f"Database '{database}' does not exist."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Open database
    # --------------------------------------------------------

    conn = sqlite3.connect(
        database
    )

    try:

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        # ----------------------------------------------------
        # CSV bulk mode
        # ----------------------------------------------------

        if args.file:

            merges = load_merge_file(
                args.file
            )

            if not merges:

                print(
                    "No merge instructions found."
                )

                return

            bulk_merge(
                conn,
                merges,
                confirm=not args.yes
            )

            return

        # ----------------------------------------------------
        # Command-line bulk mode
        #
        # --alias can be repeated:
        #
        # --alias Foo --alias Bar --into 1
        # ----------------------------------------------------

        if args.alias:

            if args.into is None:

                print(
                    "--into is required when using "
                    "--alias."
                )

                sys.exit(1)

            merges = [
                (
                    alias,
                    args.into
                )
                for alias in args.alias
            ]

            bulk_merge(
                conn,
                merges,
                confirm=not args.yes
            )

            return

        # ----------------------------------------------------
        # Interactive mode
        # ----------------------------------------------------

        interactive_merge(conn)

    finally:

        conn.close()


if __name__ == "__main__":
    main()
