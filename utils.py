import pandas as pd
import logging

# logging.basicConfig(filename='judging.log', level=logging.INFO,
#                     format='%(levelname)s:%(message)s')
logger = logging.getLogger()

# specify yourself based on your form
SCORING_COLUMNS = [
    'Presentation Content [Background]',
    'Presentation Content [Originality of idea/purpose to research]',
    'Presentation Content [Appropriateness of methodology/procedure/study design]',
    'Presentation Content [Analysis of results]',
    'Presentation Content [Interpretation of results/conclusion]',
    'Presentation Content [Subject knowledge conveyed]',
    'Presentation Skills [Delivery]',
    'Presentation Skills [Organization of material]',
    'Presentation Skills [Appropriateness of visual aids]',
    'Presentation Skills [Ability to answer questions]'
]


def generate_csv(data_dir, out_dir):
    scores = pd.read_csv(f"{data_dir}/raw_scores.csv")
    ids_categories = pd.read_csv(f"{data_dir}/ids_categories.csv")

    # forward fill ids_categories to get category for each project id
    mask = ids_categories['ID (project)'].notna()
    ids_categories.loc[mask,
                       'Category'] = ids_categories.loc[mask, 'Category'].ffill()

    ids_categories = ids_categories[ids_categories['ID (project)'].notna()].copy(
    )

    # send to csv to inspect (debug)
    # ids_categories.to_csv(f"{out_dir}/ids_categories_filled.csv", index=False)

    logger.info(f"Number of judging entries: {len(scores)}")

    # merge scores with category info so all student data in one df based on project id
    merged = scores.merge(
        ids_categories[['ID (project)', 'Category',
                        'Student First Name', 'Student Last Name', 'Title of Presentation']],
        left_on='Student Project ID',
        right_on='ID (project)',
        how='left'
    )

    merged = merged.drop(columns=['ID (project)'])
    merged['Student Project ID'] = merged['Student Project ID'].astype(
        str).str.strip().str.upper()
    merged['Judge ID'] = merged['Judge ID'].astype(str).str.strip().str.upper()

    for col in SCORING_COLUMNS:
        merged[col] = pd.to_numeric(merged[col], errors='coerce')

    # group dataframe by identical project IDs, calc score means, take first student name, etc.
    results = merged.groupby(['Student Project ID']).agg({
        **{col: 'mean' for col in SCORING_COLUMNS},
        # x is the series of judge IDs
        'Judge ID': lambda x: ','.join(sorted(set(x.astype(str)))),
        'Student First Name': 'first',
        'Student Last Name': 'first',
        'Category': 'first',
        'Title of Presentation': 'first'
    }).reset_index()

    results = results.rename(columns={
        'Judge ID': 'Judges Had',
    })
    results['Judges Num'] = results['Judges Had'].apply(
        lambda x: len(x.split(',')) if pd.notna(x) else 0)

    # Average Total Score is just the average of all the scoring columns, reason why the other columns are there is in case you need more analysis
    results['Average Total Score'] = sum(
        results[col] for col in SCORING_COLUMNS)
    results['Average Total Score'] = results['Average Total Score'].round(3)
    results['Student Name'] = results['Student First Name'] + \
        " " + results['Student Last Name']

    final_cols = [
        'Category', 'Student Project ID', 'Student Name', 'Title of Presentation',
        'Average Total Score', 'Judges Num', 'Judges Had'
    ]
    # print("results columns after processing", results.columns)
    final_df = results[final_cols].copy()

    # Sort by category and score
    final_df = final_df.sort_values(
        by=['Category', 'Average Total Score'],
        ascending=[True, False]
    )

    # add Assigned Judges column based on ids_categories and ids_judges
    ids_judges_df = pd.read_csv(f"{data_dir}/ids_judges.csv")
    project_dict = get_necessary_judges(
        ids_categories, ids_judges_df, final_df)
    final_df['Assigned Judges'] = final_df['Student Project ID'].apply(
        lambda x: ','.join(project_dict[x]) if x in project_dict else '')

    output_table = ""
    for category, group_df in final_df.groupby('Category'):
        output_table += f"**{category}**\n\n"
        output_table += group_df.to_markdown(index=False) + "\n\n"

    final_df.to_csv(f"{out_dir}/output.csv", index=False)

    return final_df


