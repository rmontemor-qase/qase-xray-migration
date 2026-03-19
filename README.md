# Xray Cloud → Qase migration tool

Python CLI that pulls test data from **Xray Cloud** (GraphQL), maps it to **Qase** shapes, and imports it via the Qase API (official Python clients).

Phases:

1. **Extract** — Xray projects, folders, test cases, test executions, test runs, and attachments (with optional file download).
2. **Transform** — Qase-oriented JSON under `transformed/` (projects, suites, cases, attachment map, runs, results) plus ID mappings.
3. **Load** — Creates entities in Qase in dependency order (projects → attachments → suite/case updates → suites → cases → runs/results).

## Prerequisites

- Python 3.8+
- Xray Cloud API credentials (Client ID / Secret) and Jira Cloud base URL
- Qase API token and API base URL (for `load` / full `migrate` only)

## Installation

```bash
git clone <repository-url>
cd qase-xray-migration
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Dependencies include `requests`, `tqdm`, and Qase SDK packages (`qase-api-client`, `qase-api-v2-client`).

## Configuration

Copy the example file and edit values:

```bash
cp config.json.example config.json
```

### Required for extraction (and for the orchestrator)

| Field | Description |
| --- | --- |
| `client_id` | Xray Cloud API Client ID |
| `client_secret` | Xray Cloud API Client Secret |
| `jira_url` | Jira Cloud base URL (e.g. `https://yourcompany.atlassian.net`) |
| `projects` | List of Jira project keys to migrate (e.g. `["PROJ1", "PROJ2"]`) |

### Jira — attachment downloads (recommended)

Attachment binaries are fetched from Jira; without credentials, attachment download may be skipped while GraphQL metadata can still be stored.

| Field | Description |
| --- | --- |
| `jira_email` | Atlassian account email |
| `jira_api_token` | Jira API token (scoped token with `read:attachment:jira` is preferred) |

Optional OAuth (alternative or additional path, depending on your setup):

| Field | Description |
| --- | --- |
| `jira_oauth_client_id` | Jira OAuth 2.0 app client ID |
| `jira_oauth_client_secret` | Jira OAuth 2.0 app client secret |

### Qase — required for `load` and `migrate`

| Field | Description |
| --- | --- |
| `qase_host` | Qase API v1 base URL (default in example: `https://api.qase.io/v1`) |
| `qase_api_token` | Personal API token from your Qase workspace (Settings → API tokens) |

### Optional

| Field | Description |
| --- | --- |
| `cache_dir` | Parent directory for timestamped extraction folders (default: `cache`) |

**Security:** Never commit `config.json`. Use scoped Jira tokens where possible and rotate credentials if exposed.

### Getting Xray API credentials

1. Open your Jira Cloud instance.
2. Go to **Apps** → **Xray** → **Settings** → **API Keys** (or **Manage apps** → Xray → **Configure** → **API Keys**).
3. Create a key pair; copy **Client ID** and **Client Secret** (secret is shown once).

### Getting a Jira API token

Create a token at [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens). Prefer a **scoped** token with `read:attachment:jira` for least privilege.

## Usage

Global options (all commands):

- `--log-level` — `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`)
- `--log-file` — Override log path (defaults: `logs/extraction.log` or `logs/migration.log` for extract/migrate; `{cache}/transform.log` and `{cache}/load.log` for transform/load)

### Extract

```bash
python cli.py extract
python cli.py extract --config config.json
```

Creates `cache/xray_extraction_YYYYMMDD_HHMMSS/` with raw JSON, downloaded files under `attachments/`, `metadata.json`, and `extraction_errors.log` on failures.

### Transform

```bash
python cli.py transform --cache ./cache/xray_extraction_20260205_143022/
```

Reads raw cache files and writes `transformed/` plus updates `mappings/id_mappings.json`. Default `--config` is `config.json`; the orchestrator still validates Xray fields, so keep a valid Xray section in config.

### Load

```bash
python cli.py load --cache ./cache/xray_extraction_20260205_143022/ --config config.json
```

Requires `qase_api_token` and `qase_host`. Import order: projects → attachment uploads → case attachment hashes → suites (hierarchical) → cases (bulk) → runs and results when present.

### Full pipeline

```bash
python cli.py migrate --config config.json
```

Runs **extract → transform → load** in one process using a newly created cache directory. You must supply Qase credentials in config for the load step to succeed.

## Cache layout

```
cache/
└── xray_extraction_20260205_143022/
    ├── raw_data/
    │   ├── projects.json
    │   ├── folders.json
    │   ├── test_cases.json
    │   ├── test_executions.json
    │   ├── test_runs.json
    │   └── attachments.json
    ├── attachments/              # Downloaded files (when Jira auth works)
    ├── transformed/              # After transform
    │   ├── projects.json
    │   ├── suites.json
    │   ├── cases.json
    │   ├── attachments_map.json
    │   ├── runs.json
    │   └── results.json
    ├── mappings/
    │   └── id_mappings.json
    ├── metadata.json
    ├── extraction_errors.log
    ├── transform.log             # Default log for transform
    └── load.log                  # Default log for load
```

## Troubleshooting

### Xray / Jira authentication

- Confirm `client_id`, `client_secret`, and `jira_url`.
- Ensure the API key is enabled in Xray and project keys exist.

### Attachment download (401 / 403)

- **401:** Add valid `jira_email` + `jira_api_token`, or configure OAuth fields if that is your intended path.
- **403:** Issue or project permissions, or attachment restrictions in Jira. Confirm access in the Jira UI; extraction can still persist metadata without files.

### Rate limits

The GraphQL client targets Xray’s typical limit (**300 requests per 5 minutes**) with backoff. Migrating many projects at once may trigger throttling—run smaller batches if needed.

### Load / Qase errors

- Verify `qase_api_token` and `qase_host`.
- Ensure `transform` completed so `transformed/` exists before `load`.

### Import errors

- Activate the virtual environment and run `pip install -r requirements.txt`.

## API references

- [Xray Cloud GraphQL documentation](https://us.xray.cloud.getxray.app/doc/graphql/index.html)
- [Qase API](https://developers.qase.io/) (v1 for most entities; v2 client used for results)

## Project structure

```
qase-xray-migration/
├── cli.py                          # Entrypoint (extract | transform | load | migrate)
├── orchestrator.py                 # Wires extract → transform → load
├── config.json.example
├── requirements.txt
├── extractors/
│   ├── base_extractor.py
│   └── xray_cloud_extractor.py
├── repositories/
│   └── xray_cloud_repository.py    # Xray GraphQL queries
├── transformers/
│   ├── xray_transformer.py         # Orchestrates sub-transformers
│   ├── project_transformer.py
│   ├── suite_transformer.py
│   ├── case_transformer.py
│   ├── attachment_transformer.py
│   └── run_transformer.py
├── loaders/
│   └── qase_loader.py
├── services/
│   └── qase_service.py             # Qase SDK wrapper (v1 + v2)
├── models/
│   ├── xray_models.py
│   └── mappings.py
└── utils/
    ├── cache_manager.py
    ├── graphql_client.py
    └── logger.py
```
