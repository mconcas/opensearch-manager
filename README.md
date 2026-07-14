# *search manager

Comprehensive CLI tool for managing Elasticsearch/OpenSearch clusters and OpenSearch Dashboards.

## Features

- **Query Execution**: Run queries directly against Elasticsearch/OpenSearch clusters
- **Saved Object Management**: Manage all saved objects (dashboards, visualizations, searches) collectively
- **Dashboard Management**: List, export, import, delete, and **validate** dashboards
- **Dashboard Validation**: Detect broken references, missing indices, missing fields, bad queries
- **Visualization Management**: Manage visualizations independently
- **Saved Search Management**: Manage saved searches
- **Index Lifecycle Management**: Configure ILM/ISM policies
- **Index Operations**: Delete indices and manage index patterns
- **Authentication**: Basic Auth support with configurable SSL verification
- **Multi-Server Support**: Manage multiple clusters from one config

## Installation

```bash
git clone https://github.com/mconcas/starsearch-manager
cd starsearch-manager
pip install -e .
```

## Configuration

Create `~/.starsearch/config.json`. A **target** bundles the OpenSearch/ES
**cluster** endpoint and the OpenSearch Dashboards (**OSD**) endpoint under one
name, with credentials shared across both:

```json
{
  "targets": [
    {
      "name": "local",
      "cluster": { "protocol": "http", "host": "localhost:9200" },
      "dashboards": { "protocol": "http", "host": "localhost:5601" }
    },
    {
      "name": "prod",
      "username": "admin",
      "password": "your-password",
      "verify_ssl": false,
      "cluster":    { "protocol": "https", "host": "opensearch.example.com", "path": "/os" },
      "dashboards": { "protocol": "https", "host": "opensearch.example.com", "path": "/dashboards", "workspace": "9gt3vk" }
    }
  ]
}
```

### Configuration Options

Target-level (shared by both endpoints):

- `name`: Identifier for the target (used with `-t`/`--target`)
- `username`/`password`: Basic authentication credentials (optional)
- `verify_ssl`: Set to `false` to disable SSL certificate verification (optional, default `true`)

Endpoint-level, under `cluster` (ES/OS cluster API) and `dashboards` (OSD API):

- `protocol`: `http` or `https`
- `host`: Hostname and port (e.g. `localhost:9200`, `localhost:5601`)
- `path`: Optional reverse-proxy path prefix, e.g. `/os` or `/dashboards`
- `workspace` (`dashboards` only): Default OSD workspace id to scope saved objects to (optional)

A target may define only `cluster` or only `dashboards`; commands that need the
missing endpoint will report a clear error. The default target is the first in
the list.

## Usage

### Workspaces

If your OpenSearch Dashboards instance uses **workspaces**, saved objects
(dashboards, visualizations, searches) are scoped per workspace. Any command
that touches saved objects — `list`, `export`, `import`, `delete`, `validate` —
can be pointed at a workspace, either via the target's `dashboards.workspace`
config default or the global `-w`/`--workspace <id>` flag (which overrides it).
Use `--global` to force the global scope even when a default workspace is set:

```bash
# Discover workspace ids on the target
starsearch-cli -t prod workspace list

# List / export / import into a specific workspace
starsearch-cli -w 9gt3vk dashboard list
starsearch-cli -t prod -w 9gt3vk dashboard import dashboards.ndjson

# Inspect the global (workspace-less) scope, ignoring the config default
starsearch-cli --global dashboard list
```

`workspace list` queries the Dashboards `/api/workspaces/_list` API and prints
each workspace's id and name (add `--json` for raw output). The workspace id is
also the short token in the OSD URL (`/w/<id>/app/...`).

> **Note:** In the **global** scope (no workspace resolved), objects are not
> associated with any workspace and won't appear inside one. `import` uses the
> Dashboards `_import` API, the only path that actually tags objects with the
> target workspace.

### Target Management

View all configured targets:

```bash
# List all available targets
starsearch-cli target list
```

This shows each target's cluster and dashboards endpoints, including which one is the default.

### Basic Queries

Execute queries directly against the cluster:

```bash
# Use default server (first in config)
starsearch-cli _cluster/health

# Target specific server
starsearch-cli --target prod-os _cat/indices

# POST requests with JSON data
starsearch-cli _search -d '{"query": {"match_all": {}}}'
```

### Saved Object Management

Manage all saved objects (dashboards, visualizations, searches) at once:

