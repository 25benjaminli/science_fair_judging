import gspread
import csv
import os
import time

import pandas as pd
import argparse
import os
import math
import logging
from dotenv import load_dotenv
from utils import verify_validity, generate_csv
load_dotenv()

# initiate logger
logging.basicConfig(filename='njas_judging.log', level=logging.INFO, format='%(levelname)s:%(message)s')
logger = logging.getLogger()

parser = argparse.ArgumentParser()
parser.add_argument('--interval', type=int, default=1, help='Interval in minutes to check for updates')
parser.add_argument('--no_check', action='store_true', help='Disables cached spreadsheet updating with online version. Only use this flag if testing')
parser.add_argument('--no_verify', action='store_true', help='Disables validity verification (i.e. confirming all valid IDs for students/judges, no duplicates, etc). ')

args = parser.parse_args()

INTERVAL = args.interval

if args.no_check:
    CHECK_SAME = False
else:
    CHECK_SAME = True

if args.no_verify:
    VERIFY_VALIDITY = False
else:
    VERIFY_VALIDITY = True

print("INTERVAL", INTERVAL, "CHECK_SAME", CHECK_SAME, "VERIFY_VALIDITY", VERIFY_VALIDITY)

data_dir = "2025"
out_dir = "output"

if not os.path.exists(out_dir):
    os.makedirs(out_dir)
if not os.path.exists(data_dir):
    os.makedirs(data_dir)


while(True):
    gc = gspread.service_account()
    spreadsheet = gc.open_by_key(os.getenv("SPREADSHEET_KEY"))

    worksheet = spreadsheet.worksheet("raw_scores")
    temp_fname = f"{data_dir}/raw_scores_temp.csv"
    old_fname = f"{data_dir}/raw_scores.csv"


    with open(temp_fname, 'w') as f:
        writer = csv.writer(f)
        # print(worksheet.get_all_values())
        writer.writerows(worksheet.get_all_values())

    if os.path.exists(f"{data_dir}/raw_scores.csv") and CHECK_SAME:
        old_scores = pd.read_csv(old_fname)
        new_scores = pd.read_csv(temp_fname)
        if old_scores.equals(new_scores):
            print("raw_scores is the same, not updating")
            time.sleep(INTERVAL * 60)
            continue
        else:
            print("updating raw_scores")
            os.remove(f"{data_dir}/raw_scores.csv")
            os.rename(temp_fname, f"{data_dir}/raw_scores.csv")
    elif CHECK_SAME:
        os.rename(temp_fname, f"{data_dir}/raw_scores.csv")
    

    print("processing scores from fair participants")
    final_df = generate_csv(f"{data_dir}/raw_scores.csv", data_dir, out_dir)

    print("#### VERIFYING VALIDITY ####")
    if (VERIFY_VALIDITY and verify_validity(final_df, data_dir, out_dir)) or not VERIFY_VALIDITY:
        if VERIFY_VALIDITY:
            print("passed all checks :)")
        else:
            print("SKIPPING VERIFICATION AS REQUESTED and writing to sheets")
        
        try:
            spreadsheet.del_worksheet(spreadsheet.worksheet('aggregated_scores'))
        except gspread.exceptions.WorksheetNotFound:
            pass

        spreadsheet.add_worksheet(title='aggregated_scores', rows=500, cols=20)
        worksheet = spreadsheet.worksheet('aggregated_scores')

        with open(f'{out_dir}/output.csv', 'r') as f:
            all_rows = list(csv.reader(f))
        
        if all_rows:
            worksheet.update(all_rows, f'A1:Z{len(all_rows)}', value_input_option='RAW')
        
        print(f"Wrote {len(all_rows)} rows to google sheets")
        time.sleep(INTERVAL * 60)
    else:
        print("FAILED -- see errors in njas_judging.log")
        time.sleep(INTERVAL * 60)