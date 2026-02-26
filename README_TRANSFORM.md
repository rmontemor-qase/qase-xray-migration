# Running the Transform Phase

## Overview

The transform phase converts extracted Xray data into Qase format. It reads data from the cache directory created during extraction and produces transformed data ready for loading into Qase.

## Prerequisites

1. You must have already run the **extract** phase to create a cache directory with raw Xray data
2. The cache directory should contain:
   - `raw_data/projects.json`
   - `raw_data/folders.json`
   - `raw_data/test_cases.json`
   - `raw_data/attachments.json` (optional)
   - `raw_data/test_executions.json` (optional)

## Running the Transform Phase

### Using the CLI

```bash
python cli.py transform --cache <path_to_cache_directory>
```

**Example:**
```bash
python cli.py transform --cache ./cache/xray_extraction_20260210_134741/
```

### Using Python Code

```python
from pathlib import Path
from orchestrator import MigrationOrchestrator

# Load config (optional for transform)
config = {}  # Minimal config, or load from file

# Point to existing cache directory
cache_dir = Path("./cache/xray_extraction_20260210_134741/")

# Create orchestrator with existing cache
orchestrator = MigrationOrchestrator(config, cache_dir=cache_dir)

# Run transformation
stats = orchestrator.transform()

print(f"Transformation stats: {stats}")
```

## Output Location

The transformed data is saved in the cache directory under a `transformed/` subdirectory:

```
cache/xray_extraction_20260210_134741/
├── raw_data/              # Original extracted data
│   ├── projects.json
│   ├── folders.json
│   ├── test_cases.json
│   └── attachments.json
├── transformed/           # ✨ Transformed Qase-ready data
│   ├── projects.json      # Qase project payloads
│   ├── suites.json        # Qase suite payloads (from folders)
│   ├── cases.json         # Qase case payloads (from test cases)
│   ├── attachments_map.json  # Attachment ID mappings
│   ├── runs.json          # Qase run payloads (if executions exist)
│   └── results.json       # Qase result payloads (if executions exist)
├── mappings/
│   └── id_mappings.json   # ID mappings (Xray ID → Qase ID)
└── metadata.json
```

## Output Files Explained

### `transformed/projects.json`
Contains Qase project creation payloads:
```json
[
  {
    "title": "Project XM",
    "code": "PX",
    "description": "Migrated from Xray project XM",
    "settings": {
      "runs": {
        "auto_complete": false
      }
    },
    "access": "all"
  }
]
```

### `transformed/suites.json`
Dictionary mapping project codes to lists of suite payloads:
```json
{
  "PX": [
    {
      "title": "Orders",
      "description": "Migrated from Xray folder: /Migra/Test Repository/Orders",
      "preconditions": "",
      "parent_id": null
    }
  ]
}
```

### `transformed/cases.json`
Dictionary mapping project codes to lists of case payloads:
```json
{
  "PX": [
    {
      "title": "[Orders] Validate scenario 33",
      "description": "Case description in markdown",
      "steps": [
        {
          "action": "Open application",
          "expected_result": "User is authenticated",
          "data": "username=test_user",
          "position": 1
        }
      ],
      "attachments": [],
      "tags": ["orders", "e2e"],
      "_xray_issue_id": "10620",
      "_folder_path": "/Migra/Test Repository/Orders"
    }
  ]
}
```

### `transformed/attachments_map.json`
Maps Xray attachment IDs to Qase attachment objects:
```json
{
  "10135": {
    "filename": "test.png",
    "local_path": "attachments/test.png",
    "hash": null,
    "url": null
  }
}
```
Note: `hash` and `url` will be populated after uploading to Qase in the load phase.

### `transformed/runs.json` (if executions exist)
List of Qase run payloads:
```json
[
  {
    "title": "Test Execution Summary",
    "description": "Execution description",
    "cases": ["10620", "10662"],
    "start_time": null,
    "end_time": null,
    "_execution_issue_id": "12345",
    "_project_code": "PX"
  }
]
```

### `transformed/results.json` (if executions exist)
List of Qase result payloads:
```json
[
  {
    "title": "Test Execution Summary",
    "testops_id": 0,
    "execution": {
      "status": "passed",
      "duration": 5000,
      "start_time": 1704110400,
      "end_time": 1704110405
    },
    "message": "Test passed successfully",
    "attachments": [],
    "steps": null
  }
]
```

### `mappings/id_mappings.json`
Stores ID mappings for reference:
```json
{
  "10067": {
    "qase_id": "PX",
    "entity_type": "project",
    "metadata": {
      "name": "Project XM",
      "key": "XM"
    }
  }
}
```

## Transformation Process

The transform phase processes data in this order:

1. **Projects** → Creates Qase project payloads and generates project codes
2. **Folders → Suites** → Converts Xray folder hierarchy to Qase suite hierarchy
3. **Attachments** → Maps Xray attachment IDs to Qase format
4. **Test Cases** → Converts Xray tests to Qase cases with:
   - Jira document format → Markdown conversion
   - Step processing (action, expected result, data)
   - Attachment reference replacement
   - Label/tag extraction
5. **Executions → Runs** (if available) → Converts test executions to Qase runs
6. **Test Runs → Results** (if available) → Converts test run results to Qase results

## Logging

Transformation logs are saved to:
- `cache/[timestamp]/transform.log` (default)
- Or use `--log-file` to specify a custom location

## Troubleshooting

### Error: "No projects data found in cache"
- Ensure you've run the extract phase first
- Verify the cache directory contains `raw_data/projects.json`

### Error: "No test cases data found in cache"
- Ensure the extract phase completed successfully
- Verify `raw_data/test_cases.json` exists

### Missing suites or cases
- Check the logs for transformation errors
- Verify folder paths in test cases match folder data
- Check that project IDs match between entities

## Next Steps

After transformation completes successfully:
1. Review the transformed data in `transformed/` directory
2. Verify ID mappings in `mappings/id_mappings.json`
3. Proceed to the **load** phase to import data into Qase