```bash
# List all saved objects
starsearch-cli saved-object list

# Export all saved objects to NDJSON
starsearch-cli saved-object export > all-objects.ndjson

# Export specific objects by ID
starsearch-cli saved-object export obj-id1 obj-id2 > objects.ndjson

# Export only visualizations
starsearch-cli saved-object export --type visualization > visualizations.ndjson

# Export only dashboards
starsearch-cli saved-object export --type dashboard > dashboards.ndjson

# Export only saved searches
starsearch-cli saved-object export --type search > searches.ndjson

# Combine --type with other flags
starsearch-cli saved-object export --type visualization --json > visualizations.json
starsearch-cli saved-object export --type dashboard --to-file --json

# Export as JSON array instead of NDJSON
starsearch-cli saved-object export --json > objects.json

# Export to individual files (one per object)
starsearch-cli saved-object export --to-file

# Export to individual JSON files
starsearch-cli saved-object export --to-file --json

# Import saved objects from NDJSON file
starsearch-cli saved-object import objects.ndjson
```

### Dashboard Management

Manage dashboards separately from other objects:

```bash
# List all dashboards
starsearch-cli dashboard list

# Export specific dashboard(s) to NDJSON
starsearch-cli dashboard export dashboard-id1 dashboard-id2 > dashboards.ndjson

# Export all dashboards
starsearch-cli dashboard export > all-dashboards.ndjson

# Export as JSON array instead of NDJSON
starsearch-cli dashboard export --json > dashboards.json

# Export to individual files (one per dashboard)
starsearch-cli dashboard export --to-file

# Export specific dashboards to individual JSON files
starsearch-cli dashboard export dashboard-id1 dashboard-id2 --to-file --json

# Import dashboards from NDJSON file
starsearch-cli dashboard import dashboards.ndjson

# Delete a dashboard
starsearch-cli dashboard delete dashboard-id
```

### Dashboard Validation

Detect problems in dashboards before they break in the UI — broken references, missing indices, missing fields in aggregations, malformed queries:

```bash
# Validate all dashboards
starsearch-cli dashboard validate

# Validate specific dashboard(s) by ID
starsearch-cli dashboard validate dash-id1 dash-id2

# Verbose output (also shows passing dashboards)
starsearch-cli dashboard validate --verbose

# Machine-readable JSON output
starsearch-cli dashboard validate --json

# Validate on a specific target
starsearch-cli --target prod dashboard validate
```

The validator walks the full dependency tree (dashboard → visualizations → saved searches → index patterns → cluster indices) and performs these checks:

| Check | Level | Description |
|---|---|---|
| `broken-reference` | error | Dashboard references a visualization, search, or index pattern that doesn't exist |
| `missing-index` | error | Index pattern doesn't resolve to any cluster index, alias, or data stream |
| `missing-field` | error | Visualization aggregation or search column references a field not found in the index mapping (e.g., `message.keyword` when only `message` as `text` exists) |
| `invalid-query` | warning | `searchSourceJSON` is malformed or has mismatched parentheses |
| `invalid-json` | error | Dashboard's `panelsJSON` is not valid JSON |
| `empty-dashboard` | warning | Dashboard has no panels or references |
| Time field check | warning | Index pattern's configured time field not found in the actual index mapping |
| Global index patterns | error | Any index pattern in the system has no matching indices |

**Field-level validation** inspects `visState` aggregations, TSVB series, filters, and saved search columns against the actual cluster mapping (including `.keyword` sub-fields and nested properties). Data streams and their backing indices are fully supported.

The command exits with code `1` when errors are found, making it suitable for CI pipelines.

Example output:
```
Global Issues
============================================================
  ✗ Index pattern 'old-logs-*' (id: abc123) does not match any cluster index or alias

Dashboard Validation Results
============================================================

  ✓ [Logs] Overview  (id: dash.logs.overview)

  ✗ [InfluxDB] Overview  (id: dash.influxdb.overview)
      ✗ [missing-field] Visualization '[InfluxDB] Messages' (id: vis.influxdb.messages) references
        field 'message.keyword' not found in index 'p2-prod-metrics-app*' [agg "terms" (id: 2)]

============================================================
Total: 2 dashboard(s) — 1 ok, 0 warning(s), 1 error(s), 1 global issue(s)
```

### Visualization Management

Manage visualizations independently:

```bash
# List all visualizations
starsearch-cli visualization list

# Export specific visualization(s)
starsearch-cli visualization export vis-id1 vis-id2 > visualizations.ndjson

# Export as JSON array instead of NDJSON
starsearch-cli visualization export --json > visualizations.json

# Export to individual files (one per visualization)
starsearch-cli visualization export --to-file

# Export to individual JSON files
starsearch-cli visualization export --to-file --json

# Import visualizations
starsearch-cli visualization import visualizations.ndjson

# Delete a visualization
starsearch-cli visualization delete vis-id
```

### Saved Search Management

Manage saved searches:

```bash
# List all saved searches
starsearch-cli search list

# Export saved searches
starsearch-cli search export > searches.ndjson

# Export as JSON array instead of NDJSON
starsearch-cli search export --json > searches.json

# Export specific search(es)
starsearch-cli search export search-id1 search-id2 > searches.ndjson

# Export to individual files (one per search)
starsearch-cli search export --to-file

# Export to individual JSON files
starsearch-cli search export --to-file --json

# Import searches
starsearch-cli search import searches.ndjson

# Delete a saved search
starsearch-cli search delete search-id
```

