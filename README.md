# Xray Cloud to Qase Migration Tool

A modular migration tool for extracting test data from Xray Cloud (via GraphQL API) and migrating it to Qase test management platform.

## Prerequisites

- Python 3.8 or higher
- Xray Cloud account with API credentials
- Access to Jira Cloud instance linked to Xray

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd qase-xray-migration
```

2. Create and activate virtual environment:

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Unix/Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

1. Copy the example config file:
```bash
cp config.json.example config.json
```

2. Edit `config.json` with your credentials:
```json
{
  "client_id": "YOUR_XRAY_CLIENT_ID",
  "client_secret": "YOUR_XRAY_CLIENT_SECRET",
  "jira_url": "https://yourcompany.atlassian.net",
  "projects": ["PROJ1", "PROJ2"],
  "jira_oauth_client_id": "YOUR_JIRA_OAUTH_CLIENT_ID",
  "jira_oauth_client_secret": "YOUR_JIRA_OAUTH_CLIENT_SECRET"
}
```

**Note:** `jira_oauth_client_id` and `jira_oauth_client_secret` are optional but required for downloading attachments.

### Getting API Credentials

#### Xray Cloud API Credentials (Required)

1. Log in to your Jira Cloud instance (e.g., `https://yourcompany.atlassian.net`)
2. Navigate to **Apps** → **Xray** → **Settings** → **API Keys**
   - Or: **Settings** → **Apps** → **Manage apps** → **Xray** → **Configure** → **API Keys**
3. Create a new API key and copy the **Client ID** and **Client Secret** (secret shown only once!)
4. Use your Jira URL as `jira_url` (e.g., `https://yourcompany.atlassian.net`)
5. Add project keys (the prefix before issue numbers, e.g., `TEST-123` → key is `TEST`)

#### Jira API Credentials (Required for Attachment Downloads)

**✅ Recommended: Scoped API Token (Most Secure)**

For better security, use a **scoped API token** with only the permissions needed for attachment downloads:

1. Create a scoped token with `read:attachment:jira` scope
   - This limits the token to only read attachments, reducing security risk
2. Add to `config.json`:
   - `jira_email`: Your Atlassian account email
   - `jira_api_token`: The scoped API token

**Scoped tokens work the same way as regular tokens** - they use Basic Auth format (`email:token`) but have limited permissions.

**Option: Personal API Token (Full Permissions)**

If scoped tokens aren't available, you can use a regular personal API token:

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Give it a label (e.g., "Xray Migration - Attachments")
4. Copy the token (shown only once!)
5. Add to `config.json`:
   - `jira_email`: Your Atlassian account email
   - `jira_api_token`: The personal API token

**⚠️ Security Best Practices:**
- **Prefer scoped tokens** with `read:attachment:jira` scope when available
- Use a dedicated service account with minimal permissions
- Rotate tokens regularly
- Store tokens securely (never commit to version control)
- Revoke immediately if compromised

**Note:** Without Jira Basic Auth credentials (`jira_email` and `jira_api_token`), attachment downloads will fail. The script will skip attachment downloads if these credentials are not provided.

## Usage

### Extract Phase (✅ IMPLEMENTED)

Extract data from Xray Cloud and save to cache:

```bash
python cli.py extract
```

Or with a custom config file:
```bash
python cli.py extract --config config.json
```

This will:
- Authenticate with Xray Cloud
- Extract projects, folders, test cases, test executions, and attachments
- Download attachment files locally (requires `jira_oauth_client_id` and `jira_oauth_client_secret` in config)
- Save all data to `./cache/xray_extraction_[timestamp]/`
- Create metadata and error logs

### Transform Phase (❌ NOT YET IMPLEMENTED)

```bash
python cli.py transform --cache ./cache/xray_extraction_20260205_143022/
```

### Load Phase (❌ NOT YET IMPLEMENTED)

```bash
python cli.py load --cache ./cache/xray_extraction_20260205_143022/
```

### Full Migration (⚠️ PARTIALLY IMPLEMENTED)

```bash
python cli.py migrate
```

**Status:** Only the extract phase is implemented. Transform and load phases will be skipped with warnings.

## Cache Structure

```
cache/
└── xray_extraction_20260205_143022/
    ├── raw_data/
    │   ├── projects.json
    │   ├── folders.json
    │   ├── test_cases.json
    │   ├── test_executions.json
    │   └── attachments.json
    ├── attachments/
    │   └── [downloaded attachment files]
    ├── mappings/
    │   └── id_mappings.json
    ├── metadata.json
    └── extraction_errors.log
```

## Troubleshooting

### Authentication Errors
- Verify your `client_id` and `client_secret` are correct
- Ensure your API key has proper permissions in Xray Cloud
- Check that your Jira URL is correct and accessible
- **For attachment download errors:**
  - **401 Unauthorized:** Add `jira_oauth_client_id` and `jira_oauth_client_secret` to your `config.json` (see "Getting API Credentials" above)
  - **403 Forbidden:** Your account doesn't have permission to access the attachment. Possible causes:
    - Attachment is restricted/private
    - Your Jira account doesn't have access to the project/issue
    - OAuth app lacks sufficient permissions
    - Jira instance security settings restrict attachment access
    - **Solution:** Verify you can access the attachment in Jira web interface, or skip downloading attachments for now (metadata is still saved)

### Rate Limit Errors
- The tool automatically handles rate limits (300 requests/5min)
- If you see frequent warnings, consider reducing the number of projects migrated at once

### ModuleNotFoundError
- Make sure your virtual environment is activated
- Run `pip install -r requirements.txt`

## API Documentation

**Xray Cloud GraphQL API Documentation:**
https://us.xray.cloud.getxray.app/doc/graphql/index.html

## Project Structure

```
qase-xray-migration/
├── cli.py                    # Command-line interface
├── orchestrator.py           # Migration coordinator
├── config.json.example
├── extractors/
├── repositories/
├── models/
├── utils/
└── requirements.txt
```
