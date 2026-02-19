# Science Fair Judging App

This branch is a prototype Flask + SQLite web app. It's end-to-end, managing the judge signup, score entering, and processing in one interface. Assumes that student data is already available (check [Student Data](#student-data) to see how it should be formatted). 

## Setup

1. Create a virtual environment (e.g. virtualenv, conda), use a package manager like [uv](https://github.com/astral-sh/uv), or install in your base environment. The only external dependencies are flask and pandas (e.g. run `pip install flask pandas`). 

2. Create a .env file. Set `ADMIN_PASSWORD`, this will be the password used to access the admin interface. Only set `FLASK_ENV` to production if deploying to a production environment; otherwise, leave it unset. 

3. Place student+project data in `data/student_assignments.csv`. Dummy data is included at `dummy_data.csv`. Required columns (more is OK, but modify the DB logic accordingly):

- `Category` — project category (can span multiple rows; forward-filled automatically)
- `ID (project)` — unique project ID
- `Student First Name`, `Student Last Name`
- `Title of Presentation`

3. Run `python app.py` to deploy the app locally and open `http://localhost:5000` for the interface. 

## Workflow

### 1. Judge Signup

Judges visit `/signup` to create an account (username, password, first/last name). A unique judge ID is auto-generated. Accounts are **inactive until admin approval**.

### 2. Admin Approval & Assignment

1. Go to `/admin/login` and log in with the admin password set in your .env file.
2. Approve or reject pending judges.
3. Click **Assign** next to an approved judge to select which projects they should score. 

### 3. Scoring

Judges log in at `/login` and see only their assigned projects. Each project can be scored **once** (no re-scoring). In this program, scores are 1–10 across 10 criteria:

- Background, Originality, Methodology, Analysis, Interpretation, Subject Knowledge
- Delivery, Organization, Visual Aids, Ability to Answer Questions

Modify the rubric in `utils.py` and update the HTML templates accordingly.

### 4. Results

From the admin dashboard, click **Process & Validate Scores** to aggregate results. The output CSV (`output/output.csv`) contains per-project averages sorted by category and score, along with which judges scored each project and who was assigned. Download the CSV from the **Results** page.