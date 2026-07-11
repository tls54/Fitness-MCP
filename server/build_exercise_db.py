#!/usr/bin/env python3
"""Build exercises.db from the community-maintained Garmin Connect exercise list.

Source: https://github.com/mrnabilnoh/workout-plan-garmin-connect/blob/main/garmin_connect_exercise_list.md
(~1,500 row markdown table of exercise name / category / primary+secondary muscles,
using an emoji legend for muscle groups and equipment).

This script parses that table and computes a *candidate* Garmin FIT enum for each
row's category (garmin_category_enum) by uppercasing/underscoring the category text -
a transform confirmed correct for at least one category ("Squat" -> "SQUAT") via a live
round-trip upload (see probe_strength_roundtrip.py). Per-exercise name enums
(garmin_name_enum) are NOT guessed for every row: Garmin's real per-category exercise
name enums (e.g. "GOBLET_SQUAT" vs "SQUAT") aren't derivable from this source with
confidence, so they're only populated for the small "confident" set below (rows whose
exercise name textually matches its own category, by analogy with the confirmed squat
case) or the manually reviewed list of Theo's routine exercises. Everything else is left
NULL with confidence='todo' rather than guessing an enum that could silently fail upload.

Usage:
    cd server
    python3 build_exercise_db.py
"""

import re
import sqlite3
import urllib.request

SOURCE_URL = "https://raw.githubusercontent.com/mrnabilnoh/workout-plan-garmin-connect/main/garmin_connect_exercise_list.md"
DB_PATH = "exercises.db"

# (garmin_category_enum, garmin_name_enum) pairs read back from a workout Theo built using
# Garmin Connect's own exercise picker (via garmin_get_workout_by_id) - these are real,
# device-confirmed enum values, not guesses. Applied as a post-build confirmation pass so
# rebuilding exercises.db from the source markdown doesn't silently lose them.
CONFIRMED_SEED_PATH = "confirmed_exercises_seed.json"

MUSCLE_EMOJI_LEGEND = {
    "🦵": ["QUADS", "HAMSTRINGS", "ADDUCTORS", "ABDUCTORS", "HIPS"],
    "🍑": ["GLUTES"],
    "💪": ["BICEPS", "TRICEPS"],
    "🏋️": ["SHOULDERS", "CHEST"],
    "🧘": ["ABS", "OBLIQUES"],
    "🔙": ["LOWER_BACK"],
    "🦾": ["LATS", "TRAPS"],
    "✋": ["FOREARM"],
    "🦶": ["CALVES"],
}

EQUIPMENT_EMOJI_LEGEND = {
    "🏋️": ["barbell", "dumbbell", "kettlebell", "plate"],
    "🚴": ["bike", "elliptical"],
    "🟦": ["band"],
    "⚽": ["swiss_ball"],
    "🪑": ["bench"],
    "🪢": ["rope"],
    "🚣": ["row_machine"],
    "🔗": ["cable"],
    "🤸": ["bodyweight"],
    "🛠️": ["machine"],
}

# Reviewed against Theo's actual routine (leg press, cable fly, calf raises, rows,
# banded ankle/hip work, glute/hip stability work, plyo, general dumbbell work) - but
# NONE of those have a name that equals their own category in this dataset (e.g. "Leg
# Press" is filed under category "Squat", not its own category), so none can honestly
# be guessed by the same pattern that confirmed "Squat". Left empty on purpose rather
# than fabricate enum strings - see enum_confidence='todo' rows for all of them.
MANUAL_NAME_ENUM_OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {}


def strip_leading_emoji(cell: str) -> tuple[str, list[str]]:
    """Split a table cell into (clean_text, [equipment tags from any leading emoji])."""
    cell = cell.strip()
    equipment: list[str] = []
    changed = True
    while changed:
        changed = False
        for emoji, tags in EQUIPMENT_EMOJI_LEGEND.items():
            if cell.startswith(emoji):
                equipment.extend(t for t in tags if t not in equipment)
                cell = cell[len(emoji):].strip()
                changed = True
    return cell, equipment


def parse_muscle_cell(cell: str) -> list[str]:
    """'🦵 QUADS<br>🍑 GLUTES' -> ['QUADS', 'GLUTES']. Emoji is redundant with the text."""
    out = []
    for part in cell.split("<br>"):
        part = part.strip()
        for emoji in MUSCLE_EMOJI_LEGEND:
            part = part.replace(emoji, "")
        part = part.strip()
        if part:
            out.append(part)
    return out


def to_enum_case(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text.strip())
    text = text.strip("_").upper()
    # Garmin prefixes enum identifiers that would otherwise start with a digit with an
    # underscore (e.g. "3 Way Calf Raise" -> "_3_WAY_CALF_RAISE") - confirmed by reading
    # back a workout built via Garmin Connect's own exercise picker.
    if text and text[0].isdigit():
        text = "_" + text
    return text


