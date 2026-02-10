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
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "jira_url": "https://yourcompany.atlassian.net",
  "projects": ["PROJ1", "PROJ2"]
}
```

### Getting API Credentials

1. Log in to your Jira Cloud instance (e.g., `https://yourcompany.atlassian.net`)
2. Navigate to **Apps** → **Xray** → **Settings** → **API Keys**
   - Or: **Settings** → **Apps** → **Manage apps** → **Xray** → **Configure** → **API Keys**
3. Create a new API key and copy the **Client ID** and **Client Secret** (secret shown only once!)
4. Use your Jira URL as `jira_url` (e.g., `https://yourcompany.atlassian.net`)
5. Add project keys (the prefix before issue numbers, e.g., `TEST-123` → key is `TEST`)

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
