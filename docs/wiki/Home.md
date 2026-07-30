# os-manager

`osm` is a command line client for OpenSearch clusters and OpenSearch
Dashboards. It manages saved objects, index state management (ISM) policies,
templates, data streams and indices, and passes anything it does not recognise
straight through to the REST API.

## Install

```bash
git clone https://github.com/mconcas/opensearch-manager.git
cd opensearch-manager
pip install -e .
```

Python 3.9 or later, with `requests` as the only runtime dependency.

## Quick start

Write a config file naming at least one target, then check it resolves:

```bash
mkdir -p ~/.os-manager
$EDITOR ~/.os-manager/config.json      # see Configuration
osm target list
```

From there:

```bash
osm _cluster/health                          # raw REST passthrough
osm cat indices                              # /_cat/indices
osm dashboard list                           # saved objects
osm ism status --failed                      # policies that are stuck
osm -t prod dashboard export --to-file backup
```

## Pages

| Page | Contents |
|---|---|
| [Configuration](Configuration) | The config file, targets, endpoints, access modes |
| [Command reference](Command-Reference) | Every command, argument and flag, generated from the source |
| [Workspaces](Workspaces) | Scoping saved objects to a Dashboards workspace |
| [ISM policies](ISM-Policies) | Enrolment, policy versions, editing semantics |
| [Dashboard validation](Dashboard-Validation) | What `dashboard validate` checks and reports |
| [Recipes](Recipes) | Task-oriented examples |

## Output conventions

Every listing command takes `--json` for machine-readable output. Export
commands write ndjson to stdout, a JSON array under `--json`, or one file per
object under `--to-file [DIR]`. Import commands take several files and expand
wildcards themselves, so quoting a pattern works:

```bash
osm dashboard import 'backup/*.ndjson'
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Request failed, or `dashboard validate` found errors, or `ism status --failed` found failures |
| `2` | `ism policy version` found drifted, un-enrolled, or orphaned indices |

Exit code `2` exists so scripts can tell "something needs re-enrolling" apart
from "the request failed".
