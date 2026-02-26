# Qase Migration Guide: TestRail to Qase Data Processing

This document provides a comprehensive guide to how data is processed and migrated from TestRail to Qase. It covers all data transformations, API endpoints, and processing steps to help developers create similar migration scripts (e.g., for Xray to Qase).

## Table of Contents

1. [Migration Overview](#migration-overview)
2. [Migration Flow](#migration-flow)
3. [Qase API Endpoints](#qase-api-endpoints)
4. [Data Processing Steps](#data-processing-steps)
5. [Data Structures](#data-structures)
6. [Adapting for Other Sources](#adapting-for-other-sources)

---

## Migration Overview

The migration follows a sequential, dependency-aware process:

1. **Users** → 2. **Projects** → 3. **Attachments** → 4. **Custom Fields** → 5. **Project Data** (parallel)

Project data includes: Configurations, Shared Steps, Milestones, Suites, Cases, and Runs/Results.

### Key Principles

- **Dependencies First**: Attachments and fields must be imported before cases/runs that reference them
- **Mapping Preservation**: All source IDs are mapped to Qase IDs for later reference
- **Bulk Operations**: Where possible, use bulk APIs for efficiency
- **Error Handling**: Failures are logged but don't stop the entire migration
- **Rate Limiting**: Throttled thread pools prevent API rate limit issues

### Important: Qase Python SDK Usage

**This migration uses the Qase Python SDK**, not raw HTTP API calls. The SDK provides:
- Type-safe models and API classes
- Automatic request/response handling
- Built-in error handling
- SSL certificate management

**Raw HTTP is only used for**:
- Cases with shared steps (bypasses SDK validation)
- External issues attachment (endpoint not yet in SDK)

All examples in this guide show SDK usage. See the [Qase Python SDK Usage](#qase-python-sdk-usage) section for initialization and examples.

---

## Migration Flow

### Step 1: Users Migration

**Purpose**: Map TestRail users to Qase users

**Process**:
1. Fetch all users from TestRail
2. Fetch all users from Qase
3. Match by email address
4. Create missing users in Qase (via SCIM API if available)
5. Store mapping: `mappings.users[testrail_user_id] = qase_user_id`

**Qase SDK Usage**:
- `AuthorsApi.get_authors()` - Get all Qase users
- SCIM API (raw HTTP) - Create user via SCIM (if SCIM token configured)

**Data Mapping**:
- TestRail user → Qase user (matched by email)
- Default user ID used if no match found

---

### Step 2: Projects Migration

**Purpose**: Create Qase projects and build project mapping

**Process**:
1. Fetch all projects from TestRail
2. Filter by status (active/completed/all) and import list
3. Generate short code from project name (e.g., "My Project" → "MP")
4. Create project in Qase
5. Store mapping: `mappings.project_map[testrail_project_id] = qase_project_code`

**Qase SDK Usage**:
- `ProjectsApi.create_project()` - Create project

**SDK Usage**:
```python
from qase.api_client_v1.api.projects_api import ProjectsApi
from qase.api_client_v1.models import ProjectCreate

api_instance = ProjectsApi(client)
project_data = ProjectCreate(
    title="Project Name",
    code="PROJCODE",
    description="Project description",
    settings={"runs": {"auto_complete": False}},
    access="all",
    group=group_id  # Optional
)
response = api_instance.create_project(project_create=project_data)
```

**Code Generation Logic**:
- Extract first letters of words: "My Test Project" → "MTP"
- Remove non-alphabetic characters
- Truncate to 10 characters
- Handle duplicates with letter postfix (A, B, C...)

---

### Step 3: Attachments Migration

**Purpose**: Upload all attachments to Qase and create attachment mapping

#### 3.1 Attachment List Retrieval

**Source**: TestRail web interface (not REST API)

**Process**:
1. Use parallel pagination with 24 worker threads
2. Fetch attachments via POST to `index.php?/attachments/overview/0`
3. Extract metadata: `{"id": attachment_id, "project_id": project_id}`
4. Continue until no more results or limit reached (120,000 max)

**Code**:
```python
def get_attachments_list(self):
    max_workers = 24
    attachments = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(self.fetch_data, offset) 
                   for offset in range(0, max_workers * page_size, page_size)]
        # Process results as they complete
```

**Response Format**:
```json
{
  "data": [
    {"id": 123, "project_id": 1},
    {"id": 124, "project_id": [1, 2]}  // Can be array if linked to multiple projects
  ]
}
```

#### 3.2 Individual Attachment Download

**Process**:
1. Download attachment content from TestRail using `get_attachment(id)`
2. Extract filename from HTTP `Content-Disposition` header
3. Handle UTF-8 encoded filenames: `filename*=UTF-8''encoded_name`

**Filename Extraction**:
```python
def _get_attachment_meta(self, data) -> tuple:
    """Extract filename and content from attachment data."""
    # Pattern: filename*=UTF-8''encoded_name
    match = re.search(r"filename\*=UTF-8''(.+?)(?:;|$)", 
                      data.headers.get('Content-Disposition', ''), 
                      re.IGNORECASE)
    filename = unquote(match.group(1)) if match else "attachment"
    return (filename, data.content)  # Returns tuple: (filename, bytes)
```

**Content-Disposition Header Examples**:
- `Content-Disposition: attachment; filename*=UTF-8''image.png`
- `Content-Disposition: attachment; filename="test file.jpg"`
- Fallback: `"attachment"` if no filename found

#### 3.3 Bulk Upload to Qase

**Process**:
1. Process all attachments in parallel using `asyncio.TaskGroup`
2. For each attachment:
   - Validate project association
   - Map TestRail project_id to Qase project code
   - Download attachment content
   - Extract filename
   - Upload to Qase
   - Store mapping

**SDK Usage**:
```python
from qase.api_client_v1.api.attachments_api import AttachmentsApi

api_instance = AttachmentsApi(client)
# attachment_data is tuple: (filename, content_bytes)
response = api_instance.upload_attachment(
    code="PROJ", 
    file=[attachment_data]  # List of tuples
)

if response.status:
    attachment_hash = response.result[0].hash
    filename = response.result[0].filename
    url = response.result[0].url
    # Store in mappings
    mappings.attachments_map[testrail_id] = {
        "hash": attachment_hash,
        "filename": filename,
        "url": url
    }
```

**Error Handling**:
- **413 Error (File Too Large)**: Logs file size and continues
- **Other Errors**: Logs error with file details, continues migration
- **Missing Project**: Skips attachment, logs warning

**Response Structure**:
```python
{
    "hash": "abc123def456...",  # Qase attachment hash (used for references)
    "filename": "original_filename.png",
    "url": "https://qase.io/attachments/abc123..."
}
```

#### 3.4 Attachment Mapping Storage

**Structure**:
```python
mappings.attachments_map[testrail_attachment_id] = {
    "hash": "qase_hash",      # Used in attachments arrays and markdown links
    "filename": "image.png",   # Original filename
    "url": "https://..."       # Qase attachment URL
}
```

**Key Points**:
- Key is TestRail attachment ID (string)
- Hash is used for all references in Qase
- Filename preserved for display in markdown links
- URL used for markdown link generation

#### 3.5 Failover Mechanism

**When Used**: Attachment referenced in case/result but not found in `attachments_map`

**Process**:
1. Detect missing attachment during text processing
2. Download attachment from TestRail on-demand
3. Upload to Qase immediately
4. Add to `attachments_map` for future use
5. Continue with replacement

**Code**:
```python
def replace_failover(self, attachment_id: str, code: str, result_id: str = None, test_id: str = None):
    """Upload attachment on-demand if not found in map."""
    # Download from TestRail
    meta = self._get_attachment_meta(self.testrail.get_attachment(attachment_id))
    # Upload to Qase
    qase_attachment = self.qase.upload_attachment(code, meta)
    if qase_attachment:
        # Add to map for future use
        self.mappings.attachments_map[attachment_id] = qase_attachment
```

**Use Cases**:
- Attachments referenced in results but not in bulk list
- Attachments added after bulk import
- Edge cases where attachment wasn't captured initially

#### 3.6 Attachment Reference Detection and Replacement

**Patterns Detected**:
1. **Markdown**: `![](index.php?/attachments/get/123)`
2. **HTML img tag**: `<img src="index.php?/attachments/get/123">`
3. **HTML data attributes**: `data-attachment-id="123"` or `data-original-src="index.php?/attachments/get/123"`

**Regex Patterns**:
```python
_MARKDOWN_PATTERN = r'!\[\]\(index\.php\?/attachments/get/([a-f0-9-]{1,64})\)'
_HTML_IMG_PATTERN = r'<img[^>]*(?:src=["\']index\.php\?/attachments/get/([a-f0-9-]{1,64})["\']|data-attachment-id=["\']([a-f0-9-]{1,64})["\'])[^>]*>'
```

**Replacement Process**:
1. Extract attachment IDs from text
2. Look up Qase hash in `attachments_map`
3. Replace with Qase markdown format:
   - **Images**: `![filename](qase_url)`
   - **Videos**: `[filename](qase_url)` (link format, not image)

**Video Detection**:
```python
_VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv', ...]

def _is_video_file(self, filename: str) -> bool:
    return filename.lower().endswith(tuple(self._VIDEO_EXTENSIONS))
```

**Replacement Examples**:
- `![](index.php?/attachments/get/123)` → `![image.png](https://qase.io/attachments/abc123)`
- `<img src="index.php?/attachments/get/456">` → `![video.mp4](https://qase.io/attachments/def456)`
- Video files use link format: `[video.mp4](url)` instead of `![video.mp4](url)`

#### 3.7 Attachment Collection for Cases/Results

**Two Types of Attachments**:

1. **Case-Level Attachments**: Explicitly attached to case
   - Retrieved via `get_attachments_for_case(case_id)` API
   - Added to case's `attachments` array as Qase hashes
   - Deduplicated with inline attachments

2. **Inline Attachments**: Referenced in text fields
   - Extracted from description, preconditions, steps, custom fields
   - Replaced in text with Qase markdown links
   - Collected hashes added to `attachments` array
   - Prevents "attachment not found" errors

**Deduplication Logic**:
```python
# Collect inline attachment IDs from text
inline_attachment_ids = extract_from_text_fields(case)

# Get case-level attachments
case_level_attachments = get_attachments_for_case(case_id)

# Skip case-level if already in inline (don't add twice)
for attachment in case_level_attachments:
    if attachment_id not in inline_attachment_ids:
        data['attachments'].append(qase_hash)
```

**ID Normalization**:
- Removes `E_` prefix if present: `E_123` → `123`
- Handles both string and integer IDs
- Normalizes before lookup in `attachments_map`

---

### Step 4: Custom Fields Migration

**Purpose**: Create custom fields in Qase and map field values

#### 4.1 Field Discovery and Filtering

**Process**:
1. Fetch all custom fields from TestRail
2. Fetch existing custom fields from Qase
3. Filter fields to import based on config (`tests.fields`)
4. Detect step fields (fields containing test steps)

**Step Field Detection**:
```python
# Step fields have specific config options
if field.get('configs'):
    for config in field['configs']:
        options = config.get('options', {})
        # Check for step-specific options
        if (options.get('has_expected') is not None or 
            options.get('has_additional') is not None or
            options.get('has_reference') is not None):
            # This is a step field
            mappings.step_fields.append(field['name'])
```

**Field Filtering**:
- Only import fields in `tests.fields` config (if specified)
- Skip inactive fields (`is_active: false`)
- Skip fields with unsupported types

#### 4.2 Field Configuration Analysis

**TestRail Field Structure**:
```python
field = {
    "id": 123,
    "name": "custom_field_name",
    "label": "Field Label",
    "type_id": 6,  # TestRail type
    "configs": [
        {
            "context": {
                "is_global": True/False,
                "project_ids": [1, 2, 3]  # If not global
            },
            "options": {
                "is_required": True/False,
                "default_value": "...",
                "items": "1,Option 1\n2,Option 2\n3,Option 3"  # For dropdown/multiselect
            }
        }
    ]
}
```

**Configuration Scenarios**:

1. **Single Global Config**: One config, `is_global: true`
   - Create single global field
   - Enabled for all projects

2. **Multiple Configs**: Multiple configs with different project scopes
   - Create project-specific fields: `FieldName_PROJ1`, `FieldName_PROJ2`
   - Each field enabled only for its project

3. **Single Project Config**: One config, `is_global: false`
   - Create field for specific projects
   - Use `projects_codes` array

#### 4.3 Field Creation Process

**Check Existing Fields**:
```python
# Match by title AND type
for qase_field in qase_fields:
    if (qase_field.title == field['label'] and 
        qase_type == qase_field.type):
        # Field exists, check if update needed
        needs_update, update_data = check_field_update_needed(...)
```

**Update Scenarios**:
1. **Missing Values**: Dropdown/multiselect missing options
2. **Missing Projects**: Field not enabled for all expected projects
3. **Value Mapping**: Need to refresh `tr_key_to_qase_id` mapping

**Create New Field**:
```python
from qase.api_client_v1.api.custom_fields_api import CustomFieldsApi
from qase.api_client_v1.models import CustomFieldCreate, CustomFieldCreateValueInner

# Prepare field data
data = {
    'title': field['label'],
    'entity': 0,  # 0=case, 1=run, 2=defect
    'type': mappings.custom_fields_type[field['type_id']],
    'value': [],  # For dropdown/multiselect
    'is_filterable': True,
    'is_visible': True,
    'is_required': config['options'].get('is_required', False),
    'is_enabled_for_all_projects': is_global,
    'projects_codes': project_codes if not is_global else None
}

# For dropdown/multiselect, parse items
if field['type_id'] in [6, 12]:  # Selectbox or Multiselect
    items = config['options']['items']  # "1,Option 1\n2,Option 2"
    values = split_values(items)  # {"1": "Option 1", "2": "Option 2"}
    
    next_id = 1
    for tr_key, tr_title in values.items():
        data['value'].append(
            CustomFieldCreateValueInner(id=next_id, title=tr_title)
        )
        field['qase_values'][next_id] = tr_title
        next_id += 1

# Create field
api_instance = CustomFieldsApi(client)
response = api_instance.create_custom_field(
    custom_field_create=CustomFieldCreate(**data)
)
field['qase_id'] = response.result.id
```

**Field Type Mapping**:
```python
TestRail Type ID → Qase Type ID:
1 → 1  # String
2 → 0  # Number
3 → 2  # Text
4 → 7  # URL
5 → 4  # Checkbox
6 → 3  # Selectbox
7 → 8  # User
8 → 9  # Date
12 → 6 # Multiselect
```

#### 4.4 Value Mapping Creation

**Purpose**: Map TestRail field values to Qase field values for dropdown/multiselect fields

**Process**:
1. Parse TestRail items string: `"1,Option 1\n2,Option 2"`
2. Extract Qase values from created field
3. Match by title (case-insensitive, trimmed)
4. Create bidirectional mapping

**TestRail Items Format**:
```
"1,Option One\n2,Option Two\n3,Option Three"
```
- Format: `key,title` per line
- Key is TestRail's internal ID
- Title is display value

**Mapping Creation**:
```python
def _create_tr_key_to_qase_id_mapping(self, field):
    # Parse TestRail values
    tr_values = {}
    for line in items.split('\n'):
        if ',' in line:
            key, title = line.split(',', 1)
            tr_values[key.strip()] = title.strip()
    
    # Get Qase values (from created field)
    qase_values = field['qase_values']  # {qase_id: "title"}
    
    # Match by title and create mapping
    field['tr_key_to_qase_id'] = {}
    for tr_key, tr_title in tr_values.items():
        for qase_id, qase_title in qase_values.items():
            if tr_title.strip().lower() == qase_title.strip().lower():
                field['tr_key_to_qase_id'][tr_key] = qase_id
                break
```

**Resulting Mappings**:
```python
field['qase_values'] = {
    1: "Option One",      # Qase ID → Title
    2: "Option Two",
    3: "Option Three"
}

field['tr_key_to_qase_id'] = {
    "1": 1,  # TestRail key → Qase ID
    "2": 2,
    "3": 3
}
```

**Why Both Mappings?**:
- `qase_values`: Used for display/logging
- `tr_key_to_qase_id`: Used when importing cases (TestRail value → Qase ID)

#### 4.5 Field Update Logic

**When Update Needed**:
1. **Missing Values**: New options in TestRail not in Qase field
2. **Missing Projects**: Field not enabled for all expected projects
3. **Mapping Refresh**: Need to rebuild value mappings

**Update Process**:
```python
# Check what's missing
needs_update, update_data = check_field_update_needed(field, qase_field, mappings)

if needs_update:
    if 'missing_values' in update_data:
        # Add new values to existing field
        existing_values = qase_field.value
        next_id = len(existing_values) + 1
        for new_value in update_data['missing_values']:
            existing_values.append({
                'id': next_id,
                'title': new_value
            })
            next_id += 1
        update_payload['value'] = existing_values
    
    if 'missing_projects' in update_data:
        # Add projects to field
        existing_projects = qase_field.projects_codes or []
        update_payload['projects_codes'] = existing_projects + update_data['missing_projects']
    
    # Update field
    api_instance.update_custom_field(field_id, update_payload)
```

#### 4.6 Special Fields

**Refs Field**:
- Type: Text (type 2)
- Purpose: Store case references
- Global: Enabled for all projects
- Auto-created if `tests.refs.enable: true`

**TestRail Original ID Field**:
- Type: String (type 1)
- Purpose: Preserve original TestRail case IDs
- Global: Enabled for all projects
- Auto-created if `tests.preserve_ids: false`

**Estimate Field**:
- Type: String (type 1)
- Purpose: Store time estimates
- Global: Enabled for all projects
- Always created

#### 4.7 Field Value Processing During Case Import

**Process**:
1. Detect field type (dropdown/multiselect vs others)
2. Look up value mapping (`tr_key_to_qase_id`)
3. Convert TestRail value to Qase value
4. Handle single vs multiple values

**For Dropdown (type_id 6)**:
```python
# TestRail value: "2" (key) or 2 (integer)
testrail_value = case['custom_field_name']

# Look up Qase ID
if field.get('tr_key_to_qase_id') and str(testrail_value) in field['tr_key_to_qase_id']:
    qase_id = field['tr_key_to_qase_id'][str(testrail_value)]
    case_data['custom_field'][str(field['qase_id'])] = str(qase_id)
else:
    # Fallback: use value directly
    case_data['custom_field'][str(field['qase_id'])] = str(testrail_value)
```

**For Multiselect (type_id 12)**:
```python
# TestRail value: ["1", "2", "3"] or "1,2,3"
testrail_values = case['custom_field_name']
if isinstance(testrail_values, str):
    testrail_values = testrail_values.split(',')

# Convert each value to Qase ID
qase_ids = []
for tr_value in testrail_values:
    if field.get('tr_key_to_qase_id') and str(tr_value) in field['tr_key_to_qase_id']:
        qase_ids.append(str(field['tr_key_to_qase_id'][str(tr_value)]))
    else:
        qase_ids.append(str(tr_value))

# Join with comma for Qase API
case_data['custom_field'][str(field['qase_id'])] = ','.join(qase_ids)
```

**For Other Types**:
- **String/Number**: Use value directly
- **User**: Map TestRail user ID → Qase user ID
- **Date**: Convert format if needed
- **Checkbox**: Boolean value
- **Text**: String value

**Project-Specific Fields**:
- Look for field with key: `field_name_PROJCODE`
- If found, use project-specific field
- Otherwise, fall back to global field

**Step Fields**:
- Detected by `has_expected`, `has_additional`, or `has_reference` options
- Processed as test steps, not custom fields
- Can contain shared step references
- Processed before custom field logic

#### 4.8 Field Storage Structure

**In Mappings**:
```python
mappings.custom_fields[field_name] = {
    "id": testrail_field_id,
    "name": "custom_field_name",
    "label": "Field Label",
    "type_id": 6,  # TestRail type
    "qase_id": 123,  # Qase field ID
    "qase_values": {  # Qase ID → Title
        1: "Option 1",
        2: "Option 2"
    },
    "tr_key_to_qase_id": {  # TestRail key → Qase ID
        "1": 1,
        "2": 2
    },
    "configs": [...],  # TestRail configurations
    "project_id": 1,  # For project-specific fields
    "project_code": "PROJ"  # For project-specific fields
}
```

**Project-Specific Field Keys**:
- Global: `mappings.custom_fields["field_name"]`
- Project-specific: `mappings.custom_fields["field_name_PROJCODE"]`

---

### Step 5: Project Data Migration (Parallel)

Each project is processed independently in parallel threads.

#### 5.1 Configurations

**Purpose**: Import test configurations (environments, browsers, etc.)

**Process**:
1. Fetch configurations from TestRail (grouped by configuration groups)
2. For each group:
   - Create configuration group in Qase
   - Create each configuration in the group
3. Store mapping: `mappings.configurations[project_code][testrail_config_id] = qase_config_id`

**Qase SDK Usage**:
- `ConfigurationsApi.create_configuration_group()` - Create configuration group
- `ConfigurationsApi.create_configuration()` - Create configuration

**SDK Usage**:
```python
from qase.api_client_v1.api.configurations_api import ConfigurationsApi
from qase.api_client_v1.models import ConfigurationGroupCreate, ConfigurationCreate

api_instance = ConfigurationsApi(client)

# Create group
group_data = ConfigurationGroupCreate(title="Browsers")
group_response = api_instance.create_configuration_group(code="PROJ", configuration_group_create=group_data)
group_id = group_response.result.id

# Create configuration
config_data = ConfigurationCreate(title="Chrome", group_id=group_id)
config_response = api_instance.create_configuration(code="PROJ", configuration_create=config_data)
```

---

#### 5.2 Shared Steps

**Purpose**: Import reusable test steps

**Process**:
1. Fetch shared steps from TestRail
2. For each shared step:
   - Process step content (replace attachments, convert HTML to markdown)
   - Create shared step in Qase
   - Store mapping: `mappings.shared_steps[project_code][testrail_id] = qase_hash`

**Qase SDK Usage**:
- `SharedStepsApi.create_shared_step()` - Create shared step

**SDK Usage**:
```python
from qase.api_client_v1.api.shared_steps_api import SharedStepsApi
from qase.api_client_v1.models import SharedStepCreate, SharedStepContentCreate

api_instance = SharedStepsApi(client)
shared_step_data = SharedStepCreate(
    title="Login Steps",
    steps=[
        SharedStepContentCreate(
            action="Navigate to login page",
            expected_result="Login page displayed"
        )
    ]
)
response = api_instance.create_shared_step(code="PROJ", shared_step_create=shared_step_data)
shared_step_hash = response.result.hash  # Returns hash used to reference shared step in cases
```

**Data Processing**:
- Replace attachment references with Qase markdown links
- Convert HTML to markdown
- Format links as markdown

---

#### 5.3 Milestones

**Purpose**: Import project milestones

**Process**:
1. Fetch milestones from TestRail
2. For each milestone:
   - Create milestone in Qase
   - Handle nested milestones (prefix parent name)
   - Store mapping: `mappings.milestones[project_code][testrail_id] = qase_id`

**Qase SDK Usage**:
- `MilestonesApi.create_milestone()` - Create milestone

**SDK Usage**:
```python
from qase.api_client_v1.api.milestones_api import MilestonesApi
from qase.api_client_v1.models import MilestoneCreate

api_instance = MilestonesApi(client)
milestone_data = MilestoneCreate(
    title="Sprint 1",
    description="First sprint",
    status="active",  # or "completed"
    due_date="2024-01-31"
)
response = api_instance.create_milestone(code="PROJ", milestone_create=milestone_data)
milestone_id = response.result.id
```

**Status Mapping**:
- TestRail `is_completed: true` → Qase `status: "completed"`
- TestRail `is_completed: false` → Qase `status: "active"`

---

#### 5.4 Suites

**Purpose**: Import test suites (hierarchical structure)

**Process**:
1. Fetch suites/sections from TestRail
2. Create suites in Qase maintaining hierarchy
3. Store mapping: `mappings.suites[project_code][testrail_suite_id] = qase_suite_id`

**Qase SDK Usage**:
- `SuitesApi.create_suite()` - Create suite

**SDK Usage**:
```python
from qase.api_client_v1.api.suites_api import SuitesApi
from qase.api_client_v1.models import SuiteCreate

api_instance = SuitesApi(client)
suite_data = SuiteCreate(
    title="Suite Name",
    description="Suite description",
    preconditions="",
    parent_id=123  # Optional, for nested suites
)
response = api_instance.create_suite(code="PROJ", suite_create=suite_data)
suite_id = response.result.id
```

**Suite Mode Handling**:
- Mode 2/3: TestRail suites → Qase suites, sections → nested suites
- Mode 1: All sections become top-level suites

**Data Processing**:
- Replace attachment references
- Convert HTML to markdown
- Format links as markdown

---

#### 5.5 Cases (Test Cases)

**Purpose**: Import test cases with all metadata

**Process**:
1. Fetch cases from TestRail (paginated, per suite)
2. For each case:
   - Process case data (attachments, custom fields, steps)
   - Handle shared steps references
   - Collect inline attachments
   - Prepare case payload
3. Bulk create cases in Qase
4. Store ID mapping: `mappings.case_id_mapping[testrail_id] = qase_id`

**Qase SDK Usage**:
- `CasesApi.bulk()` - Bulk create cases (for cases without shared steps)
- Raw HTTP client - Bulk create cases with shared steps (bypasses SDK validation)

**SDK Usage** (Bulk):
```python
from qase.api_client_v1.api.cases_api import CasesApi
from qase.api_client_v1.models import TestCasebulk, TestCasebulkCasesInner, TestStepCreate

api_instance = CasesApi(client)
cases = [
    TestCasebulkCasesInner(
        id=123,  # Optional, for preserve_ids
        title="Test Case Title",
        description="Case description",
        preconditions="Preconditions",
        postconditions="Postconditions",
        severity=2,
        priority=1,
        type=1,
        behavior=1,
        automation=0,
        status=1,
        suite_id=456,
        milestone_id=789,
        author_id=1,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-02T00:00:00Z",
        steps=[
            TestStepCreate(
                action="Step action",
                expected_result="Expected result",
                data="",
                position=1
            )
        ],
        attachments=["hash1", "hash2"],  # Qase attachment hashes
        custom_field={
            "123": "value",  # Custom field ID → value
            "456": [1, 2]    # For multiselect
        },
        params=[],  # Test parameters
        is_flaky=0
    )
]
# For cases WITHOUT shared steps
response = api_instance.bulk(code="PROJ", test_casebulk=TestCasebulk(cases=cases))

# For cases WITH shared steps, use raw HTTP client (SDK doesn't support shared step dicts)
# See QaseApiClient.create_cases_bulk() for implementation
```

**Case Data Processing**:

1. **ID Handling**:
   - If `preserve_ids=true`: Use original ID if ≤ 2^31-1, else hash it
   - If `preserve_ids=false`: Generate new ID or hash original

2. **Attachments**:
   - Extract inline attachments from text fields (description, preconditions, steps)
   - Get case-level attachments via API
   - Deduplicate (don't add inline attachments as case-level)
   - Replace attachment references in text with Qase markdown links
   - Collect attachment hashes for `attachments` array

3. **Custom Fields**:
   - Map TestRail custom field values to Qase field IDs
   - Handle dropdown/multiselect value mapping
   - Process step fields (fields containing test steps)
   - Handle BDD scenario fields

4. **Steps**:
   - Process regular steps (action, expected, data)
   - Handle shared step references (replace TestRail ID with Qase hash)
   - Process step fields (custom fields containing steps)

5. **Text Processing**:
   - Replace attachment references: `![](index.php?/attachments/get/123)` → `![filename](qase_url)`
   - Convert HTML to markdown
   - Format links as markdown

6. **External Issues** (JIRA):
   - Collect JIRA issue references
   - After case creation, attach via external issues API

**Special Handling**:
- Cases with shared steps: Use direct HTTP API (bypasses SDK validation)
- Step fields: Detected by config options (`has_expected`, `has_additional`, `has_reference`)
- BDD scenarios: Parsed from JSON custom field

**Qase SDK Usage** (External Issues):
- Raw HTTP client - Attach external issues (endpoint not yet in SDK)

**SDK Usage** (Raw HTTP - endpoint not in SDK yet):
```python
# Use raw HTTP client since this endpoint isn't in SDK yet
from src.api.qase import QaseApiClient

api_client = QaseApiClient(base_url=api_host_v1, api_token=token, logger=logger)
payload = {
    "type": "jira-cloud",  # or "jira-server"
    "links": [
        {
            "case_id": 123,
            "external_issues": ["PROJ-456", "PROJ-789"]
        }
    ]
}
response = api_client._request('POST', f'/case/{code}/external-issue/attach', json=payload)
```

---

#### 5.6 Runs and Results

**Purpose**: Import test runs and execution results

**Process**:
1. Build runs index (from runs and test plans)
2. For each run:
   - Create run in Qase
   - Fetch results from TestRail
   - Process results (attachments, comments, step results)
   - Bulk create results in Qase
   - Complete run if it was completed in TestRail

**Qase SDK Usage**:
- `RunsApi.create_run()` - Create run
- `ResultsApi.create_result_bulk()` - Bulk create results (API v1)
- `ResultsApi.create_results_v2()` - Bulk create results (API v2, recommended)
- `RunsApi.complete_run()` - Complete run

**SDK Usage** (Create Run):
```python
from qase.api_client_v1.api.runs_api import RunsApi
from qase.api_client_v1.models import RunCreate

api_instance = RunsApi(client)
run_data = RunCreate(
    title="Test Run Name",
    description="Run description",
    start_time="2024-01-01 10:00:00",
    end_time="2024-01-01 11:00:00",  # Optional
    author_id=1,
    cases=[123, 456, 789],  # Case IDs included in run
    configurations=[1, 2],   # Configuration IDs
    milestone_id=10         # Optional
)
response = api_instance.create_run(code="PROJ", run_create=run_data)
run_id = response.result.id
```

**SDK Usage** (Create Results - API v2):
```python
from qase.api_client_v2.api.results_api import ResultsApi as ResultsApiV2
from qase.api_client_v2.models import (
    CreateResultsRequestV2, ResultCreate, ResultExecution,
    ResultStep, ResultStepData, ResultStepExecution, ResultStepStatus
)

api_instance = ResultsApiV2(client_v2)
results = [
    ResultCreate(
        title="Test Case Title",
        testops_id=123,  # Qase case ID
        execution=ResultExecution(
            status="passed",  # passed, failed, blocked, skipped
            duration=5000,    # milliseconds
            start_time=1704110400,  # Unix timestamp
            end_time=1704110405
        ),
        message="Test comment/result message",
        attachments=["hash1", "hash2"],  # Qase attachment hashes
        steps=[  # Optional, for step-by-step results
            ResultStep(
                data=ResultStepData(
                    action="Step action",
                    expected_result="Expected result"
                ),
                execution=ResultStepExecution(
                    status=ResultStepStatus.PASSED,
                    comment="Step execution comment"
                )
            )
        ]
    )
]
request = CreateResultsRequestV2(results=results)
response = api_instance.create_results_v2(
    project_code="PROJ",
    run_id=run_id,
    create_results_request_v2=request
)
```

**Result Data Processing**:

1. **Status Mapping**:
   ```python
   TestRail Status ID → Qase Status:
   1 → "passed"
   2 → "blocked"
   3 → "skipped" (untested)
   4 → "failed"
   5 → "failed"
   ```

2. **Attachments**:
   - Extract from result comments (inline references)
   - Extract from `attachment_ids` array
   - Replace references in comments with Qase markdown links
   - Collect hashes for `attachments` array

3. **Comments**:
   - Replace attachment references
   - Convert HTML to markdown
   - Format links as markdown

4. **Step Results**:
   - Map TestRail step status to Qase step status
   - Include step action, expected result, and execution comment
   - Only include steps that were executed (have status)

5. **Time Handling**:
   - Convert elapsed time to milliseconds
   - Calculate start_time from `created_on - elapsed`
   - Ensure `end_time >= start_time`

**Result Filtering**:
- Skip results with `status_id == 3` (untested)
- Only include results for cases that exist in Qase

---

## Qase Python SDK Usage

### Overview

**Important**: This migration uses the **Qase Python SDK** (`qase-api-client-v1` and `qase-api-client-v2`), not raw HTTP API calls. The SDK provides:
- Type-safe models and API classes
- Automatic request/response handling
- Built-in error handling
- SSL certificate management

### SDK Installation

```bash
pip install qase-api-client-v1 qase-api-client-v2
```

### SDK Initialization

```python
from qase.api_client_v1.api_client import ApiClient
from qase.api_client_v1.configuration import Configuration
from qase.api_client_v2.api_client import ApiClient as ApiClientV2
from qase.api_client_v2.configuration import Configuration as ConfigurationV2
import certifi

# API v1 Configuration
configuration = Configuration()
configuration.api_key['TokenAuth'] = api_token
configuration.host = 'https://api.qase.io/v1'  # or 'https://api-<domain>/v1' for enterprise
configuration.ssl_ca_cert = certifi.where()

client = ApiClient(configuration)

# API v2 Configuration (for results)
configuration_v2 = ConfigurationV2()
configuration_v2.api_key['TokenAuth'] = api_token
configuration_v2.host = 'https://api.qase.io/v2'  # or 'https://api-<domain>/v2' for enterprise
configuration_v2.ssl_ca_cert = certifi.where()

client_v2 = ApiClientV2(configuration_v2)
```

### SDK API Classes and Models

The migration uses these SDK components:

**API v1 Classes**:
- `AuthorsApi` - User management
- `ProjectsApi` - Project operations
- `CustomFieldsApi` - Custom field operations
- `SystemFieldsApi` - System field queries
- `SuitesApi` - Suite operations
- `CasesApi` - Case operations
- `RunsApi` - Run operations
- `ResultsApi` - Result operations (v1)
- `AttachmentsApi` - Attachment uploads
- `MilestonesApi` - Milestone operations
- `ConfigurationsApi` - Configuration operations
- `SharedStepsApi` - Shared step operations

**API v2 Classes**:
- `ResultsApi` - Result operations (v2, recommended)

**SDK Models** (v1):
- `ProjectCreate` - Create project
- `SuiteCreate` - Create suite
- `TestCasebulk` - Bulk create cases
- `TestCasebulkCasesInner` - Individual case in bulk
- `TestStepCreate` - Create test step
- `RunCreate` - Create run
- `ResultCreateBulk` - Bulk create results
- `MilestoneCreate` - Create milestone
- `CustomFieldCreate` - Create custom field
- `CustomFieldCreateValueInner` - Custom field value
- `ConfigurationCreate` - Create configuration
- `ConfigurationGroupCreate` - Create configuration group
- `SharedStepCreate` - Create shared step
- `SharedStepContentCreate` - Shared step content

**SDK Models** (v2):
- `CreateResultsRequestV2` - Bulk create results request
- `ResultCreate` - Individual result
- `ResultExecution` - Result execution details
- `ResultStep` - Result step
- `ResultStepData` - Step data (action/expected)
- `ResultStepExecution` - Step execution details
- `ResultStepStatus` - Step status enum

### SDK Usage Examples

**Create Project**:
```python
from qase.api_client_v1.api.projects_api import ProjectsApi
from qase.api_client_v1.models import ProjectCreate

api_instance = ProjectsApi(client)
project_data = ProjectCreate(
    title="Project Name",
    code="PROJCODE",
    description="Description",
    settings={"runs": {"auto_complete": False}},
    access="all"
)
response = api_instance.create_project(project_create=project_data)
if response.status:
    project_code = response.result.code
```

**Create Cases (Bulk)**:
```python
from qase.api_client_v1.api.cases_api import CasesApi
from qase.api_client_v1.models import TestCasebulk, TestCasebulkCasesInner, TestStepCreate

api_instance = CasesApi(client)
cases = [
    TestCasebulkCasesInner(
        title="Test Case",
        description="Description",
        steps=[
            TestStepCreate(
                action="Step action",
                expected_result="Expected result"
            )
        ]
    )
]
response = api_instance.bulk(code="PROJ", test_casebulk=TestCasebulk(cases=cases))
```

**Upload Attachment**:
```python
from qase.api_client_v1.api.attachments_api import AttachmentsApi

api_instance = AttachmentsApi(client)
# attachment_data is tuple: (filename, content_bytes)
response = api_instance.upload_attachment(code="PROJ", file=[attachment_data])
if response.status:
    attachment_hash = response.result[0].hash
```

**Create Results (v2)**:
```python
from qase.api_client_v2.api.results_api import ResultsApi as ResultsApiV2
from qase.api_client_v2.models import CreateResultsRequestV2, ResultCreate, ResultExecution

api_instance = ResultsApiV2(client_v2)
results = [
    ResultCreate(
        title="Test Case Title",
        testops_id=123,  # Qase case ID
        execution=ResultExecution(
            status="passed",
            duration=5000,
            start_time=1704110400,
            end_time=1704110405
        ),
        message="Test comment"
    )
]
request = CreateResultsRequestV2(results=results)
response = api_instance.create_results_v2(
    project_code="PROJ",
    run_id=456,
    create_results_request_v2=request
)
```

### Raw HTTP Client (Edge Cases Only)

A raw HTTP client (`QaseApiClient`) is used only for:
1. **Cases with shared steps** - Bypasses SDK validation that doesn't support shared step dicts
2. **External issues attachment** - Endpoint not yet in SDK

**When to use raw HTTP**:
- Only when SDK doesn't support the operation
- When SDK validation is too strict for your use case
- For endpoints not yet available in SDK

**Example**:
```python
# Only for cases with shared steps or external issues
from src.api.qase import QaseApiClient

api_client = QaseApiClient(base_url=api_host_v1, api_token=token, logger=logger)
# Use for specific edge cases only
```

### Rate Limiting
- Cloud: ~230 requests per 10 seconds
- Enterprise: Varies by instance
- Use throttled thread pools to manage rate limits
- SDK handles retries automatically for some errors

---

## Data Processing Steps

### Attachment Processing

**Patterns Detected**:
- Markdown: `![](index.php?/attachments/get/{id})`
- HTML: `<img src="index.php?/attachments/get/{id}">`
- HTML: `data-attachment-id="{id}"`

**Replacement**:
- Images: `![filename](qase_url)`
- Videos: `[filename](qase_url)` (link format)

**Process**:
1. Extract attachment IDs from text
2. Look up Qase hash in `attachments_map`
3. Replace with Qase markdown format
4. Collect hashes for `attachments` array

### HTML to Markdown Conversion

- Preserve structure (headings, lists, links)
- Convert `<img>` tags to markdown images
- Convert `<a>` tags to markdown links
- Preserve code blocks and tables

### Link Formatting

- Convert TestRail case links to Qase case links
- Format: `[text](qase_case_url)`
- Preserve external links as-is

### Custom Field Value Mapping

**For Dropdown/Multiselect**:
1. Get TestRail field value (key or array of keys)
2. Look up Qase ID in `tr_key_to_qase_id` mapping
3. Use Qase ID in case payload

**For Other Types**:
- String/Number: Use value directly
- User: Map TestRail user ID to Qase user ID
- Date: Convert format if needed

### Step Processing

**Regular Steps**:
- Extract action, expected result, data
- Process attachments in step content
- Convert HTML to markdown

**Shared Steps**:
- Replace TestRail shared step ID with Qase hash
- Format: `{"shared": "qase_hash"}`

**Step Fields**:
- Parse JSON/array format
- Extract steps from custom field
- Process each step's content, expected, additional_info

---

## Data Structures

### Mappings Object

```python
class Mappings:
    users: Dict[int, int]  # testrail_user_id → qase_user_id
    project_map: Dict[int, str]  # testrail_project_id → qase_project_code
    attachments_map: Dict[str, dict]  # testrail_attachment_id → qase_attachment_object
    custom_fields: Dict[str, dict]  # field_name → field_data
    suites: Dict[str, Dict[int, int]]  # project_code → {testrail_suite_id → qase_suite_id}
    milestones: Dict[str, Dict[int, int]]  # project_code → {testrail_milestone_id → qase_milestone_id}
    configurations: Dict[str, Dict[int, int]]  # project_code → {testrail_config_id → qase_config_id}
    shared_steps: Dict[str, Dict[int, str]]  # project_code → {testrail_id → qase_hash}
    case_id_mapping: Dict[int, int]  # testrail_case_id → qase_case_id
    result_statuses: Dict[int, str]  # testrail_status_id → qase_status_slug
    priorities: Dict[int, int]  # testrail_priority_id → qase_priority_id
    types: Dict[int, int]  # testrail_type_id → qase_type_id
    case_statuses: Dict[int, int]  # testrail_case_status_id → qase_case_status_id
```

### Field Data Structure

```python
field_data = {
    "id": testrail_field_id,
    "name": "custom_field_name",
    "label": "Field Label",
    "type_id": 6,  # TestRail type
    "qase_id": 123,  # Qase field ID
    "qase_values": {  # For dropdown/multiselect
        1: "Option 1",
        2: "Option 2"
    },
    "tr_key_to_qase_id": {  # TestRail key → Qase ID mapping
        "1": 1,
        "2": 2
    },
    "configs": [...]  # TestRail field configurations
}
```

### Attachment Object Structure

```python
attachment_object = {
    "hash": "abc123...",  # Qase attachment hash
    "filename": "image.png",
    "url": "https://qase.io/..."
}
```

---

## Adapting for Other Sources (e.g., Xray)

To adapt this migration for another source system (like Xray), follow these steps:

### 1. Understand Source System Structure

- Map Xray entities to Qase entities:
  - Xray Tests → Qase Cases
  - Xray Test Executions → Qase Runs/Results
  - Xray Preconditions → Qase Shared Steps or Case Preconditions
  - Xray Test Sets → Qase Suites
  - Xray Attachments → Qase Attachments

### 2. Implement Source API Client

Create a client similar to `TestrailApiClient`:
- Fetch projects, cases, runs, results, attachments
- Handle pagination
- Map Xray data structures to internal format

### 3. Adapt Data Processing

**For Cases**:
- Map Xray test structure to Qase case structure
- Convert Xray steps to Qase steps format
- Handle Xray custom fields → Qase custom fields
- Process Xray attachments → Qase attachments

**For Runs/Results**:
- Map Xray test execution → Qase run
- Map Xray test run result → Qase result
- Convert Xray status → Qase status
- Process Xray execution comments → Qase result messages

**For Attachments**:
- Download from Xray API
- Upload to Qase using same endpoint
- Create mapping: `xray_attachment_id → qase_attachment_hash`

### 4. Reuse Qase SDK Logic

The Qase SDK usage is source-agnostic. You can reuse the `QaseService` methods which wrap the SDK:

- `QaseService.create_project()` - Uses `ProjectsApi`
- `QaseService.upload_attachment()` - Uses `AttachmentsApi`
- `QaseService.create_custom_field()` - Uses `CustomFieldsApi`
- `QaseService.create_suite()` - Uses `SuitesApi`
- `QaseService.create_cases()` - Uses `CasesApi` (or raw HTTP for shared steps)
- `QaseService.create_run()` - Uses `RunsApi`
- `QaseService.send_bulk_results_v2()` - Uses `ResultsApi` (v2)
- `QaseService.create_milestone()` - Uses `MilestonesApi`
- `QaseService.create_shared_step()` - Uses `SharedStepsApi`
- `QaseService.create_configuration()` - Uses `ConfigurationsApi`

**Or use SDK directly**:
```python
from qase.api_client_v1.api.projects_api import ProjectsApi
from qase.api_client_v1.models import ProjectCreate

api_instance = ProjectsApi(client)
response = api_instance.create_project(project_create=ProjectCreate(...))
```

### 5. Key Differences to Handle

**Xray-Specific**:
- Xray uses JIRA integration → Map Xray tests to Qase cases
- Xray test execution structure may differ
- Xray custom fields may have different structure
- Xray attachments may be linked differently

**Common Adaptations**:
- Status mapping (Xray status → Qase status)
- Field type mapping (Xray types → Qase types)
- User mapping (Xray users → Qase users)
- Date/time format conversion

### 6. Migration Order

Follow the same order as TestRail migration:
1. Users
2. Projects
3. Attachments (bulk import)
4. Custom Fields
5. Project Data (parallel):
   - Configurations (if applicable)
   - Shared Steps/Preconditions
   - Milestones (if applicable)
   - Suites/Test Sets
   - Cases/Tests
   - Runs/Executions and Results

### 7. Testing Strategy

1. Start with a single project
2. Verify each step independently:
   - Check attachments are uploaded and mapped
   - Verify custom fields are created correctly
   - Ensure cases are created with proper structure
   - Confirm results are linked correctly
3. Test edge cases:
   - Large attachments
   - Complex custom fields
   - Nested suites
   - Shared steps references
4. Scale to full migration

---

## Common Patterns and Best Practices

### 1. Bulk Operations

Always use bulk APIs when available:
- Bulk case creation (up to 100 cases per request)
- Bulk result creation (up to 500 results per request)

### 2. Error Handling

- Log errors but continue migration
- Track failed items for retry
- Validate data before sending to API

### 3. Rate Limiting

- Use throttled thread pools
- Implement exponential backoff
- Monitor API rate limit headers

### 4. Data Validation

- Validate IDs are within safe range (≤ 2^31-1)
- Check required fields before API calls
- Handle missing/null values gracefully

### 5. Mapping Preservation

- Store all ID mappings for reference
- Support `preserve_ids` option for case IDs
- Log mapping statistics

### 6. Attachment Handling

- Bulk import attachments first
- Use failover for missing attachments
- Replace references in text fields
- Collect hashes for arrays

### 7. Text Processing

- Replace attachment references
- Convert HTML to markdown
- Format links consistently
- Preserve code blocks and formatting

---

## Troubleshooting

### Common Issues

1. **Attachment Not Found**
   - Check if attachment was imported in bulk step
   - Verify attachment ID mapping
   - Use failover mechanism

2. **Custom Field Value Mismatch**
   - Verify field value mapping (`tr_key_to_qase_id`)
   - Check field was created with correct values
   - Update field if values are missing

3. **Case Creation Fails**
   - Check for shared step hash validity
   - Verify suite ID exists
   - Validate custom field IDs

4. **Result Creation Fails**
   - Ensure case exists in Qase
   - Verify status mapping
   - Check time values (end_time >= start_time)

5. **Rate Limit Errors**
   - Reduce thread pool size
   - Increase throttling delay
   - Process in smaller batches

---

## Conclusion

This guide provides a comprehensive overview of the TestRail to Qase migration process. The Qase API endpoints and data structures are source-agnostic, making it straightforward to adapt this migration for other source systems like Xray.

Key takeaways:
- Follow dependency order (users → projects → attachments → fields → data)
- Use bulk APIs for efficiency
- Preserve ID mappings for reference
- Handle attachments carefully (bulk import + failover)
- Process text content (attachments, HTML, links)
- Use throttled thread pools for rate limiting

For questions or issues, refer to the [Qase API Documentation](https://developers.qase.io/) or the migration script source code.
