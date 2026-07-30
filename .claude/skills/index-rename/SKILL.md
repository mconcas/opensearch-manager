---
name: index-rename
description: Rename an OpenSearch index so the result is indistinguishable from the original except for its name - same content, mappings, settings, aliases, and ISM management. Trigger when the user asks to rename an index, or to "move"/"re-label" an index to a new name. Mutating - clones then deletes the source, requires user confirmation.
---

# index-rename

OpenSearch has no rename API. This renames by `_clone` (hard-links segments, so cost is independent of index size), then carries over everything clone leaves behind, verifies, and deletes the source.

The pre-flight survey is the substance of this skill. Clone itself is one call; what makes a rename correct is discovering, before cloning, which of the carry-over surfaces this particular index touches.

## Preconditions

`osm` raw passthrough is **GET-only**. Mutations either use a real subcommand (`osm index delete`, `osm ism change-policy`, `osm ism policy edit-ism-template`) or a short script:

```python
from os_manager.client import connect
c = connect("<target>")
c.fetch("<path>", method="PUT", json={...})
```

## Pre-flight survey

Run all of these before mutating anything. Each one decides an action.

### 1. Refuse data stream backing indices

```bash
osm -t <target> '_cat/indices/<old>?v'
```

A name of the form `.ds-<stream>-NNNNNN` cannot be meaningfully renamed - the name encodes stream membership and generation. **Stop and tell the user**; the operation they want is a rollover or a reindex into a new stream, not a rename.

### 2. Aliases on the source

```bash
osm -t <target> '<old>/_alias'
```

Clone does **not** copy aliases. Any alias found here must be recreated on the target, including `is_write_index`. Record them now.

### 3. Which ISM policy claims the old name, and how

```bash
osm -t <target> '_plugins/_ism/explain/<old>'
osm -t <target> '_plugins/_ism/policies' | python -c "
import sys, json
for p in json.load(sys.stdin).get('policies', []):
    pol = p['policy']
    for t in (pol.get('ism_template') or []):
        print(pol['policy_id'], t.get('priority'), t.get('index_patterns'))
"
```

Two things to determine:

- **Does the claiming policy's `ism_template` still match the new name?** A literal pattern (`logs-x-historical`) will not; a wildcard (`logs-x-*`) will. If it does not match, repoint it **before** cloning (step 1 of the procedure) - then ISM auto-enrols the clone at creation and no manual `_ism/add` is needed.
- **Does a *different* policy's `ism_template` match the new name?** If so the clone will auto-enrol on the wrong policy. Resolve the pattern overlap with the user before proceeding.

### 4. Age-based transitions - the one case where clone is wrong

```bash
osm -t <target> ism policy show <policy>
```

Clone stamps the target with a fresh `index.creation_date`. If the policy has any `min_index_age` condition, **every age clock restarts** - a 30-day delete becomes 30 days from the rename, silently.

- No age conditions (e.g. a no-op retention policy with a single state and no transitions): clone is safe, note it and continue.
- Age conditions present: **stop and raise it**. Either accept the reset explicitly, or use snapshot + restore with `rename_pattern`/`rename_replacement`, which preserves `creation_date`. That needs a configured snapshot repository - check `osm -t <target> _snapshot` before offering it.

### 5. Dashboards index patterns

```bash
osm -t <target> index-pattern list
```

A pattern matching the old name but not the new one needs updating or the data disappears from Dashboards. A wildcard covering both (`logs-x-*` for `logs-x-historical` → `logs-x-historical-nginx`) needs nothing.

### 6. Shard placement and disk

```bash
osm -t <target> '_cat/shards/<old>?v'
osm -t <target> '_cat/allocation?v'
```

Clone hard-links per shard on whichever node holds it, so it needs no meaningful extra space. Confirm the index is green first - cloning a red/yellow index inherits the problem. Note `number_of_replicas`; pass it explicitly in the clone body so the target does not pick up a template default.

## Procedure

### 1. Repoint the `ism_template` (only if step 3 found a non-matching pattern)

Do this **first**, before the clone exists:

```bash
osm -t <target> ism policy edit-ism-template <policy> \
    --replace-pattern <old> <new>
```

The old index keeps its own managed-index job; templates only apply at index creation, so this affects nothing until the clone appears.

