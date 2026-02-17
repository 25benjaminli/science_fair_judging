import streamlit as st
import gspread
import csv
import os
import pandas as pd
from dotenv import load_dotenv
from utils import verify_validity, generate_csv
import logging

load_dotenv()

logging.basicConfig(
    filename="science_fair_judging.log",
    level=logging.INFO,
    format="%(levelname)s:%(message)s",
)
logger = logging.getLogger()

st.set_page_config(page_title="science_fair Judging System",
                   page_icon="📊", layout="wide")

# configure for your own use
data_dir = "2025"
out_dir = "output"

st.title("Science Fair Judging System")
st.markdown(
    "Process judging scores and generate aggregated results. Currently relies on external google forms / sheets to retrieve data. Check out the readme for how to setup the spreadsheet!"
)

tab1, tab2, tab3 = st.tabs(
    ["Search Students", "Search Judges", "Process Scores"])

with tab1:
    st.header("Student Search")
    st.markdown(
        "Search for a student to view their project details and assigned judges")

    if os.path.exists(f"{out_dir}/output.csv"):
        output_df = pd.read_csv(f"{out_dir}/output.csv")

        search_term = st.text_input(
            "Search by Student Name or Project ID",
            placeholder="e.g., 'Smith' or 'APS02'",
        )

        if search_term:
            mask = (
                output_df["Student Name"].astype(
                    str).str.contains(search_term, case=False, na=False)
                | output_df["Student Project ID"].astype(str).str.contains(search_term, case=False, na=False)
            )
            results = output_df[mask]

            if len(results) > 0:
                st.success(f"Found {len(results)} result(s)")
                for idx, row in results.iterrows():
                    with st.expander(
                        f"**{row['Student Name']}** - {row['Student Project ID']}"
                    ):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(
                                f"**Project ID:** {row['Student Project ID']}")
                            st.markdown(
                                f"**Category:** {row['Category']}")
                            st.markdown(
                                f"**Title:** {row['Title of Presentation']}")
                            st.markdown(
                                f"**Score:** {row['Average Total Score']}")
                        with col2:
                            st.markdown(
                                f"**Assigned Judges:** {row['Assigned Judges']}")
                            st.markdown(
                                f"**Received Judges:** {row['Judges Had']}")
                            st.markdown(
                                f"**Judges Count:** {row['Judges Num']}")
            else:
                st.warning("No students found matching your search")
    else:
        st.error("Output file not found. Please process scores first.")

with tab2:
    st.header("Judge Search")
    st.markdown(
        "Search for a judge to view projects they've judged and haven't judged yet")

    if (
        os.path.exists(f"{data_dir}/ids_judges.csv")
        and os.path.exists(f"{out_dir}/output.csv")
    ):
        ids_judges_df = pd.read_csv(f"{data_dir}/ids_judges.csv")
        output_df = pd.read_csv(f"{out_dir}/output.csv")

        # Map judge_id -> list of projects they judged
        judge_to_judged = {}
        # Map judge_id -> list of projects assigned to them
        judge_to_assigned = {}

        for _, project_row in output_df.iterrows():
            # judges who judged the project
            judges_had = [j.strip().upper()
                          for j in str(project_row['Judges Had']).split(',') if j.strip()]
            for judge_id in judges_had:
                if judge_id not in judge_to_judged:
                    judge_to_judged[judge_id] = []
                judge_to_judged[judge_id].append({
                    'id': project_row['Student Project ID'],
                    'student': project_row['Student Name'],
                    'category': project_row['Category'],
                    'score': project_row['Average Total Score']
                })

            # judges assigned to the project
            assigned_judges = [j.strip().upper() for j in str(
                project_row['Assigned Judges']).split(',') if j.strip()]
            for judge_id in assigned_judges:
                if judge_id not in judge_to_assigned:
                    judge_to_assigned[judge_id] = []
                judge_to_assigned[judge_id].append({
                    'id': project_row['Student Project ID'],
                    'student': project_row['Student Name'],
                    'category': project_row['Category']
                })

        search_judge = st.text_input(
            "Search by Judge Name or Judge ID", placeholder="e.g., 'Smith' or 'MOH'")

        if search_judge:
            mask = (
                ids_judges_df["FIRST"].astype(str).str.contains(
                    search_judge, case=False, na=False)
                | ids_judges_df["LAST"].astype(str).str.contains(search_judge,
                                                                 case=False, na=False)
                | ids_judges_df["JUDGE ID"].astype(str).str.contains(search_judge, case=False, na=False)
            )
            results = ids_judges_df[mask]

            if len(results) > 0:
                st.success(f"Found {len(results)} judge(s)")
                for idx, row in results.iterrows():
                    judge_id = row["JUDGE ID"].strip().upper()
                    judge_name = f"{row['FIRST']} {row['LAST']}"

                    with st.expander(f"**{judge_name}** ({judge_id})"):
                        judged_projects = judge_to_judged.get(judge_id, [])
                        assigned_projects = judge_to_assigned.get(judge_id, [])

                        col1, col2 = st.columns(2)

                        with col1:
                            st.markdown(
                                f"### ✅ Projects Judged ({len(judged_projects)})")
                            if judged_projects:
                                for project in judged_projects:
                                    st.markdown(
                                        f"- **{project['id']}**: {project['student']} ({project['category']})")
                            else:
                                st.info("No projects judged yet")

                        with col2:
                            st.markdown(f"### ⏳ Not Yet Judged")
                            judged_ids = [p['id'] for p in judged_projects]
                            unjudged = [
                                p for p in assigned_projects if p['id'] not in judged_ids]
                            if unjudged:
                                st.warning(
                                    f"{len(unjudged)} project(s) pending")
                                for project in unjudged:
                                    st.markdown(
                                        f"- **{project['id']}**: {project['student']} ({project['category']})")
                            else:
                                st.success(
                                    "All assigned projects have been judged!")
            else:
                st.warning("No judges found matching your search")
    else:
        st.error("Required data files not found. Please process scores first.")