### Index Lifecycle Management (ILM/ISM)

Configure lifecycle policies for index management:

```bash
# Show ILM policy info for all indices
starsearch-cli ilm info

# Show detailed policy info including all indices
starsearch-cli ilm info --all

# Set delete phase (delete after N days)
starsearch-cli ilm my-policy set delete-after 30

# Set warm phase (move to warm after N days)
starsearch-cli ilm my-policy set warm-after 7

# Set cold phase (move to cold after N days)
starsearch-cli ilm my-policy set cold-after 14

# Set rollover thresholds (size and document count)
starsearch-cli ilm my-policy set rollover 50gb 1000000
```

### Jobs & Policy Status

Inspect what the cluster is currently doing — long-running operations, queued master-level work, and how lifecycle policies are being applied to each managed index.

```bash
# Running cluster tasks (filters out monitor/internal noise by default)
starsearch-cli jobs list

# Include monitor/internal tasks
starsearch-cli jobs list --all

# Only show tasks whose action contains a substring
starsearch-cli jobs list --filter reindex
starsearch-cli jobs list --filter forcemerge

# Pending master-level cluster tasks (cluster-state changes queued at the master)
starsearch-cli jobs pending

# In-flight ILM/ISM policy work (only indices currently being acted on,
# retrying, or failed)
starsearch-cli jobs policy
```

Per-index lifecycle execution status — the "how is this policy actually being applied" view. Works against both Elasticsearch ILM (`_ilm/explain`) and OpenSearch ISM (`_plugins/_ism/explain`):

```bash
# All managed indices: phase, action, step, status, retries, time-in-step, last error
starsearch-cli ilm status

# Single index (or a wildcard pattern)
starsearch-cli ilm status my-index-000001
starsearch-cli ilm status 'logs-*'

# Only indices whose step is failed or retrying (exits 1 if any found — CI friendly)
starsearch-cli ilm status --failed

# Machine-readable
starsearch-cli ilm status --failed --json
```

Example output:

```
Index                           Policy                   Phase   Action  Step            Status  Retries  In Step
-----------------------------------------------------------------------------------------------------------------
.ds-prod-logs-app-000001        observability-retention  delete  delete  attempt_delete  failed  3        1d6h

Errors:
  ✗ .ds-prod-logs-app-000001 [attempt_delete] index [.ds-prod-logs-app-000001] is the write index for data stream [prod-logs-app] and cannot be deleted

Total: 1 index(es) — 1 failed
```

### Index Operations

```bash
# Delete an index
starsearch-cli index delete my-index-name
```

### Index Pattern Management

```bash
# List all index patterns
starsearch-cli index-pattern list

# Delete an index pattern
starsearch-cli index-pattern delete pattern-id
```

### Multi-Server Usage

Use the `--target` flag to specify which server to use:

```bash
# Query production server
starsearch-cli --target prod-os _cluster/health

# List dashboards on staging server
starsearch-cli --target staging dashboard list

# Export from one server and import to another
starsearch-cli --target prod dashboard export dash-id > prod-dashboard.ndjson
starsearch-cli --target staging dashboard import prod-dashboard.ndjson
```

### Version Information

```bash
starsearch-cli --version
starsearch-cli -v
```

## Output Format

- Queries return pretty-printed JSON
- List commands display formatted tables
- Export commands generate NDJSON (newline-delimited JSON)
- Error messages are returned as JSON with `"error"` key

## Examples

### Backup All Dashboards

```bash
starsearch-cli --target prod dashboard export > backup-dashboards.ndjson
starsearch-cli --target prod visualization export > backup-visualizations.ndjson
starsearch-cli --target prod search export > backup-searches.ndjson
```

### Migrate Dashboards Between Clusters

```bash
# Export from production
starsearch-cli --target prod dashboard export > dashboards.ndjson

# Import to staging
starsearch-cli --target staging dashboard import dashboards.ndjson
```

### Clean Up Old Indices with ILM

```bash
# Configure policy to delete indices after 90 days
starsearch-cli --target prod ilm logs-policy set delete-after 90

# Move to warm storage after 30 days
starsearch-cli --target prod ilm logs-policy set warm-after 30
```

## API Support

The tool supports both:
- **Dashboards API**: Modern OpenSearch Dashboards API (automatic detection)
- **Direct .kibana access**: Fallback for older versions or when Dashboards API is unavailable

The appropriate API is selected automatically based on server configuration.

## Development

```bash
# Clone the repository
git clone <repo-url>
cd starsearch-manager

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable mode
pip install -e .

# Run tests
starsearch-cli --version
```