# Xray Cloud → Qase migration tool

Python CLI that pulls test data from **Xray Cloud** (GraphQL), maps it to **Qase** shapes, and imports it via the Qase API (official Python clients).

Phases:

1. **Extract** — Xray projects, folders, test cases, test executions (including nested test runs), and attachments (Jira-hosted and Xray Cloud evidence files, with optional download).
2. **Transform** — Qase-oriented JSON under `transformed/` (projects, suites, cases, attachment map, runs, results) plus ID mappings.
3. **Load** — Creates entities in Qase in dependency order (projects → attachments → case attachment hash updates → suites → cases → runs/results).

## What we migrate from Xray

Scope is **Xray Cloud** via GraphQL plus **Jira Cloud** REST where noted. The tables below reflect what the current code actually maps or imports.

### Projects

| Source | Qase |
| --- | --- |
| Jira project name, key, id | Project **title**, **code** (usually Jira key when valid), short **description** noting Xray origin |
| — | **runs.auto_complete** disabled on created projects |

### Folders → suites

| Source | Qase |
| --- | --- |
| Xray folder **path** on tests | **Suites**; suite **description** embeds the Xray path so cases can match the right suite |

### Test cases (tests)

| Source | Qase |
| --- | --- |
| Jira **summary** | Case **title** (duplicate titles disambiguated with issue key) |
| Jira **description** (ADF, string, or HTML-ish) | Case **description** (Markdown where conversion applies) |
| Jira **labels** | **Tags** |
| Xray **steps** (`action`, `result`, `data`) | Case **steps** |
| Xray **test type** name | **Automation** flag (heuristic) |
| Xray **folder** path | **Suite** after suites are created |
| Jira **attachments**; wiki `!file!` / `[^file]` | Upload to Qase; links rewritten to **Qase CDN URLs** on load |
| Jira **issue key** number (optional) | Qase case **`id`** when `preserve_xray_case_ids` is `true`: uses the key suffix (`XSP-50` → **50**) so Qase cards match Jira; falls back to internal issue id only if the key is missing |

**Not mapped from Xray/Jira (fixed Qase defaults today):** `preconditions`, `postconditions`, `severity`, `priority`, `type`, `behavior`, `status`.

### Attachments (files)

| Source | Behavior |
| --- | --- |
| Jira issue attachments | **Jira email + API token**; uploaded to Qase; map keyed by Jira attachment id |
| Xray Cloud test-run **evidence** / step **evidence** & **attachments** (`/api/v2/attachments/{uuid}`) | **Xray client id/secret** (Bearer); same upload path; Xray URLs in text replaced with **Qase URLs** on load |

### Test executions → runs

| Source | Qase |
| --- | --- |
| Execution Jira **summary** / **description** | Run **title** / **description** |
| Tests referenced by nested **test runs** | Run **cases** (resolved to Qase case ids on load) |

### Test runs → results

| Source | Qase |
| --- | --- |
| Run **status** | Result **status** (passed / failed / blocked / skipped / **untested** for TODO-style states) |
| Started/finished | **duration** (result wall-clock times omitted for Qase API rules) |
| **comment**, **defects**, **evidence** | **message** (structured Markdown sections) + result **attachments** |
| Step **action** / **result** | Step definition: **action** / **expected_result** |
| Step **actualResult**, **comment**, **defects**, **evidence**, **attachments** | Step **comment** (Markdown) + step **attachments** (hashes) |

Runs that include **untested** results are left **in progress** (complete run is not called for those).

### ID mappings

`mappings/id_mappings.json` stores Xray/Jira → Qase ids (e.g. projects, cases) for load and traceability.

---

## What we do **not** migrate yet

- **Test plans**, **test sets**, **boards**, **requirements** / coverage reporting.
- **Cucumber/Gherkin** as structured scenarios (only a coarse automation hint from test type).
- **Test versions**, **parameters**, **iterations**, **datasets** on runs.
- **Custom fields** on tests, executions, or run steps.
- **Precondition** issues and precondition **results** (not fully queried/mapped).
- **Users** — Xray/Jira users are not created or synced in Qase; **assignee** and **executed by** are not applied to cases or results.
- **Jira priority, components, epics, fix versions** → Qase case fields.
- **Defects** as first-class Qase defects or guaranteed Jira **keys** (often ids only from GraphQL).
- **Exact historical** result start/end times in Qase (duration preserved where possible).
- **Xray Server / Data Center** (Cloud only).
- **Qase** shared steps, custom fields on entities, and external integrations driven from Xray.

---

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

### Jira — attachment downloads (recommended for Jira-hosted files)

Jira issue attachments are downloaded with **Jira** credentials. **Xray Cloud** test-run evidence files use **Xray** client id/secret only. Without Jira credentials, Jira-hosted binaries may be skipped while metadata is still stored.

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
| `preserve_xray_case_ids` | If `true`, bulk case creation sets Qase **`id`** from the Jira **issue key** suffix (e.g. `XSP-50` → `50`), so the case id in Qase matches what you see in Jira—not Jira’s unrelated internal numeric id (which produced ids like `XSP-1120`). If the key is missing, falls back to internal `issueId`. Default `false`. Applied at **load** time; older caches without `_jira_issue_key` still resolve keys from `raw/test_cases.json`. Use an empty Qase project or delete mistaken cases before reloading. |

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
    │   ├── test_executions.json   # includes nested test runs per execution
    │   └── attachments.json
    ├── attachments/              # Downloaded files (Jira and/or Xray Cloud evidence)
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

- **Jira issue attachments — 401:** Add valid `jira_email` + `jira_api_token` (or OAuth if that is your path).
- **Jira — 403:** Project/issue permissions or attachment restrictions; confirm in the Jira UI. Metadata may still be saved without files.
- **Xray Cloud evidence** (`getxray.app/.../attachments/...`): Uses **Xray** `client_id` / `client_secret` only. If downloads fail, check Xray API access and `extraction_errors.log`.

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