with tab3:
    st.header("Process Scores")

st.sidebar.header("Options")
verify_validity_flag = st.sidebar.checkbox(
    "Verify validity",
    value=True,
    help="Confirms all valid IDs for students/judges, no duplicates, etc.",
)
check_updates = st.sidebar.checkbox(
    "Check for updates", value=True, help="Only process if spreadsheet has changed")
upload_to_sheets = st.sidebar.checkbox(
    "Upload to Google Sheets", value=True, help="Upload processed results to Google Sheets")

with tab3:
    if st.button("Process Scores", type="primary"):
        with st.spinner("Fetching data from Google Sheets..."):
            try:
                gc = gspread.service_account()
                spreadsheet = gc.open_by_key(os.getenv("SPREADSHEET_KEY"))
                worksheet = spreadsheet.worksheet("raw_scores")

                # download raw scores from online sheets
                temp_fname = f"{data_dir}/raw_scores_temp.csv"
                old_fname = f"{data_dir}/raw_scores.csv"

                with open(temp_fname, "w") as f:
                    writer = csv.writer(f)
                    writer.writerows(worksheet.get_all_values())

                # only process the scores if there are updates, otherwise skip to display
                should_process = True
                if os.path.exists(old_fname) and check_updates:
                    old_scores = pd.read_csv(old_fname)
                    new_scores = pd.read_csv(temp_fname)
                    if old_scores.equals(new_scores):
                        st.info("Raw scores haven't changed since last run")
                        should_process = False
                    else:
                        st.success("New scores detected")
                        os.remove(old_fname)
                        os.rename(temp_fname, old_fname)
                else:
                    if os.path.exists(temp_fname):
                        if os.path.exists(old_fname):
                            os.remove(old_fname)
                        os.rename(temp_fname, old_fname)

                # open raw_scores and strip + upper Student Project ID and Judge ID columns
                raw_scores_df = pd.read_csv(f"{data_dir}/raw_scores.csv")
                raw_scores_df["Student Project ID"] = raw_scores_df["Student Project ID"].str.strip(
                ).str.upper()
                raw_scores_df["Judge ID"] = raw_scores_df["Judge ID"].str.strip(
                ).str.upper()
                raw_scores_df.to_csv(f"{data_dir}/raw_scores.csv", index=False)

                if should_process or not check_updates:
                    with st.spinner("Processing scores..."):
                        final_df = generate_csv(data_dir, out_dir)
                        st.success(f"Processed {len(final_df)} projects")

                    if verify_validity_flag:
                        with st.spinner("Verifying validity..."):
                            if verify_validity(final_df, data_dir, out_dir):
                                st.success("✅ Passed all validity checks")
                                valid = True
                            else:
                                st.error(
                                    "❌ Validity checks failed - see science_fair_judging.log for details")
                                valid = False
                    else:
                        st.warning("Skipping validity verification")
                        valid = True

                    # upload to google sheets (so other admins can see it, a little scuffed but would otherwise require formal database handling)
                    if valid and upload_to_sheets:
                        with st.spinner("Uploading to Google Sheets..."):
                            try:
                                spreadsheet.del_worksheet(
                                    spreadsheet.worksheet("aggregated_scores"))
                            except gspread.exceptions.WorksheetNotFound:
                                pass

                            spreadsheet.add_worksheet(
                                title="aggregated_scores", rows=500, cols=20)
                            worksheet = spreadsheet.worksheet(
                                "aggregated_scores")

                            with open(f"{out_dir}/output.csv", "r") as f:
                                all_rows = list(csv.reader(f))

                            if all_rows:
                                worksheet.update(
                                    all_rows,
                                    f"A1:Z{len(all_rows)}",
                                    value_input_option="RAW",
                                )
                                st.success(
                                    f"✅ Uploaded {len(all_rows)} rows to Google Sheets")
                    elif valid and not upload_to_sheets:
                        st.info(
                            "📋 Skipped uploading to Google Sheets (disabled in options)")

                if os.path.exists(f"{out_dir}/output.csv"):
                    st.markdown("---")
                    st.header("Aggregated Scores")

                    output_df = pd.read_csv(f"{out_dir}/output.csv")

                    categories = output_df["Category"].unique()
                    for category in sorted(categories):
                        st.subheader(f"**{category}**")
                        category_df = output_df[output_df["Category"]
                                                == category]
                        st.dataframe(
                            category_df, use_container_width=True, hide_index=True)

                    st.download_button(
                        label="Download CSV",
                        data=output_df.to_csv(index=False),
                        file_name="aggregated_scores.csv",
                        mime="text/csv",
                    )

            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Streamlit error: {str(e)}")

    elif os.path.exists(f"{out_dir}/output.csv"):
        st.info("Click 'Process Scores' to fetch and process new data")
        st.markdown("---")
        st.header("Last Processed Results")

        output_df = pd.read_csv(f"{out_dir}/output.csv")

        categories = output_df["Category"].unique()
        for category in sorted(categories):
            st.subheader(f"**{category}**")
            category_df = output_df[output_df["Category"] == category]
            st.dataframe(category_df, use_container_width=True,
                         hide_index=True)

        st.download_button(
            label="Download CSV",
            data=output_df.to_csv(index=False),
            file_name="aggregated_scores.csv",
            mime="text/csv",
        )
    else:
        st.info("Click 'Process Scores' to get started")
