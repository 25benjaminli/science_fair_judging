import os
import hmac
import sqlite3
import secrets
from functools import wraps
from datetime import datetime, timezone

import pandas as pd
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, jsonify, send_file, abort
)

from utils import (
    DATABASE, DATA_DIR, ADMIN_PASSWORD,
    SCORING_COLUMNS, SCORING_SHORT_NAMES,
    init_db, hash_password, verify_password, generate_judge_id,
    sanitize_text, validate_username, load_student_projects,
    process_scores, verify_validity,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "FLASK_ENV") == "production"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.before_request
def csrf_protect():
    """Verify CSRF token on all POST requests."""
    if request.method == "POST":
        token = session.get("csrf_token", None)
        form_token = request.form.get("csrf_token", None)
        if not token or not form_token or not hmac.compare_digest(token, form_token):
            abort(403)


@app.before_request
def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "judge_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin access required.", "danger")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes – Public
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes – Judge signup / login
# ---------------------------------------------------------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = sanitize_text(request.form.get("username", ""), 50)
        password = request.form.get("password", "").strip()
        first_name = sanitize_text(request.form.get("first_name", ""), 50)
        last_name = sanitize_text(request.form.get("last_name", ""), 50)

        if not all([username, password, first_name, last_name]):
            flash("All fields are required.", "danger")
            return redirect(url_for("signup"))

        if not validate_username(username):
            flash(
                "Username must be 3-50 characters (letters, numbers, underscore only).", "danger")
            return redirect(url_for("signup"))

        if len(password) < 4:
            flash("Password must be at least 4 characters.", "danger")
            return redirect(url_for("signup"))

        db = get_db()
        if db.execute("SELECT 1 FROM judges WHERE username = ?", (username,)).fetchone():
            flash("Username already taken.", "danger")
            return redirect(url_for("signup"))

        judge_id = generate_judge_id(first_name, last_name, db)
        db.execute(
            "INSERT INTO judges (username, password_hash, first_name, last_name, judge_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, hash_password(password), first_name,
             last_name, judge_id, (str(datetime.now(timezone.utc)) + ' UTC')),
        )
        db.commit()
        flash(
            "Account created! Please wait for admin approval before logging in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = sanitize_text(request.form.get("username", ""), 50)
        password = request.form.get("password", "").strip()
        db = get_db()
        judge = db.execute(
            "SELECT * FROM judges WHERE username = ?", (username,)).fetchone()
        if judge and verify_password(judge["password_hash"], password):
            if not judge["approved"]:
                flash("Your account is pending admin approval.", "warning")
                return redirect(url_for("login"))
            session["judge_id"] = judge["judge_id"]
            session["judge_db_id"] = judge["id"]
            session["judge_name"] = f"{judge['first_name']} {judge['last_name']}"
            return redirect(url_for("judge_dashboard"))
        flash("Invalid username or password.", "danger")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes – Judge dashboard & scoring
# ---------------------------------------------------------------------------

@app.route("/judge")
@login_required
def judge_dashboard():
    db = get_db()
    judge = db.execute("SELECT * FROM judges WHERE judge_id = ?",
                       (session["judge_id"],)).fetchone()

    # Get projects this judge has already scored
    scored = db.execute(
        "SELECT student_project_id FROM scores WHERE judge_id = ?",
        (session["judge_id"],),
    ).fetchall()
    scored_ids = {r["student_project_id"] for r in scored}

    # Get only assigned projects for this judge
    assigned = db.execute(
        "SELECT student_project_id FROM judge_assignments WHERE judge_id = ?",
        (session["judge_id"],),
    ).fetchall()
    assigned_ids = {r["student_project_id"] for r in assigned}

    student_assignments = load_student_projects()
    projects = []
    if not student_assignments.empty:
        for _, row in student_assignments.iterrows():
            pid = row["ID (project)"]
            if pid not in assigned_ids:
                continue
            # ! If you want more fields, add them here and update the html accordingly
            projects.append({
                "id": pid,
                "student_name": f"{row.get('Student First Name', '')} {row.get('Student Last Name', '')}",
                "category": row.get("Category", ""),
                "title": row.get("Title of Presentation", ""),
                "scored": pid in scored_ids,
            })

    return render_template("judge_dashboard.html", judge=judge, projects=projects, scored_ids=scored_ids)


@app.route("/judge/score/<project_id>", methods=["GET", "POST"])
@login_required
def score_project(project_id):
    project_id = project_id.strip().upper()
    db = get_db()

    student_assignments = load_student_projects()
    project_row = student_assignments[student_assignments["ID (project)"]
                                      == project_id]
    if project_row.empty:
        flash("Project not found.", "danger")
        return redirect(url_for("judge_dashboard"))

    project_info = project_row.iloc[0]

    # Check that this judge is assigned to this project
    assigned = db.execute(
        "SELECT 1 FROM judge_assignments WHERE judge_id = ? AND student_project_id = ?",
        (session["judge_id"], project_id),
    ).fetchone()
    if not assigned:
        flash("You are not assigned to this project.", "danger")
        return redirect(url_for("judge_dashboard"))

    # Check for existing score — block re-scoring
    existing = db.execute(
        "SELECT * FROM scores WHERE judge_id = ? AND student_project_id = ?",
        (session["judge_id"], project_id),
    ).fetchone()
    if existing:
        flash("You have already scored this project.", "warning")
        return redirect(url_for("judge_dashboard"))

    if request.method == "POST":
        values = {}
        for short in SCORING_SHORT_NAMES:
            val = request.form.get(short, "")
            try:
                val = int(val)
                if val < 1 or val > 10:
                    raise ValueError
            except ValueError:
                flash(f"Invalid score for {short}. Must be 1-10.", "danger")
                return redirect(url_for("score_project", project_id=project_id))
            values[short] = val

        comments = sanitize_text(request.form.get("comments", ""), 500)
        student_name = f"{project_info.get('Student First Name', '')} {project_info.get('Student Last Name', '')}"

        db.execute(
            f"""INSERT INTO scores (judge_id, student_project_id,
                {', '.join(SCORING_SHORT_NAMES)}, comments, student_name)
            VALUES (?, ?, {', '.join('?' for _ in SCORING_SHORT_NAMES)}, ?, ?)""",
            [session["judge_id"], project_id] + [values[k]
                                                 for k in SCORING_SHORT_NAMES] + [comments, student_name],
        )
        db.commit()
        flash(f"Score submitted for {project_id}.", "success")
        return redirect(url_for("judge_dashboard"))

    return render_template(
        "score_form.html",
        project_id=project_id,
        project_info=project_info,
        scoring_fields=list(zip(SCORING_SHORT_NAMES, SCORING_COLUMNS)),
    )


# ---------------------------------------------------------------------------
# Routes – Admin
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form["password"] and hmac.compare_digest(
            request.form["password"], ADMIN_PASSWORD
        ):
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin password.", "danger")
    return render_template("admin_login.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    pending = db.execute(
        "SELECT * FROM judges WHERE approved = 0 ORDER BY created_at DESC").fetchall()
    approved_raw = db.execute(
        "SELECT * FROM judges WHERE approved = 1 ORDER BY last_name, first_name").fetchall()

    # Add assignment counts for each approved judge
    approved = []
    for j in approved_raw:
        count = db.execute(
            "SELECT COUNT(*) as cnt FROM judge_assignments WHERE judge_id = ?",
            (j["judge_id"],),
        ).fetchone()["cnt"]
        approved.append({**dict(j), "assignment_count": count})

    total_scores = db.execute(
        "SELECT COUNT(*) as cnt FROM scores").fetchone()["cnt"]
    total_judges = db.execute(
        "SELECT COUNT(*) as cnt FROM judges WHERE approved = 1").fetchone()["cnt"]

    return render_template(
        "admin_dashboard.html",
        pending=pending,
        approved=approved,
        total_scores=total_scores,
        total_judges=total_judges,
    )


@app.route("/admin/approve/<int:judge_db_id>", methods=["POST"])
@admin_required
def approve_judge(judge_db_id):
    db = get_db()
    db.execute("UPDATE judges SET approved = 1 WHERE id = ?", (judge_db_id,))
    db.commit()
    flash("Judge approved.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reject/<int:judge_db_id>", methods=["POST"])
@admin_required
def reject_judge(judge_db_id):
    db = get_db()
    db.execute("DELETE FROM judges WHERE id = ? AND approved = 0", (judge_db_id,))
    db.commit()
    flash("Judge rejected and removed.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/assign/<int:judge_db_id>", methods=["GET", "POST"])
@admin_required
def admin_assign_judge(judge_db_id):
    db = get_db()
    judge = db.execute(
        "SELECT * FROM judges WHERE id = ? AND approved = 1", (judge_db_id,)).fetchone()
    if not judge:
        flash("Judge not found or not approved.", "danger")
        return redirect(url_for("admin_dashboard"))

    student_assignments = load_student_projects()

    if request.method == "POST":
        selected = request.form.getlist("projects")
        selected = [pid.strip().upper() for pid in selected]

        # Clear existing assignments and re-insert
        db.execute("DELETE FROM judge_assignments WHERE judge_id = ?",
                   (judge["judge_id"],))
        for pid in selected:
            db.execute(
                "INSERT OR IGNORE INTO judge_assignments (judge_id, student_project_id) VALUES (?, ?)",
                (judge["judge_id"], pid),
            )
        db.commit()
        flash(
            f"Assigned {len(selected)} project(s) to {judge['first_name']} {judge['last_name']}.", "success")
        return redirect(url_for("admin_dashboard"))

    # Get current assignments
    current = db.execute(
        "SELECT student_project_id FROM judge_assignments WHERE judge_id = ?",
        (judge["judge_id"],),
    ).fetchall()
    assigned_ids = {r["student_project_id"] for r in current}

    # Build project list grouped by category
    categories = {}
    if not student_assignments.empty:
        for _, row in student_assignments.iterrows():
            cat = row.get("Category", "Uncategorized")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append({
                "id": row["ID (project)"],
                "student_name": f"{row.get('Student First Name', '')} {row.get('Student Last Name', '')}",
                "title": row.get("Title of Presentation", ""),
                "assigned": row["ID (project)"] in assigned_ids,
            })

    return render_template(
        "admin_assign.html",
        judge=judge,
        categories=categories,
        assigned_ids=assigned_ids,
    )


@app.route("/admin/assign_category/<int:judge_db_id>/<path:category>", methods=["POST"])
@admin_required
def admin_assign_category(judge_db_id, category):
    """Quick-assign all projects in a category to a judge."""
    db = get_db()
    judge = db.execute(
        "SELECT * FROM judges WHERE id = ? AND approved = 1", (judge_db_id,)).fetchone()
    if not judge:
        flash("Judge not found or not approved.", "danger")
        return redirect(url_for("admin_dashboard"))

    student_assignments = load_student_projects()
    cat_projects = student_assignments[student_assignments["Category"] == category]
    count = 0
    for _, row in cat_projects.iterrows():
        pid = row["ID (project)"]
        db.execute(
            "INSERT OR IGNORE INTO judge_assignments (judge_id, student_project_id) VALUES (?, ?)",
            (judge["judge_id"], pid),
        )
        count += 1
    db.commit()
    flash(
        f"Assigned {count} project(s) in '{category}' to {judge['first_name']} {judge['last_name']}.", "success")
    return redirect(url_for("admin_assign_judge", judge_db_id=judge_db_id))


@app.route("/admin/process", methods=["POST"])
@admin_required
def admin_process():
    db = get_db()
    final_df = process_scores(db)
    if final_df is None or final_df.empty:
        flash("No scores to process.", "warning")
        return redirect(url_for("admin_results"))

    issues = verify_validity(final_df, db)
    if issues:
        for issue in issues:
            flash(issue, "warning")
    else:
        flash("All validity checks passed!", "success")

    flash(f"Processed {len(final_df)} projects.", "success")
    return redirect(url_for("admin_results"))


@app.route("/admin/results")
@admin_required
def admin_results():
    output_path = os.path.join(DATA_DIR, "output.csv")
    categories = {}
    if os.path.exists(output_path):
        df = pd.read_csv(output_path)
        for cat in sorted(df["Category"].dropna().unique()):
            categories[cat] = df[df["Category"] == cat].to_dict("records")

    return render_template("admin_results.html", categories=categories)


@app.route("/admin/download")
@admin_required
def admin_download():
    output_path = os.path.join(DATA_DIR, "output.csv")
    if os.path.exists(output_path):
        return send_file(output_path, as_attachment=True, download_name="aggregated_scores.csv")
    flash("No output file found. Process scores first.", "warning")
    return redirect(url_for("admin_results"))


@app.route("/admin/scores")
@admin_required
def admin_view_scores():
    db = get_db()
    scores = db.execute("""
        SELECT s.*, j.first_name, j.last_name
        FROM scores s
        JOIN judges j ON s.judge_id = j.judge_id
        ORDER BY s.created_at DESC
    """).fetchall()
    return render_template("admin_scores.html", scores=scores, scoring_names=SCORING_SHORT_NAMES)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "info")
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------------------
# Init & Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(debug=debug, port=5000)