def get_necessary_judges(ids_categories, ids_judges, output):
    project_dict = {}
    for index, row in output.iterrows():
        # get the row associated with the current project id
        project_id = row['Student Project ID']

        ids_categories_row = ids_categories[ids_categories['ID (project)']
                                            == project_id]
        judges = []
        if len(ids_categories_row) != 1:
            logger.error(
                f"Student Project ID {project_id} not found or duplicated in ids_categories.csv")
            continue

        # print("current project id", project_id)
        for j in range(1, 7):
            if pd.isna(ids_categories_row[f"Judge {j}"].values[0]):
                continue
            judges.append(
                str(ids_categories_row[f"Judge {j}"].values[0]).upper())

        project_dict[project_id] = []
        for judge in judges:
            # Handle judge names - split on first space
            judge_parts = judge.split(" ", 1)
            if len(judge_parts) != 2:
                logger.warning(
                    f"Judge name '{judge}' does not contain first and last name")
                continue

            fname = judge_parts[0].upper()
            lname = judge_parts[1].upper()
            judge_id = [ids_judges.loc[judgeidx]["JUDGE ID"].upper() for judgeidx in range(len(
                ids_judges)) if ids_judges.loc[judgeidx]["FIRST"].upper() == fname and ids_judges.loc[judgeidx]["LAST"].upper() == lname]
            if len(judge_id) != 1:
                logger.warning(
                    f"number of judge ids for judge {judge} found is {len(judge_id)}")
            else:
                judge_id = judge_id[0]
                project_dict[project_id].append(judge_id)
        project_dict[project_id] = sorted(project_dict[project_id])

    return project_dict


def verify_validity(final_scores, data_dir, out_dir):

    ids_judges = pd.read_csv(f"{data_dir}/ids_judges.csv")
    judge_ids_list = [str(x).strip().upper()
                      for x in ids_judges['JUDGE ID'].tolist()]

    ids_categories = pd.read_csv(f"{data_dir}/ids_categories.csv")
    id_list = [str(x).strip().upper()
               for x in ids_categories['ID (project)'].tolist()]

    project_dict = get_necessary_judges(
        ids_categories, ids_judges, final_scores)

    passed = True

    for i, row in final_scores.iterrows():
        # confirm that Judges Num matches the number of unique judges in Judges Had
        project_id = row['Student Project ID']
        judges_had = [x.strip()
                      for x in str(row['Judges Had']).split(",") if x.strip()]
        unique_judges_had = set(judges_had)
        if len(unique_judges_had) != row['Judges Num']:
            text = f"all judges should be unique for {project_id}, got {judges_had}"
            # a real problem, duplicate entries cannot exist!!
            logger.error(text)
            passed = False

        if project_id not in project_dict:
            logger.error(f"Project {project_id} not found in project_dict")
            passed = False
            continue

        # confirm that all judges in Judges Had are in the allowed judges list
        for judge_id in unique_judges_had:
            if judge_id not in project_dict[project_id]:
                text = f"Judge {judge_id} for {project_id} not in allowed list {project_dict[project_id]}!"
                # this may be a problem but if more judges show up than expected then disregard
                logger.warning(text)
                passed = False

        required_judges = len(project_dict[project_id])
        if len(unique_judges_had) < required_judges:
            # a real problem - each project must have enough judges
            logger.error(
                f"Project {project_id} has {len(unique_judges_had)} judges but was assigned {required_judges}")
            passed = False

    return passed

# utility function, use if you desire


def get_names(data_dir):
    placements = pd.read_csv(f"{data_dir}/placements.csv")
    ids_categories = pd.read_csv(f"{data_dir}/ids_categories.csv")

    placements = placements.drop(columns=['Student Name'])
    for index, current_row in placements.iterrows():
        project_id = current_row['Student Project ID']
        id_row = ids_categories[ids_categories['ID (project)'] == project_id]
        if len(id_row) == 0:
            logger.warning(
                f"Project ID {project_id} not found in ids_categories")
            continue
        fname, lname = id_row['Student First Name'].values[0], id_row['Student Last Name'].values[0]
        # print("fname", fname, "lname", lname)
        placements.loc[index, 'Student First Name'] = fname
        placements.loc[index, 'Student Last Name'] = lname

    # sort placements by place, then by last name (A-Z)
    placements = placements.sort_values(
        by=['prize winner', 'place', 'Student Last Name'], ascending=[True, False, True])
    placements.to_csv(f"{data_dir}/placements_new.csv", index=False)


if __name__ == "__main__":
    # sanity check, you can also run the processing logic from here without the UI
    data_dir = "2025"
    out_dir = "output"
    final_scores = generate_csv(data_dir, out_dir)
    validity_passed = verify_validity(final_scores, data_dir, out_dir)
    if validity_passed:
        logger.info("All checks passed!")
    else:
        logger.warning("Some checks failed, please review the logs.")
