# Workspaces

Where Dashboards has workspaces enabled, a saved object belongs to one workspace
and is invisible from the others. A `dashboard list` that returns nothing usually
means the right objects exist in a workspace you are not looking at.

Every command touching saved objects - `list`, `export`, `import`, `delete`,
`validate` - is scoped to one of three things, in order of precedence:

1. `--global`, the global scope, ignoring whatever the target configures
2. `-w ID`, the workspace given on the command line
3. the `workspace` key of the target's `dashboards` endpoint

```bash
osm -t prod workspace list                        # discover workspace ids
osm -t prod -w 9gt3vk dashboard import dash.ndjson
osm -t prod --global dashboard list               # ignore the configured workspace
```

## Finding a workspace id

`osm workspace list` prints each workspace with its id. The id is also the token
in the Dashboards URL:

```
https://opensearch.example.com/dashboards/w/9gt3vk/app/dashboards
                                            ^^^^^^
```

Set it once per target in the config file to avoid repeating `-w`:

```json
"dashboards": { "protocol": "https", "host": "opensearch.example.com",
                "path": "/dashboards", "workspace": "9gt3vk" }
```

## Importing across workspaces

Objects carry no workspace of their own in an ndjson export, so the scope of the
import decides where they land. Exporting from one workspace and importing into
another is a plain copy:

```bash
osm -t prod   -w 9gt3vk dashboard export --to-file backup
osm -t staging -w a1b2c3 dashboard import 'backup/*.ndjson'
```

## Limitation without a Dashboards endpoint

Only the Dashboards API tags imported objects with a workspace. Against a target
with no `dashboards` endpoint, `import` writes to the cluster's `.kibana` index
unscoped, and the objects appear in no workspace at all. Configure a
`dashboards` endpoint whenever workspaces matter. See
[Configuration](Configuration#access-modes).
