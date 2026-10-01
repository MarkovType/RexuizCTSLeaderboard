# ============================================================
# website/app.py
# ============================================================

import html
import sqlite3
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
DATABASE = BASE_DIR.parent / "app" / "cts.db"


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

    if not DATABASE.exists():
        raise RuntimeError(
            f"Database not found: {DATABASE}"
        )

    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# HELPERS
# ============================================================

def format_time(seconds):

    if seconds is None:
        return ""

    minutes = int(seconds // 60)
    remaining = seconds - (minutes * 60)

    return f"{minutes}:{remaining:05.2f}"


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
# HOME
# ============================================================

@app.route("/")
def index():

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
                WHERE scrape_id = s.id
            ) AS total_records

        FROM scrapes s
        ORDER BY s.id DESC
        LIMIT 1
        """
    )

    recent_top1 = query_all(
        """
        SELECT
            c.id,
            c.scrape_id,
            c.time_text,
            c.time_seconds,
            s.scraped_at,

            m.id AS map_id,
            m.name AS map_name,

            p.id AS player_id,
            p.canonical_name AS player_name,

            pa.name AS name_used

        FROM top1_changes c

        JOIN scrapes s
            ON s.id = c.scrape_id

        JOIN maps m
            ON m.id = c.map_id

        JOIN player_aliases pa
            ON pa.id = c.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        ORDER BY c.id DESC
        LIMIT 3
        """
    )

    top_holders = query_all(
        """
        SELECT
            p.id,
            p.canonical_name,

            SUM(CASE WHEN r.rank = 1 THEN 1 ELSE 0 END)
                AS rank1,

            SUM(CASE WHEN r.rank = 2 THEN 1 ELSE 0 END)
                AS rank2,

            SUM(CASE WHEN r.rank = 3 THEN 1 ELSE 0 END)
                AS rank3,

            SUM(CASE WHEN r.rank = 4 THEN 1 ELSE 0 END)
                AS rank4,

            SUM(CASE WHEN r.rank = 5 THEN 1 ELSE 0 END)
                AS rank5,

            SUM(CASE WHEN r.rank = 6 THEN 1 ELSE 0 END)
                AS rank6,

            SUM(CASE WHEN r.rank = 7 THEN 1 ELSE 0 END)
                AS rank7,

            SUM(CASE WHEN r.rank = 8 THEN 1 ELSE 0 END)
                AS rank8,

            SUM(CASE WHEN r.rank = 9 THEN 1 ELSE 0 END)
                AS rank9,

            SUM(CASE WHEN r.rank = 10 THEN 1 ELSE 0 END)
                AS rank10,

            COUNT(*) AS total

        FROM records r

        JOIN player_aliases pa
            ON pa.id = r.player_alias_id

        JOIN players p
            ON p.id = pa.player_id

        WHERE r.scrape_id = (
            SELECT MAX(id)
            FROM scrapes
        )

        GROUP BY p.id

        ORDER BY total DESC, p.canonical_name

        LIMIT 10
        """
    )

    return render_template(
        "index.html",
        latest_scrape=latest_scrape,
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
            SELECT id, name
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
            SELECT id, name
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
        (total + per_page - 1) // per_page,
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

    map_row = query_one(
        """
        SELECT id, name
        FROM maps
        WHERE id = ?
        """,
        (map_id,)
    )

    if not map_row:
        abort(404)

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

          AND r.scrape_id = (
              SELECT MAX(id)
              FROM scrapes
          )

        ORDER BY r.rank
        """,
        (map_id,)
    )

    history = query_all(
    """
    SELECT
        c.time_seconds,
        c.time_text,
        s.scraped_at,

        p.id AS player_id,
        p.canonical_name AS player_name

    FROM top1_changes c

    JOIN scrapes s
        ON s.id = c.scrape_id

    JOIN player_aliases pa
        ON pa.id = c.player_alias_id

    JOIN players p
        ON p.id = pa.player_id

    WHERE c.map_id = ?

    ORDER BY c.id
    """,
    (map_id,)
)


    chart = make_record_history_svg(
        history
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
                    CASE WHEN r.rank = 1
                    THEN 1 ELSE 0 END
                ) AS rank1,

                SUM(
                    CASE WHEN r.rank <= 3
                    THEN 1 ELSE 0 END
                ) AS top3,

                COUNT(*) AS total

            FROM players p

            LEFT JOIN player_aliases pa
                ON pa.player_id = p.id

            LEFT JOIN records r
                ON r.player_alias_id = pa.id
               AND r.scrape_id = (
                   SELECT MAX(id)
                   FROM scrapes
               )

            WHERE p.canonical_name LIKE ?

            GROUP BY p.id

            ORDER BY total DESC, p.canonical_name
            LIMIT 200
            """,
            (f"%{search}%",)
        )

    else:

        rows = query_all(
            """
            SELECT
                p.id,
                p.canonical_name,

                SUM(
                    CASE WHEN r.rank = 1
                    THEN 1 ELSE 0 END
                ) AS rank1,

                SUM(
                    CASE WHEN r.rank <= 3
                    THEN 1 ELSE 0 END
                ) AS top3,

                COUNT(r.id) AS total

            FROM players p

            LEFT JOIN player_aliases pa
                ON pa.player_id = p.id

            LEFT JOIN records r
                ON r.player_alias_id = pa.id
               AND r.scrape_id = (
                   SELECT MAX(id)
                   FROM scrapes
               )

            GROUP BY p.id

            ORDER BY total DESC, p.canonical_name
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

    player = query_one(
        """
        SELECT id, canonical_name
        FROM players
        WHERE id = ?
        """,
        (player_id,)
    )

    if not player:
        abort(404)

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

          AND r.scrape_id = (
              SELECT MAX(id)
              FROM scrapes
          )

        ORDER BY r.rank, m.name
        """,
        (player_id,)
    )

    statistics = query_one(
        """
        SELECT
            SUM(CASE WHEN r.rank = 1 THEN 1 ELSE 0 END) AS rank1,
            SUM(CASE WHEN r.rank = 2 THEN 1 ELSE 0 END) AS rank2,
            SUM(CASE WHEN r.rank = 3 THEN 1 ELSE 0 END) AS rank3,
            SUM(CASE WHEN r.rank = 4 THEN 1 ELSE 0 END) AS rank4,
            SUM(CASE WHEN r.rank = 5 THEN 1 ELSE 0 END) AS rank5,
            SUM(CASE WHEN r.rank = 6 THEN 1 ELSE 0 END) AS rank6,
            SUM(CASE WHEN r.rank = 7 THEN 1 ELSE 0 END) AS rank7,
            SUM(CASE WHEN r.rank = 8 THEN 1 ELSE 0 END) AS rank8,
            SUM(CASE WHEN r.rank = 9 THEN 1 ELSE 0 END) AS rank9,
            SUM(CASE WHEN r.rank = 10 THEN 1 ELSE 0 END) AS rank10,
            COUNT(r.id) AS total

        FROM records r

        JOIN player_aliases pa
            ON pa.id = r.player_alias_id

        WHERE pa.player_id = ?

          AND r.scrape_id = (
              SELECT MAX(id)
              FROM scrapes
          )
        """,
        (player_id,)
    )

    history = query_all(
        """
        SELECT
            s.scraped_at,
            COUNT(*) AS record_count

        FROM records r

        JOIN scrapes s
            ON s.id = r.scrape_id

        JOIN player_aliases pa
            ON pa.id = r.player_alias_id

        WHERE pa.player_id = ?

        GROUP BY s.id

        ORDER BY s.id
        """,
        (player_id,)
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
        format_time=format_time,
    )


# ============================================================
# SVG: MAP RECORD HISTORY
# ============================================================

def make_record_history_svg(history):

    width = 900
    height = 320

    if not history:
        return ""

    points = [
        row["time_seconds"]
        for row in history
        if row["time_seconds"] is not None
    ]

    if not points:
        return ""

    minimum = min(points)
    maximum = max(points)

    if minimum == maximum:
        minimum -= 1
        maximum += 1

    padding_left = 70
    padding_right = 30
    padding_top = 35
    padding_bottom = 50

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
        f'aria-label="Record history">'
    )

    # Background.
    svg.append(
        f'<rect width="{width}" '
        f'height="{height}" '
        f'fill="#090909"/>'
    )

    # Grid.
    for i in range(5):

        y = (
            padding_top
            + graph_height * i / 4
        )

        value = (
            maximum
            - (maximum - minimum) * i / 4
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

    coordinates = []

    count = len(points)

    for i, value in enumerate(points):

        if count == 1:
            x = padding_left + graph_width / 2
        else:
            x = (
                padding_left
                + graph_width * i / (count - 1)
            )

        y = (
            padding_top
            + (
                (maximum - value)
                / (maximum - minimum)
            )
            * graph_height
        )

        coordinates.append(
            (x, y)
        )

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

    for x, y in coordinates:

        svg.append(
            f'<circle '
            f'cx="{x:.1f}" '
            f'cy="{y:.1f}" '
            f'r="4" '
            f'fill="#ffb000" '
            f'stroke="#090909" '
            f'stroke-width="2"/>'
        )

    svg.append("</svg>")

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

    maximum = max(values)

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
        f'aria-label="Player record history">'
    )

    svg.append(
        f'<rect width="{width}" '
        f'height="{height}" '
        f'fill="#090909"/>'
    )

    # Horizontal grid.
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

    coordinates = []

    count = len(values)

    for i, value in enumerate(values):

        if count == 1:
            x = padding_left + graph_width / 2
        else:
            x = (
                padding_left
                + graph_width * i / (count - 1)
            )

        y = (
            padding_top
            + graph_height
            - (
                value / maximum
            ) * graph_height
        )

        coordinates.append(
            (x, y)
        )

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

    for x, y in coordinates:

        svg.append(
            f'<circle '
            f'cx="{x:.1f}" '
            f'cy="{y:.1f}" '
            f'r="4" '
            f'fill="#ffb000"/>'
        )

    svg.append("</svg>")

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

