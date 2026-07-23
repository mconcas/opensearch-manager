---
name: ism-retry-failed
description: Retry failed OpenSearch ISM steps. Trigger when `ism-diagnose` shows indices in step_status=failed, or the user says "ISM step failed" / "policy step keeps failing" / "stuck in retry". Calls `_plugins/_ism/retry/<idx>` to push the index out of failed state.
---

# ism-retry-failed

Re-arm ISM on indices that have hit a terminal failed state.

## When to use

After `ism-diagnose` reports indices with `step_status: failed` AND `action.failed: true` (the latter is the precondition for the retry endpoint to do anything).

**Beware the false positives:**
- `step_status: failed` with `action.failed: false` means ISM is mid-retry backoff — it'll retry on its own. The retry API returns "This index is not in failed state" for these.
- `step_status: condition_not_met` is NOT a failure — it's a polling step. The retry endpoint won't help. Fix is at the policy level (e.g. add `min_index_age` to rollover) or via `ism-upgrade-policy --state` to bump to a different state.

## Procedure

### 1. Verify state before retrying

```bash
osm ism status --failed
```

If the table is empty, there's nothing for this skill to do — re-route to `ism-diagnose`.

### 2. Read the underlying error

The `Errors:` section gives the actual cause. Common ones:
- "is the write index for data stream … and cannot be deleted" → resolve the data-stream block first via `ism-rollover-write-index`, then retry.
- "no such index" → upstream deleted it manually; ISM will resolve once it tries to access the missing index again.
- "ClusterBlockException ... no write" → cluster-level write block; resolve and retry.

Resolve the underlying cause before retrying. Retrying without addressing the cause just re-fails.

### 3. Retry

For a single index:
```bash
osm ism retry '<index-name>'
```

For a pattern (comma-separated or wildcard accepted by ISM):
```bash
osm ism retry '<pattern>'
```

To retry from a specific state in the policy (rare — usually you want the natural state):
```bash
osm ism retry '<pattern>' --state <state>
```

### 4. Verify

```bash
osm ism status '<index>'
```

After a couple of ticks, the step should either progress (good) or fail again (didn't fix the underlying cause — go back to step 2).

## Pitfalls

- The retry endpoint refuses if `action.failed=false`. Inspect the explain output if you get "not in failed state":
  ```bash
  osm '_plugins/_ism/explain/<index-name>'
  ```
  Look at `action.failed`, `action.consumed_retries`, `step.step_status`. If `action.failed: false` and `consumed_retries < retry.count` in the policy, ISM will auto-retry — just wait.
- `_plugins/_ism/retry` does NOT pick up a queued `change_policy`. If you want to both reset the state AND apply a new policy version, use `osm ism change-policy <idx> <policy> --state <state>` instead.
