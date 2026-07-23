---
name: ism-rollover-write-index
description: Manually roll over a data stream or write alias to unblock an ISM delete step. Trigger when an ISM delete action fails with "is the write index for data stream … and cannot be deleted", or the user asks to "force rollover" a data stream. After rollover, the previously-blocked backing index is no longer the write index and ISM can delete it on the next retry.
---

# ism-rollover-write-index

Unblock the most common ISM delete failure: a backing index that aged into the `delete` state but is still the write index of its data stream (because rollover never fired).

## When to use

`ism-diagnose` shows an index in `delete/attempt_delete/failed` with error:
> "index [...] is the write index for data stream [...] and cannot be deleted"

Or any time a user wants to force a rollover (small data stream that won't reach the size threshold, scheduled rotation, etc.).

## Procedure

### 1. Identify the data stream

The backing index name has the form `.ds-<datastream-name>-<generation>`. Strip the leading `.ds-` and trailing `-NNNNNN` to get the data stream name. The CLI can verify:

```bash
osm data-stream list <datastream-name>
```

Confirm:
- `Backing` count is 1 (single-index data stream — typical of the stuck case).
- `Write Idx` matches the index ISM is trying to delete.
- `Status` is GREEN.

### 2. Rollover

```bash
osm ism rollover <datastream-name>
```

This POSTs `<datastream-name>/_rollover`. Output:

```json
{
  "name": "...",
  "status": 200,
  "ok": true,
  "response": {
    "rolled_over": true,
    "old_index": ".ds-...-000001",
    "new_index": ".ds-...-000002",
    "conditions": {}
  }
}
```

`conditions: {}` means a forced rollover (no conditions evaluated) — that's expected when called against a data stream name directly.

### 3. Check the new write index has a policy attached

Brand-new backing indices in this cluster often come up with `policy_id: null` because the index template doesn't bake in the policy_id setting and the ISM coordinator sweep hasn't run yet (every 10 min by default).

```bash
osm '_plugins/_ism/explain/.ds-<name>-000NNN'
```

If `policy_id: null` and `enabled: null`, manually enrol it:

```bash
osm ism change-policy '.ds-<name>-000NNN' <policy-name>
```

(The CLI auto-falls-back to `_plugins/_ism/add` for un-managed indices.)

### 4. Retry the previously-blocked index

ISM may auto-retry on its own (if `consumed_retries < retry.count` in the policy). If `action.failed` is now `true`, force the retry:

```bash
osm ism retry '.ds-<name>-000001'
```

### 5. Verify

```bash
osm ism status '.ds-<name>-*'
```

The old backing index should disappear (deleted) within a tick. The new one should be in `hot`.

## Pitfalls

- **Don't rollover an alias that has rollover-on-write disabled in its data-stream config.** The CLI doesn't check this. The response will be a 400 with a specific message — read it before retrying.
- **Don't rollover if you only want to upgrade the policy version.** Use `ism-upgrade-policy` instead; rollover is a heavy operation that creates a new index, allocation, segments, etc.
- **The new backing index inherits its mapping from the data stream's index template.** If the template is wrong, rolling over makes a new index with the same wrong mapping. Fix the template first, then rollover.
- Rolling over also resets `policy_seq_no` *on the new index only* — the old index keeps its own metadata.
