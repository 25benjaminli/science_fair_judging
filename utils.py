import pandas as pd
import logging

logger = logging.getLogger()

def get_category(project_id, df):
    row_index = df.index[df['ID (project)'] == project_id].tolist()

    if not row_index:
        return "Student Project ID not found"

    idx = row_index[0] # start at the index of the Student Project ID
    while idx >= 0 and pd.isna(df.at[idx, "Category"]):
        idx -= 1
    
    return df.at[idx, "Category"] if idx >= 0 else "Category not found"



def generate_csv(spreadsheet_name, data_dir, out_dir):
    # initiate logger

    ids_categories = pd.read_csv(f"{data_dir}/ids_categories.csv")
    scores = pd.read_csv(spreadsheet_name).drop(columns=['Timestamp', 'Email Address'])

    cols_list = scores.columns.tolist()

    # !! this filtering mechanism assumes a certain format, you can customize depending on your question categories
    valid_cols_for_sum = [col for col in cols_list if "Presentation Content" in col or "Presentation Skills" in col or "Student Project ID" in col]

    cumu_table = pd.DataFrame(columns=valid_cols_for_sum)

    print("number of judging entries", len(scores))


    for index in range(len(scores)):
        current_row = scores.loc[index]
        project_id = current_row['Student Project ID'].strip().upper()
        judge_id = current_row['Judge ID'].strip().upper()
        current_sum = 0
        temp_dict = {}
        for col in valid_cols_for_sum:
            if col == 'Student Project ID': continue
            current_sum += int(scores.loc[index, col])
            temp_dict[col] = int(scores.loc[index, col])

        if project_id in cumu_table['Student Project ID'].values:
            cumu_row = cumu_table.loc[cumu_table['Student Project ID'] == project_id]
        else:
            cumu_row = None
        if cumu_row is None:
            new_row = scores.loc[index].copy()
            new_row['Judges Num'] = 1 # initialize
            # search for the corresponding category
            new_row['Category'] = get_category(project_id, ids_categories)
            new_row['Judges Had'] = judge_id
            new_row['Student Project ID'] = project_id

            new_row_df = pd.DataFrame(new_row).T
            cumu_table = pd.concat([cumu_table, new_row_df], ignore_index=True)

        else:
            for key in temp_dict:
                cumu_table.loc[cumu_table['Student Project ID'] == project_id, key] += temp_dict[key]
            
            cumu_table.loc[cumu_table['Student Project ID'] == project_id, 'Judges Num'] += 1
            cumu_table.loc[cumu_table['Student Project ID'] == project_id, 'Judges Had'] += f",{judge_id}"

            # if cumu_table.loc[cumu_table['Student Project ID'] == project_id, 'Student Name'].values[0].lower() != current_row['Student Name'].lower():
            #     # this is a warning because the algorithm will just take the last name it sees and use it for the table
            #     logger.warning(f"Student Name mismatch for {project_id}. {cumu_table.loc[cumu_table['Student Project ID'] == project_id, 'Student Name'].values[0]} vs {current_row['Student Name']}")



    final_df = pd.DataFrame()

    # at the end, average everything out. then sort
    for index in range(len(cumu_table)):
        avg_tot_score = 0
        for col in valid_cols_for_sum:
            if col == 'Student Project ID': continue
            avg_tot_score += int(cumu_table.loc[index, col])
        avg_tot_score /= cumu_table.loc[index, 'Judges Num']

        new_row = {
            'Category': cumu_table.loc[index, 'Category'],
            'Student Project ID': cumu_table.loc[index, 'Student Project ID'],
            'Student Name': cumu_table.loc[index, 'Student Name'],
            'Average Total Score': round(avg_tot_score, 3),
            'Judges Num': cumu_table.loc[index, 'Judges Num'],
            'Judges Had': cumu_table.loc[index, 'Judges Had'],
            # you can also add other statistics here such as standard deviation, median, etc. 
        }
        
        final_df = pd.concat([final_df, pd.DataFrame([new_row])], ignore_index=True)

    # sort the final df by category and total
    final_df['Average Total Score'] = pd.to_numeric(final_df['Average Total Score'], errors='coerce')
    final_df = final_df.sort_values(by=['Category', 'Average Total Score'], ascending=[True, False])


    output_table = ""
    for category, group_df in final_df.groupby('Category'):
        output_table += f"**{category}**\n\n"
        output_table += group_df.to_markdown(index=False) + "\n\n"


    # print(output_table)
    # export to markdown
    with open(f"{out_dir}/output.md", "w") as f:
        f.write(output_table)
    # export to csv
    with open(f"{out_dir}/output.csv", "w") as f:
        final_df.to_csv(f, index=False)
    
    return final_df

