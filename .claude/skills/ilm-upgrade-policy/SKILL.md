---
name: ilm-upgrade-policy
description: Re-enrol OpenSearch indices on the latest version of an ISM policy. Trigger when `ilm-diagnose` (or `starsearch-cli ilm policy version`) shows indices "drifted" (policy_seq_no older than current) or "not enrolled" (policy_id set but no managed_index doc), and the user wants the updated policy to actually take effect. Mutating — requires user confirmation.
---

# ilm-upgrade-policy

Apply the *current* version of an ISM policy to managed indices that are pinned to an older version. OpenSearch ISM does NOT auto-migrate already-managed indices when a policy is edited — they stay pinned to the `policy_seq_no` they were enrolled with until you explicitly call `change_policy`. This skill does that safely.

## When to use

After `ilm-diagnose` reports:
- Drifted indices (policy_seq_no behind current).
- Not-enrolled indices (policy_id setting present, no managed_index doc).

Both are addressed by `starsearch-cli ilm change-policy`, which transparently falls back to `_plugins/_ism/add` when ISM reports an index as "not being managed".

## Procedure

### 1. Confirm scope before mutating

```bash
starsearch-cli ilm policy version
```

Confirm with the user which patterns to target. Prefer **narrow patterns** over `*` to avoid touching system indices (`.opendistro-*`, `.kibana_*`, etc.). For data-stream backing indices, `.ds-<prefix>-*` is the right shape.

### 2. Issue change-policy

```bash
starsearch-cli ilm change-policy '<pattern>' <policy-name>
```

The CLI POSTs `_plugins/_ism/change_policy/<pattern>` with `{"policy_id": "<name>"}`. The response splits into:
- `updated_indices` — successfully queued for the new policy version.
- `failed_indices` — listed with reasons. The two common reasons:
  - **`Cannot change policy while transitioning to new state`** — the index already has a queued change_policy from a previous call. Benign; ISM will apply the queued change at the next tick. Don't re-issue; just wait.
  - **`This index is not being managed`** — the index has no `policy_id` setting (no managed_index doc, not stamped by ISM template). The CLI auto-falls-back to `_plugins/_ism/add/<idx>` for these. Reported in the same row as `updated=N` reflecting the fallback successes.

### 3. (Optional, advanced) Force a specific state

For an index stuck in a failed/incorrect state, you can re-enrol AND reset its state in one call:

```bash
starsearch-cli ilm change-policy '<index>' <policy-name> --state <state>
```

Use this sparingly — it bypasses ISM's natural state machine. Common case: an index in `delete/failed` whose underlying block has been cleared (e.g. after `ilm-rollover-write-index`) but ISM has stopped auto-retrying.

### 4. Be aware: convergence is NOT immediate

The change is **queued**, not applied. Apparent `policy_seq_no` (per `ilm policy version`) updates after ISM next executes a step for that index. The per-index schedule interval is baked in at managed-index creation — typically 60 min — and is **not** affected by changing `plugins.index_state_management.job_interval` on the cluster.

If the user needs faster convergence:
- Lower `plugins.index_state_management.job_interval` (cluster setting) — affects **only new** managed-index docs going forward, not existing ones.
- Or `POST _plugins/_ism/remove/<idx>` then `POST _plugins/_ism/add/<idx>` to recreate the managed-index doc with the new interval. This destroys ISM execution state for the index — only do this if you're OK with the index restarting from default_state.

### 5. Verify after a tick

```bash
starsearch-cli ilm policy version
```

Indices that have ticked since change_policy will show green (current `_seq_no`). Indices still on the old `_seq_no` haven't ticked yet — wait or accept it.

## Confirmation prompts to use with the user

Before running:
- "Run `change-policy` on `<pattern>` to re-enrol N indices on `<policy>` (current `_seq_no=...`)?"
- If using `--state`, **always** show what state the indices will be reset to and confirm.

## Common pitfalls

- `change_policy` accepts wildcards but **also** applies to non-managed matches if you target a broad pattern. Sticking to `.ds-<prefix>-*` for data streams is the safe default.
- Calling change_policy on an index with an *already-queued* change returns the "Cannot change policy while transitioning" error. That doesn't mean the original queued change is lost — it's still in place. Wait for it to apply.
- For indices with `policy_id: null` and no `ism_template` match, change_policy / add will succeed but you may want to also fix the underlying template (see `ilm-template-coverage` for the template-side fix).
