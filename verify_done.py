import pandas as pd

data_dir = "data"
student_assignments = pd.read_csv(f"{data_dir}/student_assignments.csv")
id_list = [str(x).strip().upper()
           for x in student_assignments['ID (project)'].tolist()]

final_scores = pd.read_csv(f"{data_dir}/output.csv")
final_scores_list = [str(x).strip().upper()
                     for x in final_scores['Student Project ID'].tolist()]


# all project IDs are allowed to be scored
problems = []
for project_id in final_scores_list:
    if project_id not in id_list:
        problems.append(project_id)

if len(problems) > 0:
    print(
        f"The following project IDs have scores but are not registered: {problems}")
else:
    print("All project IDs with scores are registered!")

problems = []
for project_id in id_list:
    if project_id not in final_scores_list and project_id != "NAN":
        problems.append(project_id)

if len(problems) > 0:
    print(
        f"The following project IDs are registered but have no scores (maybe didn't show up): {problems}")
else:
    print("All registered project IDs have scores")
