# Science Fair Judging System

Takes judging scores from google forms -> spreadsheets, performs input validation to ensure consistency, orders participants per category by mean score. Should be adaptable to your own custom forms with some tweaks and fairly extendable (in case you want more summary statistics on judges, students, etc). Used for the 2025 New Jersey Academy of Science Junior Academy Symposium. 

## Installation

1. Install required packages (it would be wise to use something like conda...):
```sh
pip install -r requirements.txt
```

2. Set up Google Sheets API:
   - Create a service account and download the credentials JSON file
   - Share your Google Spreadsheet with the service account email
   - Create a `.env` file in the project root:
   ```
   SPREADSHEET_KEY=your_google_spreadsheet_key
   ```

## Data Format

All input files should be placed in the `2025` directory.

### `ids_categories.csv`

Maps student projects to categories and assigned judges.

| ID (project) | Category | Student First Name | Student Last Name | Judge 1 | Judge 2 | Judge 3 | ... |
|--------------|----------|-------------------|------------------|---------|---------|---------|-------|
| APS01 | Animal and Plant Science | John | Doe | Alice Smith | Bob Jones | Carol White | ...
| MCS01 | Math and Computer Science | Jane | Smith | Zachery Smith | Neville Ford | Pam Rogers | ...
|  | Math and Computer Science | Jacob | Green | Zachery Smith | Neville Ford | Pam Rogers | ...
| CHE01 | Chemistry/Biochemistry | Mike | Johnson | David Lee | Emily Brown | Frank Davis | ...

**Key Points:**
- The `Category` column forward-fills: blank cells inherit the category from above. BUT I believe it also works if each cell has a category assigned to it too. 
- Judge columns (1-6) can be left blank if fewer judges are assigned
- Project IDs must be unique and match IDs in scoring data
- Judge names must match format in `ids_judges.csv` (format: "First Last")

### `ids_judges.csv`

List of all judges with unique identifiers.

| JUDGE ID | FIRST | LAST |
|----------|-------|------|
| ASM | Alice | Smith |
| BJO | Bob | Jones |
| CWH | Carol | White |
| DLE | David | Lee |
| EBR | Emily | Brown |

**Key Points:**
- Judge IDs must be consistent across all files
- Names must exactly match those used in `ids_categories.csv`

### `raw_scores.csv`

This is acquired via the spreadsheet connected to the google form. I set up a simple google form with the "multiple choice grid" option titled "presentation content". The resulting spreadsheet should look like this. 

| Timestamp | Email Address | Judge ID | Student Project ID | Presentation Content [Background] | Presentation Content [Originality] | Presentation Content [Methodology] | ... | Other Comments | Student Name |
|-----------|---------------|----------|-------------------|----------------------------------|---------------------------------------------------------------|-----------------------------------------------------------------------------|-----|----------------|--------------|
| 2025-01-15 10:30:00 | alice@example.com | ASM | APS01 | 8 | 9 | 7 | ... | Great project | John Doe |
| 2025-01-15 10:35:00 | bob@example.com | BJO | APS01 | 7 | 8 | 8 | ... | Well done | John Doe |
| 2025-01-15 10:40:00 | carol@example.com | CWH | CHE01 | 9 | 9 | 8 | ... | Excellent work | Mike Johnson |

**Key Points:**
- The "..." represents additional scoring columns from the judging rubric
- `Timestamp` and `Email Address` are ignored by the system
- `Student Project ID` are enforced to match IDs in `ids_categories.csv`
- `Judge ID` are enforced to match IDs in `ids_judges.csv`
- All columns with "Presentation Content" or "Presentation Skills" in the header are used for scoring



## Running the Program

```sh
# Basic usage (checks for updates every 1 minute)
python main.py --interval 1

# only add flags like --no_verify or --no_check if you're debugging/testing
```

Overall, the system validates:
- Judge IDs entered to the form exist in `ids_judges.csv`
- Project IDs entered to the form are registered in `ids_categories.csv`
- No duplicate scores from same judge
- Judges only score assigned projects
- Projects have minimum number of required judges

Check `njas_judging.log` for errors and warnings!

Running the program produces three relevant outputs:

- `output/output.csv` - Aggregated scores with average totals and judge counts
- `output/output.md` - Formatted markdown tables by category
- Google Sheets `aggregated_scores` worksheet

Once you're done with the entire fair you can run 
```sh
python verify_done.py
```
to confirm that all registered participants have been judged. 

## License
MIT