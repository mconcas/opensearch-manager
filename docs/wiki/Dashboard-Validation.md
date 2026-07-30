# Dashboard validation

`osm dashboard validate [id ...]` checks that dashboards still work against the
live cluster. It walks the whole reference chain:

```
dashboard -> visualization -> saved search -> index pattern -> cluster mapping
```

With no ids it validates every dashboard in scope. It exits `1` when any error or
global issue is found, so it can gate a deployment.

```bash
osm -t prod dashboard validate
osm -t prod dashboard validate dash.influxdb.overview --json
```

## Output

```
  ✗ [InfluxDB] Overview  (id: dash.influxdb.overview)
      ✗ [missing-field] Visualization '[InfluxDB] Messages' (id: vis.influxdb.messages)
        references field 'message.keyword' not found in 'p2-prod-metrics-app*' [agg "terms" (id: 2)]

Total: 2 dashboard(s) - 1 ok, 0 warning(s), 1 error(s), 1 global issue(s)
```

Each finding names the dashboard, the object that carries the problem, and the
specific field or reference at fault. Global issues are problems with a shared
object, such as an index pattern matching no index, counted once rather than
repeated under every dashboard that uses it.

`--json` produces the same findings as structured data, with a `summary` object
holding the counts.

## Checks

| Check | Level | Raised when |
|---|---|---|
| `broken-reference` | error | A referenced visualization, search, or index pattern is missing |
| `missing-index` | error | An index pattern matches no index, alias, or data stream |
| `missing-field` | error | An aggregation, filter, or column reads a field the mapping lacks |
| `invalid-query` | warning | `searchSourceJSON` is malformed or has mismatched parentheses |
| `invalid-json` | error | `panelsJSON` is not valid JSON |
| `empty-dashboard` | warning | The dashboard has no panels or references |

## Diagnosing a missing field

A `missing-field` finding means the index pattern's cached field list and the
live mapping disagree, or the field genuinely no longer exists. Two commands
separate the cases:

```bash
osm index field-caps 'p2-prod-metrics-app*'              # what the cluster has
osm index field-caps 'p2-prod-metrics-app*' --conflicts   # mapped as several types
osm index-pattern list                                    # cached field-list size
```

If the cluster has the field but Dashboards does not, the index pattern's cached
field list is stale. Rebuild it from the live mapping:

```bash
osm index-pattern refresh <pattern-id> --dry-run   # show the diff first
osm index-pattern refresh <pattern-id>
```