### 2. Write-block the source

`_clone` requires it:

```python
c.fetch("<old>/_settings", method="PUT", json={"index.blocks.write": True})
```

### 3. Clone

```python
c.fetch("<old>/_clone/<new>", method="POST",
        json={"settings": {"index.number_of_replicas": <n>}})
```

Expect `acknowledged` and `shards_acknowledged` both true. This returns in seconds regardless of index size.

### 4. Clear the write block on the target

The target **inherits the block** from the read-only source and stays unwritable until cleared. Forgetting this is the most common way a rename appears to have broken the cluster.

```python
c.fetch("<new>/_settings", method="PUT", json={"index.blocks.write": None})
```

Clear it on the source too if the source is being kept.

### 5. Replay aliases (only if step 2 found any)

```python
c.fetch("_aliases", method="POST", json={"actions": [
    {"add": {"index": "<new>", "alias": "<alias>"}}]})
```

## Verification

All of it must pass before the source is deleted.

```bash
osm -t <target> '_cat/indices/<prefix>*?v'
```

`docs.count`, `docs.deleted` and `store.size` must be identical on both rows, and the new index green.

```python
src = c.fetch(f"{SRC}/_mapping")[SRC]["mappings"]
dst = c.fetch(f"{DST}/_mapping")[DST]["mappings"]
assert src == dst

VOLATILE = {"uuid", "provided_name", "creation_date", "version", "resize"}
def norm(i):
    s = c.fetch(f"{i}/_settings")[i]["settings"]["index"]
    return {k: v for k, v in s.items() if k not in VOLATILE}
```

Content fingerprint - a `stats` aggregation over the time field compares min, max and an exact sum across every document, which is far stronger evidence than a doc count alone:

```python
body = {"size": 0, "track_total_hits": True,
        "aggs": {"span": {"stats": {"field": "<time-field>"}}}}
assert (c.fetch(f"{SRC}/_search", method="POST", json=body)["aggregations"]
        == c.fetch(f"{DST}/_search", method="POST", json=body)["aggregations"])
```

ISM enrolment on the target must match the source's shape - same `policy_id`, `enabled: true`:

```bash
osm -t <target> '_plugins/_ism/explain/<new>'
```

If it shows `policy_id: null`, the template repoint did not take. Enrol manually and re-check:

```bash
osm -t <target> ism change-policy '<new>' <policy>
```

### Residual differences that are expected

These always differ after a clone and are not failures:

- `uuid` - unavoidable, it is a different index.
- `provided_name` - the point of the rename.
- `creation_date` - fresh. Only matters if step 4 found age conditions.
- `resize.source.name` / `resize.source.uuid` - clone provenance.
- `routing_partition_size: "1"` - the default made explicit.
- `routing.allocation.initial_recovery._id: null` - the resize allocation constraint, already released.

## Deleting the source

**Confirm with the user explicitly.** With no snapshot repository this is irreversible, and the clone's hard links mean keeping the source costs almost no disk - so "keep it for now" is a legitimate and cheap answer.

```bash
osm -t <target> index delete <old>
```

Then confirm the cluster settled:

```bash
osm -t <target> '_cluster/health'
osm -t <target> ism list | grep <new>
```

`status: green`, `unassigned_shards: 0`, and the new name listed against the expected policy.

## Pitfalls

- **Never reindex when clone will do.** Reindex costs O(docs) instead of O(1), resets `_seq_no`/`_version`, and silently inherits whatever index template matches the *new* name. Reach for it only to change shard count, mappings, or to cross clusters.
- **Clone cannot resize.** The target shard count always equals the source's.
- **ISM state resets.** Re-enrolment starts at the policy's `default_state`. Harmless for a single-state policy; for a multi-state one, read the source's state from explain first and restore it with `osm ism change-policy '<new>' <policy> --state <state>`.
- **Order matters.** Repointing `ism_template` after the clone leaves the new index in the "policy_id set, no managed_index doc" limbo that `ism-diagnose` reports - recoverable, but avoidable by doing it first.
- **A wildcard `ism_template` covering both names** means both indices are claimed while both exist. Fine for the duration of the rename, but do not leave it broader than intended once the source is gone.
