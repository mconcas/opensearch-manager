# Configuration

`osm` reads `~/.os-manager/config.json`. It holds a list of targets; a target
names two endpoints, the OpenSearch REST API and OpenSearch Dashboards, and
shares its credentials between them. The first target is the default, and
`-t NAME` selects another.

```json
{
  "targets": [
    {
      "name": "local",
      "cluster":    { "protocol": "http", "host": "localhost:9200" },
      "dashboards": { "protocol": "http", "host": "localhost:5601" }
    },
    {
      "name": "prod",
      "username": "admin",
      "password": "secret",
      "verify_ssl": false,
      "cluster":    { "protocol": "https", "host": "opensearch.example.com", "path": "/os" },
      "dashboards": { "protocol": "https", "host": "opensearch.example.com", "path": "/dashboards", "workspace": "9gt3vk" }
    }
  ]
}
```

The file contains credentials, so keep it out of version control and readable
only by you:

```bash
chmod 600 ~/.os-manager/config.json
```

## Target keys

| Key | Meaning |
|---|---|
| `name` | Target name for `-t` |
| `username`, `password` | Basic auth for both endpoints, optional |
| `verify_ssl` | Verify TLS certificates (default `true`) |
| `cluster` | Endpoint of the OpenSearch REST API |
| `dashboards` | Endpoint of OpenSearch Dashboards |

## Endpoint keys

| Key | Meaning |
|---|---|
| `protocol` | `http` or `https` |
| `host` | Hostname, with port if it is not the protocol default |
| `path` | Reverse-proxy prefix, optional, e.g. `/dashboards` |
| `workspace` | Default workspace for saved objects, `dashboards` only |

## Access modes

Saved objects are read and written through the Dashboards saved-objects API when
a `dashboards` endpoint is configured, and directly against the cluster's
`.kibana` index when it is not. Everything else always goes to the `cluster`
endpoint.

Either endpoint may be left out. A command that needs the missing one fails with
an explicit error rather than guessing.

Going through Dashboards is the better path: it runs the same import and export
logic the UI does, resolves references, and tags objects with a workspace. The
`.kibana` fallback exists for clusters with no reachable Dashboards, and it
cannot set workspaces at all.

## Checking what is configured

```bash
osm target list
```

This prints each target with its resolved endpoint URLs, its workspace and
username if set, and its `verify_ssl` value. It reads only the config file, so
it works with no cluster reachable. Passwords are never printed.