def fetch_markdown() -> str:
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_table(markdown: str) -> list[dict]:
    rows = []
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("| Exercise "):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            continue
        if set(line.replace("|", "").strip()) <= set("- "):
            continue  # the |---|---|---|---| separator row

        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        raw_name, raw_category, raw_primary, raw_secondary = cells

        name, name_equipment = strip_leading_emoji(raw_name)
        category, category_equipment = strip_leading_emoji(raw_category)
        equipment = category_equipment + [e for e in name_equipment if e not in category_equipment]

        rows.append(
            {
                "name": name,
                "category": category,
                "equipment": equipment,
                "primary_muscles": parse_muscle_cell(raw_primary),
                "secondary_muscles": parse_muscle_cell(raw_secondary),
            }
        )
    return rows


def apply_confirmed_seed(conn: sqlite3.Connection) -> None:
    """Apply CONFIRMED_SEED_PATH's (category_enum, name_enum) pairs on top of the freshly
    built table, matching each pair back to a row by recomputing its own name/category enum
    and comparing. A blank name_enum in the seed means "generic category, no specific
    exercise" - matched to the self-referential row (name == category) if one exists.
    """
    import os

    if not os.path.exists(CONFIRMED_SEED_PATH):
        return

    with open(CONFIRMED_SEED_PATH) as f:
        pairs = json.load(f)

    rows = conn.execute("SELECT id, name, category, garmin_category_enum FROM exercises").fetchall()
    by_category: dict[str, list] = {}
    for r in rows:
        by_category.setdefault(r[3], []).append(r)

    matched, unmatched = 0, []
    for category_enum, name_enum in pairs:
        candidates = by_category.get(category_enum, [])
        target = category_enum if name_enum == "" else name_enum
        hit = next((r for r in candidates if to_enum_case(r[1]) == target), None)
        if hit:
            conn.execute(
                "UPDATE exercises SET garmin_category_enum=?, garmin_name_enum=?, enum_confidence='confirmed' WHERE id=?",
                (category_enum, name_enum or category_enum, hit[0]),
            )
            matched += 1
        else:
            unmatched.append((category_enum, name_enum))
    conn.commit()

    print(f"Applied confirmed seed: {matched}/{len(pairs)} matched")
    for u in unmatched:
        print(f"  unmatched (generic category, no catalog row to attach to): {u}")


def build_db(rows: list[dict]) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS exercises_fts")
    conn.execute("DROP TABLE IF EXISTS exercises")
    conn.execute(
        """
        CREATE TABLE exercises (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            garmin_category_enum TEXT,
            garmin_name_enum TEXT,
            enum_confidence TEXT NOT NULL,  -- 'confirmed' | 'guessed' | 'todo'
            equipment TEXT,                 -- comma-separated
            primary_muscles TEXT,           -- comma-separated
            secondary_muscles TEXT          -- comma-separated
        )
        """
    )
    conn.execute("CREATE VIRTUAL TABLE exercises_fts USING fts5(name, content='exercises', content_rowid='id')")

    for row in rows:
        name_key = (row["name"].lower(), row["category"].lower())
        category_enum = to_enum_case(row["category"])

        if row["name"].lower() == "squat" and row["category"].lower() == "squat":
            name_enum, confidence = "SQUAT", "confirmed"
        elif name_key in MANUAL_NAME_ENUM_OVERRIDES:
            _, override_name_enum, confidence = MANUAL_NAME_ENUM_OVERRIDES[name_key]
            name_enum = override_name_enum
        elif row["name"].lower() == row["category"].lower():
            # Same pattern as the confirmed squat case (bare exercise name == category) -
            # reasonable to guess name_enum == category_enum, but not live-tested.
            name_enum, confidence = category_enum, "guessed"
        else:
            name_enum, confidence = None, "todo"

        conn.execute(
            """INSERT INTO exercises
               (name, category, garmin_category_enum, garmin_name_enum, enum_confidence,
                equipment, primary_muscles, secondary_muscles)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["name"],
                row["category"],
                category_enum,
                name_enum,
                confidence,
                ",".join(row["equipment"]),
                ",".join(row["primary_muscles"]),
                ",".join(row["secondary_muscles"]),
            ),
        )

    conn.execute("INSERT INTO exercises_fts (rowid, name) SELECT id, name FROM exercises")
    conn.commit()
    apply_confirmed_seed(conn)

    total = conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    by_confidence = conn.execute(
        "SELECT enum_confidence, COUNT(*) FROM exercises GROUP BY enum_confidence"
    ).fetchall()
    conn.close()

    print(f"Built {DB_PATH}: {total} exercises")
    for confidence, count in by_confidence:
        print(f"  {confidence}: {count}")


if __name__ == "__main__":
    print(f"Fetching {SOURCE_URL} ...")
    md = fetch_markdown()
    parsed_rows = parse_table(md)
    print(f"Parsed {len(parsed_rows)} rows")
    build_db(parsed_rows)
