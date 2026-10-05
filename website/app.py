# ============================================================
# website/app.py
# ============================================================

import html
import sqlite3
from collections import defaultdict
from pathlib import Path

from flask import (
    Flask,
    abort,
    render_template,
    request,
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATABASE = (
    BASE_DIR.parent
    / "app"
    / "cts.db"
)


# ============================================================
# FLASK
# ============================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    """
    Open a database connection for the website.

    The website never modifies the database.
    """

    if not DATABASE.exists():
        raise RuntimeError(
            f"Database not found: {DATABASE}"
        )

    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    return conn


def query_one(sql, params=()):
    conn = get_db()

    try:
        return conn.execute(
            sql,
            params
        ).fetchone()

    finally:
        conn.close()


def query_all(sql, params=()):
    conn = get_db()

    try:
        return conn.execute(
            sql,
            params
        ).fetchall()

    finally:
        conn.close()


# ============================================================
# HELPERS
# ============================================================

def format_time(seconds):
    """
    Convert seconds into the CTS display format.

    Examples:

        10.27 -> 0:10.27
        70.50 -> 1:10.50
    """

    if seconds is None:
        return ""

    minutes = int(
        seconds // 60
    )

    remaining = (
        seconds
        - (minutes * 60)
    )

    return (
        f"{minutes}:"
        f"{remaining:05.2f}"
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    # --------------------------------------------------------
    # Latest scrape
    #
    # records is now the CURRENT state and therefore has no
    # scrape_id.
    #
    # The latest scrape timestamp still comes from scrapes.
    # --------------------------------------------------------

    latest_scrape = query_one(
        """
        SELECT
            s.id,
            s.scraped_at,
            s.source_url,
            s.content_hash,

            (
                SELECT COUNT(*)
                FROM maps
            ) AS total_maps,

            (
                SELECT COUNT(*)
                FROM records
            ) AS total_records

        FROM scrapes s

        ORDER BY s.id DESC

        LIMIT 1
        """
    )

    # --------------------------------------------------------
    # Recent record changes
    #
    # These are the 10 most recent changes in record_history,
    # regardless of rank.
    #
    # IMPORTANT:
    #
    # This is intentionally NOT restricted to rank = 1.
    # --------------------------------------------------------

    recent_records = query_all(
        """
        SELECT
            h.id,
            h.scrape_id,
            h.map_id,
            h.rank,

            h.time_text,
            h.time_seconds,

            s.scraped_at,

            m.name AS map_name,

            p.id AS player_id,
            p.canonical_name AS player_name,

            pa.name AS name_used

        FROM record_history h

        JOIN scrapes s
            ON s.id = h.scrape_id

        JOIN maps m
            ON m.id = h.map_id

        JOIN player_aliases pa
            ON pa.id = h.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        ORDER BY
            h.id DESC

        LIMIT 10
        """
    )

    # --------------------------------------------------------
    # Current world records
    #
    # Keep current #1 records exactly as before.
    # --------------------------------------------------------

    recent_top1 = query_all(
        """
        SELECT
            h.id,
            h.scrape_id,
            h.map_id,
            h.rank,

            h.time_text,
            h.time_seconds,

            s.scraped_at,

            m.name AS map_name,

            p.id AS player_id,
            p.canonical_name AS player_name,

            pa.name AS name_used

        FROM record_history h

        JOIN scrapes s
            ON s.id = h.scrape_id

        JOIN maps m
            ON m.id = h.map_id

        JOIN player_aliases pa
            ON pa.id = h.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        WHERE h.rank = 1

        ORDER BY
            h.id DESC

        LIMIT 3
        """
    )

    # --------------------------------------------------------
    # Current top record holders
    #
    # records is already the current leaderboard.
    #
    # There is NO need to select a particular scrape.
    # --------------------------------------------------------

    top_holders = query_all(
        """
        SELECT
            p.id,
            p.canonical_name,

            SUM(
                CASE
                    WHEN r.rank = 1
                    THEN 1
                    ELSE 0
                END
            ) AS rank1,

            SUM(
                CASE
                    WHEN r.rank = 2
                    THEN 1
                    ELSE 0
                END
            ) AS rank2,

            SUM(
                CASE
                    WHEN r.rank = 3
                    THEN 1
                    ELSE 0
                END
            ) AS rank3,

            SUM(
                CASE
                    WHEN r.rank = 4
                    THEN 1
                    ELSE 0
                END
            ) AS rank4,

            SUM(
                CASE
                    WHEN r.rank = 5
                    THEN 1
                    ELSE 0
                END
            ) AS rank5,

            SUM(
                CASE
                    WHEN r.rank = 6
                    THEN 1
                    ELSE 0
                END
            ) AS rank6,

            SUM(
                CASE
                    WHEN r.rank = 7
                    THEN 1
                    ELSE 0
                END
            ) AS rank7,

            SUM(
                CASE
                    WHEN r.rank = 8
                    THEN 1
                    ELSE 0
                END
            ) AS rank8,

            SUM(
                CASE
                    WHEN r.rank = 9
                    THEN 1
                    ELSE 0
                END
            ) AS rank9,

            SUM(
                CASE
                    WHEN r.rank = 10
                    THEN 1
                    ELSE 0
                END
            ) AS rank10,

            COUNT(*) AS total

        FROM records r

        JOIN player_aliases pa
            ON pa.id = r.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        GROUP BY p.id

        ORDER BY
            total DESC,
            p.canonical_name

        LIMIT 10
        """
    )

    return render_template(
        "index.html",
        latest_scrape=latest_scrape,
        recent_records=recent_records,
        recent_top1=recent_top1,
        top_holders=top_holders,
        format_time=format_time,
    )


# ============================================================
# MAP LIST
# ============================================================

@app.route("/maps")
def maps():

    search = request.args.get(
        "q",
        ""
    ).strip()

    page = max(
        request.args.get(
            "page",
            1,
            type=int
        ),
        1
    )

    per_page = 50

    if search:

        pattern = f"%{search}%"

        total = query_one(
            """
            SELECT COUNT(*)
            FROM maps
            WHERE name LIKE ?
            """,
            (pattern,)
        )[0]

        map_rows = query_all(
            """
            SELECT
                id,
                name
            FROM maps
            WHERE name LIKE ?
            ORDER BY name
            LIMIT ?
            OFFSET ?
            """,
            (
                pattern,
                per_page,
                (page - 1) * per_page
            )
        )

    else:

        total = query_one(
            """
            SELECT COUNT(*)
            FROM maps
            """
        )[0]

        map_rows = query_all(
            """
            SELECT
                id,
                name
            FROM maps
            ORDER BY name
            LIMIT ?
            OFFSET ?
            """,
            (
                per_page,
                (page - 1) * per_page
            )
        )

    pages = max(
        (total + per_page - 1)
        // per_page,
        1
    )

    return render_template(
        "maps.html",
        maps=map_rows,
        search=search,
        page=page,
        pages=pages,
    )


# ============================================================
# MAP PAGE
# ============================================================

@app.route("/map/<int:map_id>")
def map_page(map_id):

    # --------------------------------------------------------
    # Map
    # --------------------------------------------------------

    map_row = query_one(
        """
        SELECT
            id,
            name
        FROM maps
        WHERE id = ?
        """,
        (map_id,)
    )

    if not map_row:
        abort(404)

    # --------------------------------------------------------
    # CURRENT TOP 10
    #
    # records contains ONLY current state.
    # --------------------------------------------------------

    current_records = query_all(
        """
        SELECT
            r.rank,
            r.time_text,
            r.time_seconds,

            p.id AS player_id,
            p.canonical_name AS player_name,

            pa.name AS name_used

        FROM records r

        JOIN player_aliases pa
            ON pa.id = r.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        WHERE r.map_id = ?

        ORDER BY r.rank
        """,
        (map_id,)
    )

    # --------------------------------------------------------
    # COMPLETE HISTORY
    #
    # record_history contains only CHANGES.
    #
    # This is also used by the history table shown below the
    # graph.
    # --------------------------------------------------------

    history = query_all(
        """
        SELECT
            h.id,
            h.scrape_id,
            h.rank,

            h.time_seconds,
            h.time_text,

            s.scraped_at,

            p.id AS player_id,
            p.canonical_name AS player_name,

            pa.name AS name_used

        FROM record_history h

        JOIN scrapes s
            ON s.id = h.scrape_id

        JOIN player_aliases pa
            ON pa.id = h.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        WHERE h.map_id = ?

        ORDER BY
            h.scrape_id,
            h.rank,
            h.id
        """,
        (map_id,)
    )

    # --------------------------------------------------------
    # Reconstructed SVG graph.
    #
    # The function receives map_id and loads the history
    # itself. This avoids passing an integer where a history
    # collection is expected.
    # --------------------------------------------------------

    chart = make_record_history_svg(
        map_id
    )

    return render_template(
        "map.html",
        map=map_row,
        records=current_records,
        history=history,
        chart=chart,
        format_time=format_time,
    )


# ============================================================
# PLAYER LIST
# ============================================================

@app.route("/players")
def players():

    search = request.args.get(
        "q",
        ""
    ).strip()

    if search:

        rows = query_all(
            """
            SELECT
                p.id,
                p.canonical_name,

                SUM(
                    CASE
                        WHEN r.rank = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS rank1,

                SUM(
                    CASE
                        WHEN r.rank <= 3
                        THEN 1
                        ELSE 0
                    END
                ) AS top3,

                COUNT(r.id) AS total

            FROM players p

            LEFT JOIN player_aliases pa
                ON pa.player_id = p.id

            LEFT JOIN records r
                ON r.player_alias_id =
                   pa.id

            WHERE p.canonical_name LIKE ?

            GROUP BY p.id

            ORDER BY
                total DESC,
                p.canonical_name

            LIMIT 200
            """,
            (
                f"%{search}%",
            )
        )

    else:

        rows = query_all(
            """
            SELECT
                p.id,
                p.canonical_name,

                SUM(
                    CASE
                        WHEN r.rank = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS rank1,

                SUM(
                    CASE
                        WHEN r.rank <= 3
                        THEN 1
                        ELSE 0
                    END
                ) AS top3,

                COUNT(r.id) AS total

            FROM players p

            LEFT JOIN player_aliases pa
                ON pa.player_id = p.id

            LEFT JOIN records r
                ON r.player_alias_id =
                   pa.id

            GROUP BY p.id

            ORDER BY
                total DESC,
                p.canonical_name

            LIMIT 200
            """
        )

    return render_template(
        "players.html",
        players=rows,
        search=search,
    )


# ============================================================
# PLAYER PAGE
# ============================================================

@app.route("/player/<int:player_id>")
def player_page(player_id):

    # --------------------------------------------------------
    # Player
    # --------------------------------------------------------

    player = query_one(
        """
        SELECT
            id,
            canonical_name
        FROM players
        WHERE id = ?
        """,
        (player_id,)
    )

    if not player:
        abort(404)

    # --------------------------------------------------------
    # Aliases
    # --------------------------------------------------------

    aliases = query_all(
        """
        SELECT
            name,
            first_seen,
            last_seen

        FROM player_aliases

        WHERE player_id = ?

        ORDER BY name
        """,
        (player_id,)
    )

    # --------------------------------------------------------
    # CURRENT RECORDS
    #
    # No scrape_id.
    # --------------------------------------------------------

    current_records = query_all(
        """
        SELECT
            r.rank,
            r.time_text,
            r.time_seconds,

            m.id AS map_id,
            m.name AS map_name,

            pa.name AS name_used

        FROM records r

        JOIN maps m
            ON m.id = r.map_id

        JOIN player_aliases pa
            ON pa.id = r.player_alias_id

        WHERE pa.player_id = ?

        ORDER BY
            r.rank,
            m.name
        """,
        (player_id,)
    )

    # --------------------------------------------------------
    # CURRENT STATISTICS
    # --------------------------------------------------------

    statistics = query_one(
        """
        SELECT
            SUM(
                CASE
                    WHEN r.rank = 1
                    THEN 1
                    ELSE 0
                END
            ) AS rank1,

            SUM(
                CASE
                    WHEN r.rank = 2
                    THEN 1
                    ELSE 0
                END
            ) AS rank2,

            SUM(
                CASE
                    WHEN r.rank = 3
                    THEN 1
                    ELSE 0
                END
            ) AS rank3,

            SUM(
                CASE
                    WHEN r.rank = 4
                    THEN 1
                    ELSE 0
                END
            ) AS rank4,

            SUM(
                CASE
                    WHEN r.rank = 5
                    THEN 1
                    ELSE 0
                END
            ) AS rank5,

            SUM(
                CASE
                    WHEN r.rank = 6
                    THEN 1
                    ELSE 0
                END
            ) AS rank6,

            SUM(
                CASE
                    WHEN r.rank = 7
                    THEN 1
                    ELSE 0
                END
            ) AS rank7,

            SUM(
                CASE
                    WHEN r.rank = 8
                    THEN 1
                    ELSE 0
                END
            ) AS rank8,

            SUM(
                CASE
                    WHEN r.rank = 9
                    THEN 1
                    ELSE 0
                END
            ) AS rank9,

            SUM(
                CASE
                    WHEN r.rank = 10
                    THEN 1
                    ELSE 0
                END
            ) AS rank10,

            COUNT(r.id) AS total

        FROM records r

        JOIN player_aliases pa
            ON pa.id = r.player_alias_id

        WHERE pa.player_id = ?
        """,
        (player_id,)
    )

    # --------------------------------------------------------
    # PLAYER HISTORY
    #
    # record_history contains only CHANGES.
    #
    # Therefore reconstruct the player's number of positions
    # after each scrape.
    # --------------------------------------------------------

    history = reconstruct_player_history(
        player_id
    )

    chart = make_player_history_svg(
        history
    )

    return render_template(
        "player.html",
        player=player,
        aliases=aliases,
        records=current_records,
        statistics=statistics,
        history=history,
        chart=chart,
    )


# ============================================================
# PLAYER HISTORY RECONSTRUCTION
# ============================================================

def reconstruct_player_history(player_id):
    """
    Reconstruct how many current top-10 positions a player held
    after every scrape.

    record_history is an event log rather than a full snapshot.

    Example:

        scrape 1:
            map A / #1 / Alice
            map A / #2 / Bob

        scrape 2:
            map A / #1 / Bob

    After scrape 1:
        Alice = 1
        Bob   = 1

    After scrape 2:
        Alice = 0
        Bob   = 2

    This function performs that reconstruction for one player.
    """

    rows = query_all(
        """
        SELECT
            h.scrape_id,
            h.map_id,
            h.rank,
            h.player_alias_id,

            s.scraped_at,

            pa.player_id

        FROM record_history h

        JOIN scrapes s
            ON s.id = h.scrape_id

        JOIN player_aliases pa
            ON pa.id = h.player_alias_id

        ORDER BY
            h.scrape_id,
            h.id
        """
    )

    # --------------------------------------------------------
    # Current holder of every map/rank.
    #
    # key:
    #     (map_id, rank)
    #
    # value:
    #     player_id
    # --------------------------------------------------------

    state = {}

    # Number of positions currently held by each player.
    player_counts = defaultdict(int)

    result = []

    current_scrape_id = None
    current_scrape_at = None

    def append_snapshot(
        scrape_id,
        scraped_at
    ):
        result.append(
            {
                "scrape_id": scrape_id,
                "scraped_at": scraped_at,
                "record_count": player_counts.get(
                    player_id,
                    0
                ),
            }
        )

    for row in rows:

        scrape_id = row["scrape_id"]

        # ----------------------------------------------------
        # New scrape.
        # ----------------------------------------------------

        if (
            current_scrape_id is not None
            and scrape_id != current_scrape_id
        ):

            append_snapshot(
                current_scrape_id,
                current_scrape_at
            )

        current_scrape_id = scrape_id
        current_scrape_at = row["scraped_at"]

        key = (
            row["map_id"],
            row["rank"]
        )

        old_player_id = state.get(
            key
        )

        new_player_id = row["player_id"]

        # ----------------------------------------------------
        # Nothing changed.
        # ----------------------------------------------------

        if old_player_id == new_player_id:
            continue

        # ----------------------------------------------------
        # Remove old holder.
        # ----------------------------------------------------

        if old_player_id is not None:

            player_counts[
                old_player_id
            ] -= 1

        # ----------------------------------------------------
        # Add new holder.
        # ----------------------------------------------------

        state[key] = new_player_id

        player_counts[
            new_player_id
        ] += 1

    # --------------------------------------------------------
    # Final scrape.
    # --------------------------------------------------------

    if current_scrape_id is not None:

        append_snapshot(
            current_scrape_id,
            current_scrape_at
        )

    return result


# ============================================================
# SVG: MAP RECORD HISTORY
# ============================================================

def make_record_history_svg(map_id):
    """
    Render the reconstructed Top-10 leaderboard history for
    one map.

    Time range:

        First known record -> present

    Each rank (#1 through #10) gets its own line.

    The graph uses STEP lines:

        horizontal = the record remains unchanged
        vertical   = the record changes

    record_history contains only changes rather than snapshots,
    so the complete leaderboard state is reconstructed first.

    A new visual state is emitted only when one or more displayed
    time values actually change.

    A player/name change that leaves the displayed time unchanged
    does NOT create a redundant visual point.
    """

    # --------------------------------------------------------
    # Load complete history for this map.
    # --------------------------------------------------------

    history = query_all(
        """
        SELECT
            h.id,
            h.scrape_id,
            h.rank,

            h.time_seconds,
            h.time_text,

            s.scraped_at,

            p.id AS player_id,
            p.canonical_name AS player_name,

            pa.name AS name_used

        FROM record_history h

        JOIN scrapes s
            ON s.id = h.scrape_id

        JOIN player_aliases pa
            ON pa.id = h.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        WHERE h.map_id = ?

        ORDER BY
            h.scrape_id,
            h.id
        """,
        (map_id,)
    )

    if not history:
        return ""

    # --------------------------------------------------------
    # SVG dimensions.
    # --------------------------------------------------------

    width = 1200
    height = 560

    padding_left = 75
    padding_right = 30
    padding_top = 35
    padding_bottom = 60

    graph_width = (
        width
        - padding_left
        - padding_right
    )

    graph_height = (
        height
        - padding_top
        - padding_bottom
    )

    # --------------------------------------------------------
    # Group changes by scrape.
    #
    # Several ranks can change during one scrape.
    #
    # All of them must be applied before we decide whether the
    # resulting visual state is different.
    # --------------------------------------------------------

    scrapes = {}

    for row in history:

        scrape_id = row["scrape_id"]

        if scrape_id not in scrapes:

            scrapes[scrape_id] = {
                "scraped_at":
                    row["scraped_at"],

                "events": [],
            }

        scrapes[
            scrape_id
        ]["events"].append(
            row
        )

    scrape_ids = list(
        scrapes.keys()
    )

    scrape_ids.sort()

    if not scrape_ids:
        return ""

    # --------------------------------------------------------
    # Current reconstructed state.
    #
    # state[rank] is the record currently occupying that rank.
    # --------------------------------------------------------

    state = {
        rank: None
        for rank in range(1, 11)
    }

    # --------------------------------------------------------
    # Return only the graph-visible state.
    #
    # Player/name changes with the same time are intentionally
    # ignored here.
    # --------------------------------------------------------

    def visual_state():

        return tuple(
            (
                state[rank]["time_seconds"]
                if state[rank] is not None
                else None
            )
            for rank in range(1, 11)
        )

    # --------------------------------------------------------
    # Reconstruct snapshots.
    #
    # A snapshot is emitted only if the visual state changed.
    # --------------------------------------------------------

    snapshots = []

    previous_visual_state = None

    for scrape_id in scrape_ids:

        scrape = scrapes[
            scrape_id
        ]

        # ----------------------------------------------------
        # Apply ALL changes belonging to this scrape.
        # ----------------------------------------------------

        for row in scrape["events"]:

            rank = row["rank"]

            if rank < 1 or rank > 10:
                continue

            state[rank] = {
                "time_seconds":
                    row["time_seconds"],

                "time_text":
                    row["time_text"],

                "player_id":
                    row["player_id"],

                "player_name":
                    row["player_name"],

                "name_used":
                    row["name_used"],
            }

        current_visual_state = (
            visual_state()
        )

        # ----------------------------------------------------
        # Only retain states that actually change what the
        # graph displays.
        # ----------------------------------------------------

        if (
            previous_visual_state is None
            or current_visual_state
            != previous_visual_state
        ):

            snapshots.append(
                {
                    "scrape_id":
                        scrape_id,

                    "scraped_at":
                        scrape["scraped_at"],

                    "values":
                        current_visual_state,
                }
            )

            previous_visual_state = (
                current_visual_state
            )

    if not snapshots:
        return ""

    # --------------------------------------------------------
    # Determine global Y-axis time range.
    # --------------------------------------------------------

    all_values = []

    for snapshot in snapshots:

        for value in snapshot["values"]:

            if value is not None:
                all_values.append(
                    value
                )

    if not all_values:
        return ""

    minimum = min(
        all_values
    )

    maximum = max(
        all_values
    )

    # --------------------------------------------------------
    # Avoid zero-height scale.
    # --------------------------------------------------------

    if minimum == maximum:

        minimum -= 1
        maximum += 1

    # --------------------------------------------------------
    # Add a small amount of visual padding.
    # --------------------------------------------------------

    value_range = (
        maximum - minimum
    )

    minimum -= (
        value_range * 0.04
    )

    maximum += (
        value_range * 0.04
    )

    # --------------------------------------------------------
    # X coordinate.
    #
    # First known state = left edge.
    # Last known state = right edge.
    #
    # There is NO 365-day restriction.
    # --------------------------------------------------------

    snapshot_count = len(
        snapshots
    )

    def x_for_index(index):

        if snapshot_count <= 1:

            return (
                padding_left
                + graph_width / 2
            )

        return (
            padding_left
            + graph_width
            * index
            / (snapshot_count - 1)
        )

    # --------------------------------------------------------
    # Y coordinate.
    #
    # Lower time = higher on graph.
    # --------------------------------------------------------

    def y_for_value(value):

        return (
            padding_top
            + (
                (maximum - value)
                / (maximum - minimum)
            )
            * graph_height
        )

    # --------------------------------------------------------
    # Start SVG.
    # --------------------------------------------------------

    svg = []

    svg.append(
        f'<svg class="chart" '
        f'viewBox="0 0 {width} {height}" '
        f'role="img" '
        f'aria-label="Top 10 record history">'
    )

    svg.append(
        f'<rect '
        f'width="{width}" '
        f'height="{height}" '
        f'fill="#090909"/>'
    )

    # --------------------------------------------------------
    # Horizontal grid.
    # --------------------------------------------------------

    for i in range(5):

        y = (
            padding_top
            + graph_height * i / 4
        )

        value = (
            maximum
            - (
                maximum - minimum
            ) * i / 4
        )

        svg.append(
            f'<line '
            f'x1="{padding_left}" '
            f'y1="{y:.1f}" '
            f'x2="{width - padding_right}" '
            f'y2="{y:.1f}" '
            f'stroke="#282828" '
            f'stroke-width="1"/>'
        )

        svg.append(
            f'<text '
            f'x="{padding_left - 10}" '
            f'y="{y + 4:.1f}" '
            f'text-anchor="end" '
            f'fill="#888" '
            f'font-size="11">'
            f'{html.escape(format_time(value))}'
            f'</text>'
        )

    # --------------------------------------------------------
    # Rank colors.
    # --------------------------------------------------------

    colors = [
        "#ffb000",
        "#e04a22",
        "#4fc3f7",
        "#81c784",
        "#ba68c8",
        "#ff8a65",
        "#64b5f6",
        "#aed581",
        "#f06292",
        "#90a4ae",
    ]

    # --------------------------------------------------------
    # Draw each rank.
    # --------------------------------------------------------

    for rank in range(1, 11):

        color = colors[
            rank - 1
        ]

        points = []

        for index, snapshot in enumerate(
            snapshots
        ):

            value = snapshot[
                "values"
            ][rank - 1]

            if value is None:
                continue

            x = x_for_index(
                index
            )

            y = y_for_value(
                value
            )

            points.append(
                (
                    x,
                    y
                )
            )

        if not points:
            continue

        # ----------------------------------------------------
        # Step path.
        #
        # From A to B:
        #
        #   H B.x
        #   V B.y
        #
        # Therefore:
        #
        #   horizontal = unchanged state
        #   vertical   = state transition
        # ----------------------------------------------------

        path = [
            f"M {points[0][0]:.1f} "
            f"{points[0][1]:.1f}"
        ]

        for x, y in points[1:]:

            path.append(
                f"H {x:.1f}"
            )

            path.append(
                f"V {y:.1f}"
            )

        svg.append(
            f'<path '
            f'd="{" ".join(path)}" '
            f'fill="none" '
            f'stroke="{color}" '
            f'stroke-width="2" '
            f'stroke-opacity="0.85" '
            f'stroke-linejoin="round"/>'
        )

        # ----------------------------------------------------
        # Points.
        #
        # These correspond only to retained visual states.
        # ----------------------------------------------------

        for x, y in points:

            svg.append(
                f'<circle '
                f'cx="{x:.1f}" '
                f'cy="{y:.1f}" '
                f'r="3" '
                f'fill="{color}" '
                f'stroke="#090909" '
                f'stroke-width="1"/>'
            )

    # --------------------------------------------------------
    # Date labels.
    # --------------------------------------------------------

    first_date = (
        snapshots[0]["scraped_at"]
    )

    last_date = (
        snapshots[-1]["scraped_at"]
    )

    svg.append(
        f'<text '
        f'x="{padding_left}" '
        f'y="{height - 18}" '
        f'fill="#666" '
        f'font-size="10">'
        f'{html.escape(first_date[:10])}'
        f'</text>'
    )

    svg.append(
        f'<text '
        f'x="{width - padding_right}" '
        f'y="{height - 18}" '
        f'text-anchor="end" '
        f'fill="#666" '
        f'font-size="10">'
        f'{html.escape(last_date[:10])}'
        f'</text>'
    )

    # --------------------------------------------------------
    # Legend.
    # --------------------------------------------------------

    legend_y = (
        height - 42
    )

    legend_width = (
        width
        - padding_left
        - padding_right
    )

    item_width = (
        legend_width / 10
    )

    for index, rank in enumerate(
        range(1, 11)
    ):

        color = colors[
            index
        ]

        x = (
            padding_left
            + item_width * index
        )

        svg.append(
            f'<circle '
            f'cx="{x:.1f}" '
            f'cy="{legend_y:.1f}" '
            f'r="4" '
            f'fill="{color}"/>'
        )

        svg.append(
            f'<text '
            f'x="{x + 8:.1f}" '
            f'y="{legend_y + 4:.1f}" '
            f'fill="#888" '
            f'font-size="10">'
            f'#{rank}'
            f'</text>'
        )

    svg.append(
        "</svg>"
    )

    return "".join(svg)


# ============================================================
# SVG: PLAYER HISTORY
# ============================================================

def make_player_history_svg(history):

    width = 900
    height = 300

    if not history:
        return ""

    values = [
        row["record_count"]
        for row in history
    ]

    if not values:
        return ""

    maximum = max(
        values
    )

    if maximum <= 0:
        return ""

    padding_left = 55
    padding_right = 30
    padding_top = 30
    padding_bottom = 40

    graph_width = (
        width
        - padding_left
        - padding_right
    )

    graph_height = (
        height
        - padding_top
        - padding_bottom
    )

    svg = []

    svg.append(
        f'<svg class="chart" '
        f'viewBox="0 0 {width} {height}" '
        f'role="img" '
        f'aria-label="Player record count history">'
    )

    svg.append(
        f'<rect '
        f'width="{width}" '
        f'height="{height}" '
        f'fill="#090909"/>'
    )

    # --------------------------------------------------------
    # Horizontal grid.
    # --------------------------------------------------------

    for i in range(5):

        y = (
            padding_top
            + graph_height * i / 4
        )

        value = (
            maximum
            - maximum * i / 4
        )

        svg.append(
            f'<line '
            f'x1="{padding_left}" '
            f'y1="{y:.1f}" '
            f'x2="{width - padding_right}" '
            f'y2="{y:.1f}" '
            f'stroke="#282828"/>'
        )

        svg.append(
            f'<text '
            f'x="{padding_left - 8}" '
            f'y="{y + 4:.1f}" '
            f'text-anchor="end" '
            f'fill="#888" '
            f'font-size="11">'
            f'{int(value)}'
            f'</text>'
        )

    # --------------------------------------------------------
    # Coordinates.
    # --------------------------------------------------------

    coordinates = []

    count = len(
        values
    )

    for i, value in enumerate(
        values
    ):

        if count == 1:

            x = (
                padding_left
                + graph_width / 2
            )

        else:

            x = (
                padding_left
                + graph_width
                * i
                / (count - 1)
            )

        y = (
            padding_top
            + graph_height
            - (
                value / maximum
            )
            * graph_height
        )

        coordinates.append(
            (
                x,
                y
            )
        )

    # --------------------------------------------------------
    # Line.
    # --------------------------------------------------------

    polyline = " ".join(
        f"{x:.1f},{y:.1f}"
        for x, y in coordinates
    )

    svg.append(
        f'<polyline '
        f'points="{polyline}" '
        f'fill="none" '
        f'stroke="#e04a22" '
        f'stroke-width="3"/>'
    )

    # --------------------------------------------------------
    # Points.
    # --------------------------------------------------------

    for x, y in coordinates:

        svg.append(
            f'<circle '
            f'cx="{x:.1f}" '
            f'cy="{y:.1f}" '
            f'r="4" '
            f'fill="#ffb000"/>'
        )

    svg.append(
        "</svg>"
    )

    return "".join(svg)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
    )
