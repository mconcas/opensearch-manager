---
name: ism-diagnose
description: Diagnose why an OpenSearch ISM policy "isn't applying" on a cluster. Triggers when the user asks why ISM policy edits aren't taking effect, why indices are stuck in a state, why deletion isn't happening, or wants a health check of a named policy. Surveys (a) per-index policy_seq_no drift, (b) failed ISM steps, (c) data streams with un-rolled-over backing indices, and (d) un-enrolled indices that have policy_id set but no managed_index doc. Read-only — no mutations.
---

# ism-diagnose

Walk the cluster end-to-end to explain why an ISM policy update isn't taking effect.

## When to use

The user reports any of:
- "I updated my ISM policy but it's not being applied."
- "Index X is stuck in the hot/cold/delete state."
- "Why isn't ISM rolling over my data stream?"
- "ISM says failed but nothing changes."

## Procedure

Run each step against the right `-t/--target` (or the default target). Do NOT mutate anything in this skill — diagnostics only.

### 1. Identify the target and the policy under suspicion

```bash
osm target list
osm ism policy show <policy-name>
```

Note the policy's `_seq_no` and `_primary_term` — this is the **current** version.

### 2. Per-index policy version drift

```bash
osm ism policy version
```

Three colours in the output:
- **Green (in sync)** — index is running on the current `_seq_no`. No action.
- **Yellow (drifted)** — index has a managed_index doc but `policy_seq_no` < current. ISM will pick up the new policy at the next state-boundary tick. If the index is stuck on `condition_not_met`, it won't tick on its own.
- **Red (not enrolled)** — index has `policy_id` setting but no managed_index doc. ISM coordinator sweep is supposed to enrol it (every 10 min by default). If it never enrols, the policy_id was stamped but the managed_index doc creation race lost.

Exit code 2 is returned if anything is drifted or not enrolled — scripts can use that.

### 3. Failed / stuck ISM steps

```bash
osm ism status --failed
osm jobs policy
```

Read the `Errors:` block carefully. Two common causes:
- "is the write index for data stream … and cannot be deleted" → use `ism-rollover-write-index`.
- `condition_not_met` for hours/days → the policy's rollover/transition condition is unreachable (e.g. `min_primary_shard_size: 30gb` on a 1 MB index with no max-age fallback). Policy-level fix, not a mechanical one.

### 4. Data-stream-level view

```bash
osm data-stream list
```

Look for `generation=1` on data streams that should have rolled over by now. If the cluster has many such streams *and* the policy's rollover condition is reachable (e.g. by size), then the policy isn't being applied — confirm with step 2.

### 5. Cross-reference if the policy is actually attached

For each affected index, fetch the raw ISM explain to look at:
- `index.plugins.index_state_management.policy_id` (should match the policy)
- `policy_seq_no` (the version under which ISM is *executing*)
- `state` / `action` / `step` (current execution position)
- `info.cause` (most useful failure reason)

```bash
osm '_plugins/_ism/explain/<index-name>'
```

To also inspect the queued change_policy on an index, query the ISM config index directly:

```bash
python3 -c "
import requests, json, urllib3; urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cfg = json.load(open('/home/<user>/.os-manager/config.json'))
srv = cfg['servers'][0]
base = f\"{srv['protocol']}://{srv['host']}{srv.get('cluster_path','')}\"
body = {'query': {'term': {'managed_index.index': '<index-name>'}}, 'size': 1}
r = requests.get(f'{base}/.opendistro-ism-config/_search', auth=(srv['username'], srv['password']), verify=False, headers={'Content-Type':'application/json'}, json=body)
print(json.dumps(r.json()['hits']['hits'][0]['_source']['managed_index'], indent=2))
"
```

The fields to look for:
- `managed_index.policy_seq_no` — what ISM **thinks** the index is on internally. May differ from `explain.policy_seq_no` (the last-executed value).
- `managed_index.change_policy` — non-null means a change is queued.
- `managed_index.schedule.interval.period` — per-index tick interval, baked in at managed-index creation. **Not** affected by changing the cluster-level `job_interval`.

### 6. Report

Summarise to the user:
- How many indices are drifted vs not enrolled vs in sync.
- Whether there are any failed steps.
- Whether the issue is **mechanical** (need change_policy / retry / rollover — fixable via the sibling skills) or **policy-level** (the policy itself can't progress under the current conditions — user has to edit it).

## Gotchas

- `policy_seq_no` in `_plugins/_ism/explain` is the *last-executed* version, not the current managed_index doc's value. The doc may already be on the new version internally — the explain catches up after the next step executes.
- `_plugins/_ism/explain/*` (with the `*`) returns entries even for indices with `policy_id: null` — `_plugins/_ism/explain` (no path) only returns managed ones.
- `total_managed_indices` in the explain response counts only fully-enrolled indices (those with a managed_index doc).
- Restricted index pattern `\.opendistro_security|\.kibana.*|\.opendistro-ism-config` is excluded from ISM by default. Don't try to manage those.