def get_necessary_judges(ids_categories, ids_judges, output):
    project_dict = {}
    for index in range(len(output)):
        row = output.loc[index]
        # get the row associated with the current project id
        project_id = row['Student Project ID'].strip().upper()
        judges_had = [x.upper() for x in row['Judges Had'].split(",")] # assumed to already be in ID format

        ids_categories_row = ids_categories[ids_categories['ID (project)'] == project_id]
        # get the judges for that project
        judges = []
        assert len(ids_categories_row) == 1, f"Project ID {project_id} not found in ids_categories.csv"
        # print("current project id", project_id)
        for j in range(1,7):
            if pd.isna(ids_categories_row[f"Judge {j}"].values[0]):
                continue
            judges.append(str(ids_categories_row[f"Judge {j}"].values[0]).upper())
            

        project_dict[project_id] = []
        # print("judges array", judges)
        for judge in judges:
            
            fname = judge.split(" ", 1)[0].upper()
            lname = judge.split(" ", 1)[1].upper()
            judge_id = [ids_judges.loc[judgeidx]["JUDGE ID"].upper() for judgeidx in range(len(ids_judges)) if ids_judges.loc[judgeidx]["FIRST"].upper() == fname and ids_judges.loc[judgeidx]["LAST"].upper() == lname]
            if len(judge_id) != 1:
                logger.warning(f"number of judge ids for judge {judge} found is {len(judge_id)}")
            else:
                judge_id = judge_id[0]
                project_dict[project_id].append(judge_id)

        # experimental code to remove judges that have already been taken, but not necessary
        # for judge in judges_had:
        #     try:
        #         judges_missing.remove(judge.upper())
        #     except:
        #         # judge that was had by the student is not in their required list of judges
        #         # log the error
        #         # logger.warning(f"Judge ID {judge} was not in the list of required judges for project {project_id}!")
        #         continue # don't duplicate the warning message

    return project_dict

def verify_validity(final_scores, data_dir, out_dir):

    ids_judges = pd.read_csv(f"{data_dir}/ids_judges.csv")
    judge_ids_list = [str(x).strip().upper() for x in ids_judges['JUDGE ID'].tolist()]


    ids_categories = pd.read_csv(f"{data_dir}/ids_categories.csv")
    id_list = [str(x).strip().upper() for x in ids_categories['ID (project)'].tolist()]
    # student_names_list = [str(x).strip().lower() for x in ids_categories['Student Name'].tolist()]

    output = pd.read_csv(f"{out_dir}/output.csv")
    project_dict = get_necessary_judges(ids_categories, ids_judges, output)


    passed = True

    for i in range(len(final_scores)):
        row = final_scores.loc[i]
        # confirm that Judges Num matches the number of unique judges in Judges Had
        project_id = row['Student Project ID'].strip().upper()
        judges_had = [x.strip().upper() for x in row['Judges Had'].split(",")]
        unique_judges_had = set(judges_had)
        if len(unique_judges_had) != row['Judges Num']:
            text = f"all judges should be unique for {project_id}, got {judges_had}"
            # a real problem, duplicate entries cannot exist!!
            logger.error(text)
            passed = False
        
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
            logger.error(f"Project {project_id} has {len(unique_judges_had)} judges but was assigned {required_judges}")
            passed = False

    return passed
    
# utility function, use if you desire
def get_names(data_dir):
    placements = pd.read_csv(f"{data_dir}/placements.csv")
    ids_categories = pd.read_csv(f"{data_dir}/ids_categories.csv")

    placements = placements.drop(columns=['Student Name'])
    for index in range(len(placements)):
        current_row = placements.loc[index]
        project_id = current_row['Student Project ID'].strip().upper()
        id_row = ids_categories[ids_categories['ID (project)'] == project_id]
        fname, lname = id_row['Student First Name'].values[0], id_row['Student Last Name'].values[0]
        # print("fname", fname, "lname", lname)
        placements.loc[index, 'Student First Name'] = fname
        placements.loc[index, 'Student Last Name'] = lname
        

    # sort placements by place, then by last name (A-Z)
    placements = placements.sort_values(by=['prize winnner', 'place', 'Student Last Name'], ascending=[True, False, True])
    placements.to_csv(f"{data_dir}/placements_new.csv", index=False)