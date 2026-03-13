"""Database operations, score processing, and shared helpers."""

import os
import re
import hashlib
import secrets

import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

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

def init_db():
    """Initialize Firebase Admin SDK."""
    if not firebase_admin._apps:
        cred = credentials.Certificate("credentials.json")
        firebase_admin.initialize_app(cred)
    return firestore.client()


def get_db():
    return firestore.client()


def generate_judge_id(first_name, last_name, db):
    base = (first_name[0] + last_name[:2]).upper()
    candidate = base
    suffix = 1
    judges_ref = db.collection('judges')
    # keep appending numbers until found unused ID
    while True:
        docs = judges_ref.where('judge_id', '==', candidate).limit(1).get()
        if not docs:
            break
        candidate = base + str(suffix)
        suffix += 1
    return candidate


def sanitize_text(value, max_len=200):
    """Strip and truncate text input."""
    return str(value).strip()[:max_len]

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

def process_scores(db):
    """Process all scores from the database and generate output CSV. Returns the DataFrame."""
    docs = db.collection('scores').get()
    if not docs:
        return None

    records = []
    for doc in docs:
        r = doc.to_dict()
        record = {
            "Judge ID": r.get("judge_id"),
            "Student Project ID": r.get("student_project_id", "").strip().upper(),
        }
        for short, full in zip(SCORING_SHORT_NAMES, SCORING_COLUMNS):
            record[full] = r.get(short, 0)
        record["Other Comments"] = r.get("comments", "")
        record["Student Name"] = r.get("student_name", "")
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
        assigned_docs = db.collection('judge_assignments').where('student_project_id', '==', pid).get()
        return ",".join(sorted(doc.to_dict().get("judge_id", "").upper() for doc in assigned_docs))

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

        assigned_docs = db.collection('judge_assignments').where('student_project_id', '==', pid).get()
        assigned_ids = [doc.to_dict().get("judge_id", "").upper() for doc in assigned_docs]

        for jid in unique_had:
            if assigned_ids and jid not in assigned_ids:
                issues.append(
                    f"Judge {jid} scored {pid} but not in assigned list {assigned_ids}")

        if assigned_ids and len(unique_had) < len(assigned_ids):
            issues.append(
                f"{pid}: has {len(unique_had)} judges, expected {len(assigned_ids)}")

    return issues
