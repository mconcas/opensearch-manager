# os-manager

`osm` - a CLI for OpenSearch clusters and OpenSearch Dashboards: saved objects,
index state management, and raw REST access.

## Install

```bash
pip install -e .
```

## Configure

`~/.os-manager/config.json` lists targets. Each names an OpenSearch REST
endpoint and an OpenSearch Dashboards endpoint, and shares credentials between
them. The first target is the default; `-t NAME` selects another.

```json
{
  "targets": [
    {
      "name": "local",
      "cluster":    { "protocol": "http", "host": "localhost:9200" },
      "dashboards": { "protocol": "http", "host": "localhost:5601" }
    }
  ]
}
```

```bash
osm target list
```

## Use

```bash
osm _cluster/health                          # unrecognised commands go to the REST API
osm cat indices
osm dashboard list                           # saved objects
osm dashboard validate                       # check dashboards against the cluster
osm ism status --failed                      # policies that are stuck
osm -t prod dashboard export --to-file backup
```

`osm --help` lists the commands, and `osm <command> [subcommand] --help` gives
the arguments of each.

## Documentation

Full documentation is in the [wiki](https://github.com/mconcas/opensearch-manager/wiki):

- [Configuration](https://github.com/mconcas/opensearch-manager/wiki/Configuration) - targets, endpoints, access modes
- [Command reference](https://github.com/mconcas/opensearch-manager/wiki/Command-Reference) - every command, argument and flag
- [Workspaces](https://github.com/mconcas/opensearch-manager/wiki/Workspaces) - scoping saved objects
- [ISM policies](https://github.com/mconcas/opensearch-manager/wiki/ISM-Policies) - enrolment, versions, editing
- [Dashboard validation](https://github.com/mconcas/opensearch-manager/wiki/Dashboard-Validation) - the checks and their meaning
- [Recipes](https://github.com/mconcas/opensearch-manager/wiki/Recipes) - task-oriented examples

The wiki is published from [`docs/wiki/`](docs/wiki) by the
[`wiki` workflow](.github/workflows/wiki.yml); edit the files there, not the
wiki itself. `Command-Reference` is generated from the CLI's own argument
definitions by `tools/gen_command_reference.py`, so it cannot drift from the
code:

```bash
python tools/gen_command_reference.py --stdout | less
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Request failed, or `dashboard validate` found errors, or `ism status --failed` found failures |
| `2` | `ism policy version` found drifted, un-enrolled, or orphaned indices |
