import os
import hmac
import secrets
from functools import wraps
from datetime import datetime, timezone

import pandas as pd
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, jsonify, send_file, abort
)
from authlib.integrations.flask_client import OAuth

from utils import (
    DATA_DIR, ADMIN_PASSWORD,
    SCORING_COLUMNS, SCORING_SHORT_NAMES,
    init_db, get_db, generate_judge_id,
    sanitize_text, load_student_projects,
    process_scores, verify_validity,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "FLASK_ENV") == "production"

init_db()

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

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

# LOGIN / SIGNUP STUFF

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login")
def login():
    # Only initiate OAuth flow if the user explicitly clicked "Sign in with Google"
    # Otherwise render the judge login page with the Google button
    if request.args.get('provider') == 'google':
        redirect_uri = url_for("auth_callback", _external=True)
        return google.authorize_redirect(redirect_uri)
    return render_template("login.html")


@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    user_info = token.get("userinfo")
    if not user_info:
        flash("Failed to get user info from Google.", "danger")
        return redirect(url_for("index"))

    email = user_info.get("email")
    first_name = user_info.get("given_name", "")
    last_name = user_info.get("family_name", "")

    db = get_db()
    users_ref = db.collection('judges')
    docs = users_ref.where('email', '==', email).limit(1).get()

    if docs:
        judge_doc = docs[0]
        judge = judge_doc.to_dict()
        if not judge.get("approved"):
            flash("Your account is pending admin approval.", "warning")
            return render_template("login.html") # Render base template instead of redirect loop
        
        session["judge_id"] = judge["judge_id"]
        session["judge_db_id"] = judge_doc.id
        session["judge_name"] = f"{judge['first_name']} {judge['last_name']}"
        return redirect(url_for("judge_dashboard"))
    else:
        # Create user
        judge_id = generate_judge_id(first_name, last_name, db)
        users_ref.add({
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
            'judge_id': judge_id,
            'approved': 0,
            'created_at': str(datetime.now(timezone.utc)) + ' UTC'
        })
        flash("Account created! Please wait for admin approval before logging in.", "success")
        return render_template("login.html")

@app.route("/signup")
def signup():
    # Treat signup the same as login for OAuth
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# JUDGING STUFF

@app.route("/judge")
@login_required
def judge_dashboard():
    db = get_db()
    
    judge_docs = db.collection('judges').where('judge_id', '==', session["judge_id"]).limit(1).get()
    judge = judge_docs[0].to_dict() if judge_docs else {}

    # Get projects this judge has already scored
    scored_docs = db.collection('scores').where('judge_id', '==', session["judge_id"]).get()
    scored_ids = {d.to_dict().get("student_project_id") for d in scored_docs}

    # Get only assigned projects for this judge
    assigned_docs = db.collection('judge_assignments').where('judge_id', '==', session["judge_id"]).get()
    assigned_ids = {d.to_dict().get("student_project_id") for d in assigned_docs}

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
    assigned = db.collection('judge_assignments').where('judge_id', '==', session["judge_id"]).where('student_project_id', '==', project_id).limit(1).get()
    if not assigned:
        flash("You are not assigned to this project.", "danger")
        return redirect(url_for("judge_dashboard"))

    # Check for existing score — block re-scoring
    existing = db.collection('scores').where('judge_id', '==', session["judge_id"]).where('student_project_id', '==', project_id).limit(1).get()
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

        score_data = {
            "judge_id": session["judge_id"],
            "student_project_id": project_id,
            "comments": comments,
            "student_name": student_name,
            "created_at": str(datetime.now(timezone.utc)) + ' UTC'
        }
        score_data.update(values)
        
        db.collection('scores').add(score_data)
        
        flash(f"Score submitted for {project_id}.", "success")
        return redirect(url_for("judge_dashboard"))

    return render_template(
        "score_form.html",
        project_id=project_id,
        project_info=project_info,
        scoring_fields=list(zip(SCORING_SHORT_NAMES, SCORING_COLUMNS)),
    )

