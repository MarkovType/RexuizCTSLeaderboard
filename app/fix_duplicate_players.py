#!/usr/bin/env python3
"""
Fix Duplicate Player Entries Script

This script identifies and fixes cases where the same player holds multiple
positions on the same map in the records table. Each player should only hold
ONE position per map.

Usage:
    python3 app/fix_duplicate_players.py

Safety:
    - Creates a backup of the database before making any changes
    - Only modifies records where duplicates are found
    - Keeps the HIGHEST rank (best position) for each player on each map
    - Logs all changes for review
"""

import sqlite3
import shutil
import os
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "cts.db"
BACKUP_DIR = BASE_DIR / "backups"

# ============================================================
# BACKUP DATABASE
# ============================================================

def create_backup():
    """
    Create a timestamped backup of the database.
    """

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"cts_backup_{timestamp}.db"

    print(f"Creating backup: {backup_file}")
    shutil.copy2(DATABASE, backup_file)

    return backup_file

# ============================================================
# FIND DUPLICATES
# ============================================================

def find_duplicate_entries():
    """
    Find all maps where the same player holds multiple positions.
    Returns a dict: {map_id: [(rank, record_id, player_id), ...]}
    """

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find all maps with duplicate players
    # In find_duplicate_entries():
    cursor.execute("""
        SELECT
            r1.map_id,
            r1.rank AS rank1,
            r1.id AS record_id1,
            r1.player_alias_id,
            pa1.player_id
        FROM records r1
        JOIN player_aliases pa1 ON pa1.id = r1.player_alias_id
        WHERE EXISTS (
            SELECT 1
            FROM records r2
            JOIN player_aliases pa2 ON pa2.id = r2.player_alias_id
            WHERE r2.map_id = r1.map_id
              AND pa2.player_id = pa1.player_id
              AND r2.id != r1.id
        )
        ORDER BY r1.map_id, r1.rank
    """)

    duplicates = {}
    for row in cursor.fetchall():
        map_id = row["map_id"]
        if map_id not in duplicates:
            duplicates[map_id] = []
        duplicates[map_id].append({
            "rank": row["rank1"],
            "record_id": row["record_id1"],
            "player_id": row["player_id"],
            "player_alias_id": row["player_alias_id"]
        })

    conn.close()
    return duplicates

# ============================================================
# FIX DUPLICATES
# ============================================================

def fix_duplicates(duplicates, dry_run=True):
    """
    Fix duplicate entries by keeping only the highest rank (lowest number).

    Args:
        duplicates: Dict of duplicate entries from find_duplicate_entries()
        dry_run: If True, only show what would be done without modifying

    Returns:
        List of actions taken: [(map_id, kept_rank, removed_ranks, removed_ids)]
    """

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    actions = []

    for map_id, records in duplicates.items():
        # Sort by rank (ascending) - rank 1 is best
        records.sort(key=lambda x: x["rank"])

        # Keep the first (highest rank)
        keep_record = records[0]

        # Remove all others
        remove_records = records[1:]

        if dry_run:
            print(f"[DRY RUN] Map {map_id}: Keep rank {keep_record['rank']}, "
                  f"remove ranks {[r['rank'] for r in remove_records]}")
        else:
            # Delete the duplicate records
            remove_ids = [r["record_id"] for r in remove_records]
            cursor.execute(
                "DELETE FROM records WHERE id IN ({})".format(",".join("?" * len(remove_ids))),
                remove_ids
            )
            conn.commit()

            print(f"[FIXED] Map {map_id}: Kept rank {keep_record['rank']} for player {keep_record['player_id']}, "
                  f"removed ranks {[r['rank'] for r in remove_records]}")

        actions.append({
            "map_id": map_id,
            "kept_rank": keep_record["rank"],
            "kept_record_id": keep_record["record_id"],
            "removed_ranks": [r["rank"] for r in remove_records],
            "removed_ids": [r["record_id"] for r in remove_records]
        })

    conn.close()
    return actions

# ============================================================
# VALIDATION CHECK
# ============================================================

def validate_no_duplicates():
    """
    Check if any duplicates remain after fixing.
    """

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) as count
        FROM (
            SELECT
                r.map_id,
                pa.player_id
            FROM records r
            JOIN player_aliases pa ON pa.id = r.player_alias_id
            GROUP BY r.map_id, pa.player_id
            HAVING COUNT(*) > 1
        ) duplicates
    """)

    result = cursor.fetchone()
    conn.close()

    # fetchone() returns a tuple, access by index
    return result[0] == 0  # ← FIXED: Use [0] instead of ["count"]

# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("DUPLICATE PLAYER ENTRIES FIX SCRIPT")
    print("=" * 70)
    print()

    # Check database exists
    if not DATABASE.exists():
        print(f"ERROR: Database not found at {DATABASE}")
        return 1

    # Step 1: Create backup
    print("[1/4] Creating database backup...")
    backup_file = create_backup()
    print(f"    Backup created: {backup_file}")
    print()

    # Step 2: Find duplicates
    print("[2/4] Scanning for duplicate player entries...")
    duplicates = find_duplicate_entries()

    if not duplicates:
        print("    ✓ No duplicate entries found!")
        print()
        print("=" * 70)
        print("DATABASE IS CLEAN - NO DUPLICATES FOUND")
        print("=" * 70)
        return 0

    print(f"    ✗ Found {len(duplicates)} maps with duplicate player entries:")
    for map_id, records in duplicates.items():
        player_ids = set(r["player_id"] for r in records)
        ranks = [r["rank"] for r in records]
        print(f"      Map {map_id}: Player(s) {player_ids} at ranks {ranks}")
    print()

    # Step 3: Show what would be fixed (dry run first)
    print("[3/4] Dry run - showing what would be fixed:")
    dry_run_actions = fix_duplicates(duplicates, dry_run=True)
    print(f"    Total actions: {len(dry_run_actions)} maps would be fixed")
    print()

    # Ask for confirmation
    response = input("[4/4] Apply fixes to database? (yes/no): ").strip().lower()

    if response != "yes":
        print("    Aborted. No changes were made to the database.")
        print("    You can run this script again later to apply the fixes.")
        print()
        print("=" * 70)
        print("DRY RUN COMPLETE - NO CHANGES MADE")
        print("=" * 70)
        return 0

    # Apply fixes
    print("[4/4] Applying fixes to database...")
    actions = fix_duplicates(duplicates, dry_run=False)
    print(f"    ✓ Fixed {len(actions)} maps")
    print()

    # Validate
    print("[VALIDATION] Checking for remaining duplicates...")
    if validate_no_duplicates():
        print("    ✓ No duplicate entries remain!")
    else:
        print("    ✗ WARNING: Some duplicates still exist!")
        print("    This may require manual investigation.")
    print()

    print("=" * 70)
    print("FIX COMPLETE")
    print(f"Backup: {backup_file}")
    print(f"Fixed: {len(actions)} maps")
    print("=" * 70)

    return 0

if __name__ == "__main__":
    exit(main())
