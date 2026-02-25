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

Create `~/.starsearch/config.json` with your cluster details:

```json
{
  "servers": [
    {
      "name": "local-es",
      "host": "localhost:9200",
      "protocol": "http"
    },
    {
      "name": "prod-os",
      "host": "opensearch.example.com",
      "protocol": "https",
      "username": "admin",
      "password": "your-password",
      "verify_ssl": false,
      "cluster_path": "/os",
      "base_path": "/dashboards"
    }
  ]
}
```

### Configuration Options

- `name`: Identifier for the server (used with `--target`)
- `host`: Server hostname and port
- `protocol`: `http` or `https`
- `username`/`password`: Basic authentication credentials (optional)
- `verify_ssl`: Set to `false` to disable SSL certificate verification (optional)
- `cluster_path`: Path prefix for cluster API access, e.g., `/os` (optional)
- `base_path`: Path prefix for Dashboards API access, e.g., `/dashboards` (optional)

## Usage

### Target Management

View all configured servers/targets:

```bash
# List all available targets
starsearch-cli target list
```

This shows all configured servers with their connection details, including which one is the default.

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