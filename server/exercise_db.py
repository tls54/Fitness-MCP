"""Lookup functions against exercises.db (built by build_exercise_db.py)."""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "exercises.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["equipment"] = d["equipment"].split(",") if d["equipment"] else []
    d["primary_muscles"] = d["primary_muscles"].split(",") if d["primary_muscles"] else []
    d["secondary_muscles"] = d["secondary_muscles"].split(",") if d["secondary_muscles"] else []
    return d


def fuzzy_search(query: str, limit: int = 10) -> list[dict]:
    """Free-text search for an exercise name, e.g. 'cable fly' or 'goblet squat'.

    Uses SQLite FTS5 (bm25-ranked) over exercise names, falling back to a plain
    substring LIKE search if FTS finds nothing (FTS5 tokenizes on word boundaries,
    so single-token typos or unusual phrasing can miss).
    """
    conn = _connect()
    try:
        fts_query = " ".join(f'"{w}"*' for w in query.split())
        rows = conn.execute(
            """
            SELECT e.* FROM exercises e
            JOIN exercises_fts f ON f.rowid = e.id
            WHERE exercises_fts MATCH ?
            ORDER BY bm25(exercises_fts)
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        if rows:
            return [_row_to_dict(r) for r in rows]

        rows = conn.execute(
            "SELECT * FROM exercises WHERE name LIKE ? ORDER BY length(name) LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def browse_category(category: str, limit: int = 50) -> list[dict]:
    """List all exercises in a given category (case-insensitive, exact category name)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM exercises WHERE lower(category) = lower(?) ORDER BY name LIMIT ?",
            (category, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def filter_by(equipment: list[str] | None = None, muscles: list[str] | None = None, limit: int = 50) -> list[dict]:
    """Filter exercises by any combination of equipment tags and target muscles (primary or secondary).

    equipment: e.g. ["band"] - matches if the exercise's equipment list contains ANY of these.
    muscles: e.g. ["CALVES", "ABDUCTORS"] - matches if primary OR secondary muscles contain ANY of these.
    Both filters are ANY-of-list (OR) within themselves, ANDed together across the two filters.
    """
    conn = _connect()
    try:
        clauses = []
        params: list[str] = []

        if equipment:
            clauses.append(
                "(" + " OR ".join("(',' || equipment || ',') LIKE ?" for _ in equipment) + ")"
            )
            params.extend(f"%,{e},%" for e in equipment)

        if muscles:
            clauses.append(
                "("
                + " OR ".join(
                    "(',' || primary_muscles || ',') LIKE ? OR (',' || secondary_muscles || ',') LIKE ?"
                    for _ in muscles
                )
                + ")"
            )
            for m in muscles:
                params.extend([f"%,{m},%", f"%,{m},%"])

        where = " AND ".join(clauses) if clauses else "1=1"
        rows = conn.execute(f"SELECT * FROM exercises WHERE {where} ORDER BY name LIMIT ?", (*params, limit)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_garmin_enums(name: str, category: str | None = None) -> dict | None:
    """Best single match for an exercise name (optionally narrowed by category), with its
    enum_confidence ('confirmed' | 'guessed' | 'todo') and category/name enum values
    (name enum may be None if confidence is 'todo').
    """
    conn = _connect()
    try:
        if category:
            row = conn.execute(
                "SELECT * FROM exercises WHERE lower(name) = lower(?) AND lower(category) = lower(?) LIMIT 1",
                (name, category),
            ).fetchone()
            if row:
                return _row_to_dict(row)

        # Multiple rows can share a name across categories (e.g. "Squat" appears under both
        # "Squat" and "Banded Exercises"); prefer the best-confidence match, not just the
        # first row SQLite happens to return, so the one confirmed/guessed enum wins over
        # an unrelated 'todo' duplicate.
        row = conn.execute(
            """
            SELECT * FROM exercises WHERE lower(name) = lower(?)
            ORDER BY CASE enum_confidence WHEN 'confirmed' THEN 0 WHEN 'guessed' THEN 1 ELSE 2 END
            LIMIT 1
            """,
            (name,),
        ).fetchone()
        if row:
            return _row_to_dict(row)

        matches = fuzzy_search(name, limit=1)
        return matches[0] if matches else None
    finally:
        conn.close()
