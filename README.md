# os-manager

`osm` - a CLI for OpenSearch clusters and OpenSearch Dashboards: saved objects,
index state management, and raw REST access.

## Install

```bash
pip install -e .
```

## Configuration

`~/.os-manager/config.json`. The first server is the default target; `-t NAME`
selects another.

```json
{
  "servers": [
    {
      "name": "local",
      "host": "localhost:9200",
      "protocol": "http"
    },
    {
      "name": "prod",
      "host": "opensearch.example.com",
      "protocol": "https",
      "username": "admin",
      "password": "secret",
      "verify_ssl": false,
      "cluster_path": "/os",
      "base_path": "/dashboards"
    }
  ]
}
```

| Key | Meaning |
|---|---|
| `name` | Target name for `-t` |
| `host` | Hostname and port |
| `protocol` | `http` or `https` |
| `username`, `password` | Basic auth, optional |
| `verify_ssl` | Verify TLS certificates (default `true`) |
| `cluster_path` | Path prefix to the OpenSearch REST API, e.g. `/os` |
| `base_path` | Path prefix to Dashboards, e.g. `/dashboards` |

**Access modes.** Saved objects are read and written through the Dashboards
saved-objects API when `base_path` is set, and directly against the cluster's
`.kibana` index when it is not. Everything else always goes to the OpenSearch
REST API under `cluster_path`.

## Commands

`osm --help` lists these; `osm <command> [subcommand] --help` gives arguments
and flags. Anything `osm` does not recognise is sent to the cluster as a REST
path, so `osm _cluster/health` and `osm cat indices` work too.

| Command | |
|---|---|
| `target list` | Configured servers |
| `saved-object list\|export\|import` | All saved objects; `export --type` narrows by type |
| `dashboard list\|export\|import\|delete` | Dashboards |
| `dashboard validate [id ...]` | Check dashboards against the cluster |
| `visualization list\|export\|import\|delete` | Visualizations |
| `search list\|export\|import\|delete` | Saved searches |
| `detector list\|export` | Anomaly detection detectors |
| `index-pattern list\|delete` | Index patterns |
| `index-pattern refresh <id>` | Rebuild the cached field list from the live mapping |
| `index delete <name>` | Delete an index |
| `index field-caps <pattern>` | Field types across a pattern, as Dashboards resolves them |
| `ism list` | Policy and state per index |
| `ism status [index]` | How each policy is executing |
| `ism settings` | Effective `plugins.index_state_management.*` settings |
| `ism schedule [index]` | Per-index tick interval baked in at enrolment |
| `ism policy show <name>` | Full policy definition |
| `ism policy version [index]` | Per-index policy version against the current one |
| `ism policy set-rollover <name>` | Edit a state's rollover conditions |
| `ism policy set-transition <name> <from> <to>` | Upsert a transition |
| `ism policy edit-ism-template <name>` | Edit which indices the policy claims |
| `ism change-policy <pattern> <policy>` | Enrol indices on the current policy version |
| `ism retry <pattern>` | Retry a failed ISM step |
| `ism rollover <name>` | Roll over a data stream or write alias |
| `index-template list\|set-policy` | Index templates and their ISM policy |
| `component-template list\|set-policy` | Component templates and their ISM policy |
| `data-stream list [pattern]` | Data streams with write index and template |
| `jobs list\|pending\|policy` | Running tasks, queued master work, ISM work in flight |

Every listing command takes `--json`. Export commands write ndjson to stdout,
`--json` a JSON array, `--to-file [DIR]` one file per object.

Policy edits are read-modify-write under optimistic concurrency control: a
concurrent edit to the same policy fails with HTTP 409 instead of overwriting.
Conditions merge into what is already there, and the value `none` removes one:

```bash
osm ism policy set-rollover logs-policy --age 1d --primary-shard-size 50gb
osm ism policy set-rollover logs-policy --docs none
```

## Examples

Back up and migrate saved objects between clusters:

```bash
osm -t prod dashboard export > dashboards.ndjson
osm -t staging dashboard import dashboards.ndjson
```

Delete backing indices 90 days after creation, then apply the edit to indices
already running the old policy version:

```bash
osm -t prod ism policy set-transition logs-policy hot delete --min-index-age 90d
osm -t prod ism change-policy 'logs-*' logs-policy
osm -t prod ism policy version 'logs-*'
```

Find why a policy is stuck:

```bash
osm ism status --failed
osm ism retry '.ds-logs-app-000001'
```

Validate dashboards, which walks dashboard -> visualization -> saved search ->
index pattern -> cluster mapping:

```
  ✗ [InfluxDB] Overview  (id: dash.influxdb.overview)
      ✗ [missing-field] Visualization '[InfluxDB] Messages' (id: vis.influxdb.messages)
        references field 'message.keyword' not found in 'p2-prod-metrics-app*' [agg "terms" (id: 2)]

Total: 2 dashboard(s) - 1 ok, 0 warning(s), 1 error(s), 1 global issue(s)
```

| Check | Level | Raised when |
|---|---|---|
| `broken-reference` | error | A referenced visualization, search, or index pattern is missing |
| `missing-index` | error | An index pattern matches no index, alias, or data stream |
| `missing-field` | error | An aggregation, filter, or column reads a field the mapping lacks |
| `invalid-query` | warning | `searchSourceJSON` is malformed or has mismatched parentheses |
| `invalid-json` | error | `panelsJSON` is not valid JSON |
| `empty-dashboard` | warning | The dashboard has no panels or references |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Request failed, or `dashboard validate` found errors, or `ism status --failed` found failures |
| `2` | `ism policy version` found drifted, un-enrolled, or orphaned indices |
