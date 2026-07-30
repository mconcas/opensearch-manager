# ISM policies

Index State Management moves indices through states on a schedule: roll over,
shrink, force merge, delete. `osm ism` inspects what ISM is actually doing and
edits policies in place.

See [Command reference](Command-Reference#osm-ism) for every flag.

## Inspecting

| Command | Answers |
|---|---|
| `osm ism list` | Which policy and state each index is in. `--all` includes unmanaged indices |
| `osm ism status [index]` | How each policy is executing, step by step. `--failed` narrows to failures and exits `1` if any |
| `osm ism settings` | The effective `plugins.index_state_management.*` cluster settings |
| `osm ism schedule [index]` | The tick interval baked into each index at enrolment |
| `osm ism policy show <name>` | The full policy JSON |
| `osm ism policy version [index]` | Whether each index runs the current revision of its policy |
| `osm jobs policy` | ISM work in flight right now |

## Enrolment and policy versions

An index is bound to the revision of the policy that existed when ISM enrolled
it. Editing a policy therefore does not change how already-enrolled indices
behave: they keep running the old revision until they are re-enrolled.

`osm ism policy version` compares each index's `policy_seq_no` against the
policy's current `_seq_no` and classifies it:

| State | Meaning |
|---|---|
| drifted | The index still runs an older revision of its policy |
| not enrolled | The index carries a `policy_id`, but ISM never built managed state for it |
| orphan | The index has no `policy_id` at all, typically a backing index created by a rollover before the template could stamp one. Shown under `--include-orphans` |

The command exits `2` when any index is drifted, un-enrolled, or an orphan, so a
check can be scripted:

```bash
osm ism policy version 'logs-*' || echo "re-enrolment needed"
```

`osm ism change-policy <pattern> <policy>` re-enrols indices on the policy's
current version. Run it after every policy edit that should affect existing
indices.

```bash
osm ism policy set-transition logs-policy hot delete --min-index-age 90d
osm ism change-policy 'logs-*' logs-policy
osm ism policy version 'logs-*'
```

## Editing semantics

Policy edits are read-modify-write under optimistic concurrency control. `osm`
reads the policy with its `_seq_no` and `_primary_term`, applies the change, and
writes it back conditionally. A concurrent edit to the same policy fails with
HTTP 409 instead of overwriting the other change. Re-run the command to apply
the edit on top of the new revision.

Each edit prints the `before` and `after` of just the part it touched, along
with the sequence number transition. An edit that changes nothing is reported as
`[no-op]` and performs no write.

Conditions merge into what is already there rather than replacing the whole set,
and the literal value `none` removes one:

```bash
osm ism policy set-rollover logs-policy --age 1d --primary-shard-size 50gb
osm ism policy set-rollover logs-policy --docs none
```

`set-transition` requires at least one `--min-*` condition. Dropping every
condition removes the transition entirely.

`edit-ism-template` changes which indices a policy claims. It needs at least one
of `--replace-pattern`, `--add-pattern`, `--remove-pattern` or `--priority`.
Where several policies claim the same index, the highest `priority` wins.

## Policies that only mark ownership

An index with no policy counts as unmanaged, which makes unmanaged-index alerts
noisy for indices that are meant to be kept forever. `osm ism policy create`
creates a policy with one state, no actions and no transitions, so enrolled
indices are managed but never modified or deleted:

```bash
osm ism policy create keep_forever --pattern 'logs-archive-*'
osm ism change-policy 'logs-archive-*' keep_forever
```

## When a policy is stuck

```bash
osm ism status --failed          # what failed, and where
osm ism retry '.ds-logs-app-000001'
```

A delete action on a data stream's write index cannot succeed: OpenSearch
refuses to delete the index a data stream is currently writing to. Roll the
stream over first, which makes the blocked index an ordinary backing index, then
retry:

```bash
osm ism rollover logs-app
osm ism retry '.ds-logs-app-000001'
```

## Templates

A policy reaches new indices either through its own `ism_template`, or through a
`policy_id` baked into an index or component template. Both are visible and
editable:

```bash
osm index-template list 'logs-*'
osm index-template set-policy logs-template logs-policy
osm component-template set-policy logs-settings none    # remove it
osm data-stream list 'logs-*'
```
