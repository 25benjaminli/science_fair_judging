# Science Fair Judging App

This branch is a prototype Flask + Firebase web app. It's end-to-end, managing the judge signup, score entering, and processing in one interface. Assumes that student data is already available (check [Setup](#setup) to see how it should be formatted). 

## Setup

1. Create a virtual environment (e.g. virtualenv, conda), use a package manager like [uv](https://github.com/astral-sh/uv), or install in your base environment. Install dependencies via `pip install flask pandas firebase-admin authlib requests`. 

2. Create a .env file. First, set `ADMIN_PASSWORD`, this will be the password used to access the admin interface. Next, set `SECRET_KEY`, run the following command and paste the output as the value `python -c 'import secrets; print(secrets.token_hex())'`. Only set `FLASK_ENV` to production if deploying to a production environment; otherwise, leave it unset. 

3. Firebase initialization. 
a. Create a [firebase project](https://firebase.google.com/). 
b. Get your project credentials and drag into the project root, rename `credentials.json`.
c. Enable cloud firestore and authentication (google oauth). 
d. Visit APIs & Services > Credentials > OAuth 2.0 Client IDs, then retrieve `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from the web client tab. Also, whitelist `http://127.0.0.1:5000/auth/callback` in "authorized redirect URIs". If deploying to production, you'll have to modify this once more. 

4. Place student+project data in `data/student_assignments.csv`. Dummy data for testing is included at `dummy_data.csv`. Required columns (more is OK, but modify the DB logic accordingly):

- `Category` — project category (can span multiple rows; forward-filled automatically)
- `ID (project)` — unique project ID
- `Student First Name`, `Student Last Name`
- `Title of Presentation`

5. Run `python app.py` to deploy the app locally and open `http://localhost:5000` for the interface. 

## Workflow

### 1. Judge Signup & Login

Judges visit `/login` to sign in using their Google account securely. A unique judge ID is auto-generated upon their first initial sign in. Accounts are **inactive until admin approval**, so judges will need to wait before being able to view assignments.

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

From the admin dashboard, click **Process & Validate Scores** to aggregate results. The output CSV (`[DATA_DIR]/output.csv`) contains per-project averages sorted by category and score, along with which judges scored each project and who was assigned. Download the CSV from the **Results** page.