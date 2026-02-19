"""Database operations, score processing, and shared helpers."""

import os
import re
import sqlite3
import hashlib
import secrets

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE = "judging.db"
DATA_DIR = "data"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

SCORING_COLUMNS = [
    "Presentation Content [Background]",
    "Presentation Content [Originality of idea/purpose to research]",
    "Presentation Content [Appropriateness of methodology/procedure/study design]",
    "Presentation Content [Analysis of results]",
    "Presentation Content [Interpretation of results/conclusion]",
    "Presentation Content [Subject knowledge conveyed]",
    "Presentation Skills [Delivery]",
    "Presentation Skills [Organization of material]",
    "Presentation Skills [Appropriateness of visual aids]",
    "Presentation Skills [Ability to answer questions]",
]

SCORING_SHORT_NAMES = [
    "background",
    "originality",
    "methodology",
    "analysis",
    "interpretation",
    "knowledge",
    "delivery",
    "organization",
    "visual_aids",
    "questions",
]

# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------


def init_db():
    """Create tables if they don't exist."""
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS judges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            judge_id TEXT UNIQUE NOT NULL,
            approved INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            judge_id TEXT NOT NULL,
            student_project_id TEXT NOT NULL,
            background INTEGER NOT NULL,
            originality INTEGER NOT NULL,
            methodology INTEGER NOT NULL,
            analysis INTEGER NOT NULL,
            interpretation INTEGER NOT NULL,
            knowledge INTEGER NOT NULL,
            delivery INTEGER NOT NULL,
            organization INTEGER NOT NULL,
            visual_aids INTEGER NOT NULL,
            questions INTEGER NOT NULL,
            comments TEXT DEFAULT '',
            student_name TEXT DEFAULT '',
            created_at TEXT,
            UNIQUE(judge_id, student_project_id)
        );
        CREATE TABLE IF NOT EXISTS judge_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            judge_id TEXT NOT NULL,
            student_project_id TEXT NOT NULL,
            UNIQUE(judge_id, student_project_id)
        );
    """)
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"


def verify_password(stored, password):
    salt, h = stored.split("$", 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == h


# ---------------------------------------------------------------------------
# Judge ID generation
# ---------------------------------------------------------------------------

def generate_judge_id(first_name, last_name, db):
    """Generate a unique 3-4 letter judge ID from name initials."""
    base = (first_name[0] + last_name[:2]).upper()
    candidate = base
    suffix = 1
    while db.execute("SELECT 1 FROM judges WHERE judge_id = ?", (candidate,)).fetchone():
        candidate = base + str(suffix)
        suffix += 1
    return candidate


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def sanitize_text(value, max_len=200):
    """Strip and truncate text input."""
    return str(value).strip()[:max_len]


def validate_username(username):
    """Username must be 3-50 alphanumeric/underscore chars."""
    return bool(re.match(r'^[a-zA-Z0-9_]{3,50}$', username))


# ---------------------------------------------------------------------------
# Student data helpers (from student_assignments.csv)
# ---------------------------------------------------------------------------

def load_student_projects():
    """Load and return the student_assignments DataFrame with forward-filled categories."""
    path = os.path.join(DATA_DIR, "student_assignments.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    mask = df["ID (project)"].notna()
    df.loc[mask, "Category"] = df.loc[mask, "Category"].ffill()
    df = df[df["ID (project)"].notna()].copy()
    df["ID (project)"] = df["ID (project)"].astype(str).str.strip().str.upper()
    return df


# ---------------------------------------------------------------------------
# Score processing
# ---------------------------------------------------------------------------

def process_scores(db):
    """Process all scores from the database and generate output CSV. Returns the DataFrame."""
    rows = db.execute("SELECT * FROM scores").fetchall()
    if not rows:
        return None

    records = []
    for r in rows:
        record = {
            "Judge ID": r["judge_id"],
            "Student Project ID": r["student_project_id"].strip().upper(),
        }
        for short, full in zip(SCORING_SHORT_NAMES, SCORING_COLUMNS):
            record[full] = r[short]
        record["Other Comments"] = r["comments"]
        record["Student Name"] = r["student_name"]
        records.append(record)

    scores_df = pd.DataFrame(records)

    student_assignments = load_student_projects()
    if student_assignments.empty:
        return None

    merged = scores_df.merge(
        student_assignments[["ID (project)", "Category", "Student First Name",
                             "Student Last Name", "Title of Presentation"]],
        left_on="Student Project ID",
        right_on="ID (project)",
        how="left",
    )
    merged = merged.drop(columns=["ID (project)"])
    merged["Student Project ID"] = merged["Student Project ID"].astype(
        str).str.strip().str.upper()
    merged["Judge ID"] = merged["Judge ID"].astype(str).str.strip().str.upper()

    for col in SCORING_COLUMNS:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")

    results = merged.groupby(["Student Project ID"]).agg(
        {
            **{col: "mean" for col in SCORING_COLUMNS},
            "Judge ID": lambda x: ",".join(sorted(set(x.astype(str)))),
            "Student First Name": "first",
            "Student Last Name": "first",
            "Category": "first",
            "Title of Presentation": "first",
        }
    ).reset_index()

    results = results.rename(columns={"Judge ID": "Judges Had"})
    results["Judges Num"] = results["Judges Had"].apply(
        lambda x: len(x.split(",")) if pd.notna(x) else 0
    )
    results["Average Total Score"] = sum(
        results[col] for col in SCORING_COLUMNS)
    results["Average Total Score"] = results["Average Total Score"].round(3)
    results["Student Name"] = results["Student First Name"] + \
        " " + results["Student Last Name"]

    final_cols = [
        "Category", "Student Project ID", "Student Name",
        "Title of Presentation", "Average Total Score", "Judges Num", "Judges Had",
    ]
    final_df = results[final_cols].copy()
    final_df = final_df.sort_values(
        by=["Category", "Average Total Score"], ascending=[True, False]
    )

    # Add assigned judges column from judge_assignments table
    def resolve_assigned(pid):
        assigned_rows = db.execute(
            "SELECT judge_id FROM judge_assignments WHERE student_project_id = ?",
            (pid,),
        ).fetchall()
        return ",".join(sorted(r["judge_id"].upper() for r in assigned_rows))

    final_df["Assigned Judges"] = final_df["Student Project ID"].apply(
        resolve_assigned)

    final_df.to_csv(os.path.join(DATA_DIR, "output.csv"), index=False)
    return final_df


def verify_validity(final_df, db):
    """Run validity checks using DB assignments."""
    issues = []
    for _, row in final_df.iterrows():
        pid = row["Student Project ID"]
        judges_had = [j.strip()
                      for j in str(row["Judges Had"]).split(",") if j.strip()]
        unique_had = set(judges_had)

        if len(unique_had) != row["Judges Num"]:
            issues.append(f"Duplicate judge entries for {pid}: {judges_had}")

        assigned_rows = db.execute(
            "SELECT judge_id FROM judge_assignments WHERE student_project_id = ?",
            (pid,),
        ).fetchall()
        assigned_ids = [r["judge_id"].upper() for r in assigned_rows]

        for jid in unique_had:
            if assigned_ids and jid not in assigned_ids:
                issues.append(
                    f"Judge {jid} scored {pid} but not in assigned list {assigned_ids}")

        if assigned_ids and len(unique_had) < len(assigned_ids):
            issues.append(
                f"{pid}: has {len(unique_had)} judges, expected {len(assigned_ids)}")

    return issues
