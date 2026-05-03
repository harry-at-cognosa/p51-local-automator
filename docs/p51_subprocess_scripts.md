# p51-local-automator Subprocess Scripts

## Overview

Two workflows delegate heavy processing to standalone Python scripts via `subprocess.run()`:
- **Type 1** -> `scripts/email_to_excel.py` (30s timeout)
- **Type 2** -> `scripts/analyze_data.py` (120s timeout)

### Why Subprocesses?
1. **Memory isolation** - Heavy pandas/matplotlib operations don't affect main process
2. **Timeout control** - Can kill stuck operations
3. **Error containment** - Script crash doesn't crash workflow engine
4. **Reusability** - Scripts can be run independently for testing

### Limitations
- No shared state - all data passed via files
- Output is stdout/stderr capture only
- No streaming progress updates
- Fixed timeout (30s email, 120s data)

### Communication Pattern
```
Workflow Runner
    |
    +-- Write input file (JSON or use existing CSV/XLSX)
    |
    +-- subprocess.run(["python3", script, input, "--output-dir", dir])
              |
              +-- Script writes output files
              |
              +-- Script prints summary to stdout
                        |
                        +-- Runner captures stdout, records artifacts
```

---

## scripts/analyze_data.py (709 lines)

**Purpose:** Multi-step data analysis pipeline with checkpointed outputs.

### Invocation (from `data_analyzer.py:76-85`)
```python
cmd = ["python3", script, file_path, "--output-dir", output_dir]
if config.get("start_date"): cmd.extend(["--start", config["start_date"]])
if config.get("end_date"): cmd.extend(["--end", config["end_date"]])
if config.get("days"): cmd.extend(["--days", str(config["days"])])
result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
```

### CLI Arguments
| Arg | Description |
|-----|-------------|
| `<file_path>` | Required: Path to CSV or Excel file |
| `--start` | Start date (YYYY-MM-DD) |
| `--end` | End date (YYYY-MM-DD) |
| `--days` | Days from start date |
| `--before` | Transactions before date |
| `--after` | Transactions after date |
| `--output-dir` | Override output directory |

### Internal Steps

#### Step 1: Ingest & Profile (lines 606-629)
- Load CSV/Excel via pandas
- Auto-detect date column (searches for "date", "time", "day" keywords)
- Auto-detect amount columns (searches for "amount", "price", "total", etc.)
- Auto-detect category columns (2-500 unique values)
- Generate `step1_data_profile.md`:
  - Row/column counts
  - Date range
  - Column summary table
  - Amount statistics (sum, mean, median, min, max, std)

#### Step 2: Filter & Select (lines 631-652)
- Filter by date range (if specified)
- Drop low-value columns:
  - All values same
  - >80% null
  - Address-like columns
  - Avg string length >80
- Generate `step2_filtered_data.xlsx`:
  - Styled headers (blue background)
  - Frozen header row
  - Auto-filter enabled
  - Number formatting

#### Step 3: Analyze & Chart (lines 654-681)
- Compute summary statistics with optional prior period comparison
- Generate `step3_summary_report.md`:
  - Amount totals/means with period-over-period % change
  - Category breakdowns (top 15)
- Generate charts:
  - `step3_chart_by_category.png` - Horizontal bar chart (top 12 categories)
  - `step3_chart_trend.png` - Time series with dual axis (amount + count)
  - `step3_chart_comparison.png` - Prior vs current period (if applicable)

#### Step 4: Outlier & Data Quality (lines 683-704)
- Missing value detection
- Duplicate row detection
- 3-sigma outlier detection per amount column
- Date parsing quality check
- Generate `step4_quality_report.md`

### Key Functions
| Function | Lines | Purpose |
|----------|-------|---------|
| `load_data()` | 69-86 | CSV/Excel loader with error handling |
| `detect_date_column()` | 89-102 | Auto-detect date column |
| `detect_amount_columns()` | 105-121 | Auto-detect monetary columns |
| `detect_category_columns()` | 124-140 | Auto-detect grouping columns |
| `profile_data()` | 143-182 | Generate markdown profile |
| `filter_by_date()` | 194-203 | Date range filtering |
| `select_key_fields()` | 206-234 | Column pruning |
| `write_filtered_excel()` | 237-274 | Styled Excel output |
| `compute_summary()` | 282-351 | Statistics with period comparison |
| `generate_charts()` | 354-481 | Matplotlib chart generation |
| `detect_outliers_and_quality()` | 488-567 | Data quality report |

### Dependencies
- pandas
- matplotlib
- numpy
- openpyxl

---

## scripts/email_to_excel.py (294 lines)

**Purpose:** Transform categorized email JSON into formatted Excel workbook.

### Invocation (from `email_monitor.py:176-178`)
```python
result = subprocess.run(
    ["python3", excel_script, json_path, "--output-dir", output_dir],
    capture_output=True, text=True, timeout=30,
)
```

### CLI Arguments
| Arg | Description |
|-----|-------------|
| `<input_json>` | Required: Path to categorized email JSON |
| `--output-dir` | Output directory (default ".") |
| `--slug` | Optional filename suffix |

### Input JSON Format
```json
[{
  "topic": "string",
  "sender": "string",
  "subject": "string",
  "date": "string",
  "snippet": "string",
  "thread_id": "string",
  "urgent": boolean,
  "urgency_reason": "string"
}]
```

### Output Structure

Creates `email_monitor_{timestamp}.xlsx` with multiple sheets:

#### Sheet 1: "Summary"
- Title: "Email Topic Monitor Report"
- Generated timestamp
- Total email count
- Urgent count (highlighted red)
- Topic summary table: Topic | Count | Urgent | Latest Date

#### Sheet 2: "All Emails"
- Columns: Date, Topic, Sender, Subject, Snippet, Urgent, Urgency Reason
- Sorted chronologically
- Auto-filter enabled
- Urgent rows highlighted pink with red text

#### Sheets 3+: One per topic
- Header with topic name and count
- Columns: Date, Sender, Subject, Snippet, Urgent, Urgency Reason
- Color-coded by topic index (rotating 5 colors)

### Styling (hardcoded constants, lines 48-84)
| Style | Value |
|-------|-------|
| Font | Calisto MT, size 12 |
| Header fill | #4472C4 (blue) |
| Header font | White, bold |
| Urgent fill | #FFC7CE (pink) |
| Urgent font | #9C0006 (red), bold |
| Topic fills | Blue, Green, Orange, Gray, Yellow (rotating) |
| Zoom | 130% |
| Row height | 26px minimum |

### Key Functions
| Function | Lines | Purpose |
|----------|-------|---------|
| `cell_alignment()` | 87-90 | Alignment based on column type |
| `apply_sheet_view()` | 93-95 | Set zoom level |
| `write_header()` | 103-112 | Styled header row |
| `write_email_row()` | 115-139 | Row with urgency highlighting |
| `set_column_widths()` | 142-156 | Fixed column widths |
| `create_workbook()` | 159-271 | Main workbook creation |

### Dependencies
- openpyxl