# ADMIN STUFF

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
    
    # Get all judges
    judges_docs = db.collection('judges').get()
    judges = [{"id": d.id, **d.to_dict()} for d in judges_docs]
    
    pending = [j for j in judges if not j.get("approved")]
    # Sort pending by created_at DESC
    pending.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    approved_raw = [j for j in judges if j.get("approved")]
    # Sort approved by last_name, first_name
    approved_raw.sort(key=lambda x: (x.get("last_name", "").lower(), x.get("first_name", "").lower()))

    # Add assignment counts for each approved judge
    assignments_docs = db.collection('judge_assignments').get()
    assignment_counts = {}
    for doc in assignments_docs:
        jid = doc.to_dict().get("judge_id")
        assignment_counts[jid] = assignment_counts.get(jid, 0) + 1
        
    approved = []
    for j in approved_raw:
        count = assignment_counts.get(j.get("judge_id"), 0)
        approved.append({**j, "assignment_count": count})

    scores_docs = db.collection('scores').get()
    total_scores = len(scores_docs)
    total_judges = len(approved_raw)

    return render_template(
        "admin_dashboard.html",
        pending=pending,
        approved=approved,
        total_scores=total_scores,
        total_judges=total_judges,
    )


@app.route("/admin/approve/<judge_db_id>", methods=["POST"])
@admin_required
def approve_judge(judge_db_id):
    db = get_db()
    db.collection('judges').document(judge_db_id).update({'approved': 1})
    flash("Judge approved.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reject/<judge_db_id>", methods=["POST"])
@admin_required
def reject_judge(judge_db_id):
    db = get_db()
    
    judge_doc = db.collection('judges').document(judge_db_id).get()
    if judge_doc.exists and not judge_doc.to_dict().get("approved"):
        db.collection('judges').document(judge_db_id).delete()
        flash("Judge rejected and removed.", "info")
    else:
        flash("Judge could not be rejected.", "warning")
        
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/assign/<judge_db_id>", methods=["GET", "POST"])
@admin_required
def admin_assign_judge(judge_db_id):
    db = get_db()
    judge_doc = db.collection('judges').document(judge_db_id).get()
    if not judge_doc.exists or not judge_doc.to_dict().get("approved"):
        flash("Judge not found or not approved.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    judge = judge_doc.to_dict()
    judge["id"] = judge_doc.id

    student_assignments = load_student_projects()

    if request.method == "POST":
        selected = request.form.getlist("projects")
        selected = [pid.strip().upper() for pid in selected]

        # Clear existing assignments and re-insert
        existing_assignments = db.collection('judge_assignments').where('judge_id', '==', judge["judge_id"]).get()
        for doc in existing_assignments:
            doc.reference.delete()
            
        for pid in selected:
            db.collection('judge_assignments').add({
                'judge_id': judge["judge_id"],
                'student_project_id': pid
            })
            
        flash(f"Assigned {len(selected)} project(s) to {judge['first_name']} {judge['last_name']}.", "success")
        return redirect(url_for("admin_dashboard"))

    # Get current assignments
    current = db.collection('judge_assignments').where('judge_id', '==', judge["judge_id"]).get()
    assigned_ids = {doc.to_dict().get("student_project_id") for doc in current}

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


@app.route("/admin/assign_category/<judge_db_id>/<path:category>", methods=["POST"])
@admin_required
def admin_assign_category(judge_db_id, category):
    """Quick-assign all projects in a category to a judge."""
    db = get_db()
    judge_doc = db.collection('judges').document(judge_db_id).get()
    if not judge_doc.exists or not judge_doc.to_dict().get("approved"):
        flash("Judge not found or not approved.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    judge = judge_doc.to_dict()

    student_assignments = load_student_projects()
    cat_projects = student_assignments[student_assignments["Category"] == category]
    count = 0
    for _, row in cat_projects.iterrows():
        pid = row["ID (project)"]
        
        # Check if assignment already exists
        existing = db.collection('judge_assignments').where('judge_id', '==', judge["judge_id"]).where('student_project_id', '==', pid).limit(1).get()
        if not existing:
            db.collection('judge_assignments').add({
                'judge_id': judge["judge_id"],
                'student_project_id': pid
            })
        count += 1

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
    
    scores_docs = db.collection('scores').get()
    judges_docs = db.collection('judges').get()
    
    # Create lookup map for judge info
    judges_map = {doc.to_dict().get("judge_id"): doc.to_dict() for doc in judges_docs}
    
    scores = []
    for doc in scores_docs:
        s = doc.to_dict()
        j = judges_map.get(s.get("judge_id"), {})
        s["first_name"] = j.get("first_name", "Unknown")
        s["last_name"] = j.get("last_name", "Unknown")
        scores.append(s)
        
    scores.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return render_template("admin_scores.html", scores=scores, scoring_names=SCORING_SHORT_NAMES)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "info")
    return redirect(url_for("admin_login"))

if __name__ == "__main__":
    init_db()
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(debug=debug, port=5000)
