# Recipes

Task-oriented examples. See [Command reference](Command-Reference) for the
full set of arguments.

## Back up saved objects

One file per object, so a diff against the previous backup is readable:

```bash
osm -t prod dashboard export --to-file backup/dashboards
osm -t prod visualization export --to-file backup/visualizations
osm -t prod search export --to-file backup/searches
```

Or everything at once, as a single ndjson stream:

```bash
osm -t prod saved-object export > backup/all.ndjson
```

## Migrate dashboards between clusters

```bash
osm -t prod dashboard export --to-file backup
osm -t staging -w 9gt3vk dashboard import 'backup/*.ndjson'
```

Quote the wildcard: `osm` expands it itself, so a pattern matching hundreds of
files works regardless of the shell's argument limits.

## Delete backing indices after 90 days

Edit the policy, then apply the edit to indices already running the old revision:

```bash
osm -t prod ism policy set-transition logs-policy hot delete --min-index-age 90d
osm -t prod ism change-policy 'logs-*' logs-policy
osm -t prod ism policy version 'logs-*'
```

## Keep an index forever without it counting as unmanaged

```bash
osm -t prod ism policy create keep_forever --pattern 'logs-archive-*'
osm -t prod ism change-policy 'logs-archive-*' keep_forever
```

The policy has one state with no actions, so enrolled indices are managed but
never modified or deleted.

## Find why a policy is stuck

```bash
osm ism status --failed
osm ism retry '.ds-logs-app-000001'
```

If the failing step is a delete on a data stream's write index, roll the stream
over first:

```bash
osm ism rollover logs-app
osm ism retry '.ds-logs-app-000001'
```

## Audit policy coverage across a cluster

```bash
osm ism list --all                                  # including unmanaged indices
osm ism policy version --include-orphans            # exits 2 if anything needs re-enrolling
osm index-template list                             # which templates carry a policy_id
osm data-stream list                                # write index and template per stream
```

## Track down a field type conflict

```bash
osm index field-caps 'p2-prod-metrics-*' --conflicts
osm index field-caps 'p2-prod-metrics-*' --unknown     # rendered as '?' in Dashboards
```

## Check dashboards before a release

```bash
osm -t staging dashboard validate || exit 1
```

See [Dashboard validation](Dashboard-Validation) for what each finding means.

## Reach an endpoint osm does not wrap

Any unrecognised first word is sent to the cluster as a REST path, with
`cluster`, `cat` and `nodes` expanded to `_cluster`, `_cat` and `_nodes`:

```bash
osm _cluster/health
osm cat indices
osm -t prod cat shards
osm nodes stats
osm _cat/allocation?v
```

The global flags still apply, so `-t` selects the target as usual.
