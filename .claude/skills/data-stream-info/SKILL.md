---
name: data-stream-info
description: Inspect a data stream and the templates that govern its backing indices. Trigger when the user asks about a specific data stream (e.g. "what's the state of p2-staging-logs-app-foo?"), wants to see who the write index is, why new backing indices don't get a policy, or is debugging template inheritance. Read-only.
---

# data-stream-info

Walk a data stream from the top down: stream name → backing indices → index template → composed component templates → applied settings/mappings. Useful when ISM templates aren't auto-stamping policies on new backing indices, or when a data stream has unexpected settings.

## When to use

- "Why doesn't the new backing index have the policy attached?"
- "What template is this data stream using?"
- "Is the rollover threshold defined at the stream level or template level?"
- "Inventory all data streams matching `<prefix>-*`."

## Procedure

### 1. List data streams

```bash
starsearch-cli data-stream list                      # all
starsearch-cli data-stream list '<wildcard>'         # filtered
```

Output columns: `Name | Status | Gen | Backing | Write Idx | Template`.

Notes:
- `Gen=1` means the stream has never been rolled over. If the policy expects rollover, that's a red flag — confirm with `ilm-diagnose`.
- `Template` is the *index template* used to create new backing indices.

### 2. Inspect the index template

```bash
starsearch-cli '_index_template/<template-name>'
```

Look for:
- `index_patterns` — must match the data stream's backing index naming (`.ds-<stream>-*` or the alias). The cluster auto-creates a `.ds-<stream>-...` index per rollover.
- `template.settings.index.plugins.index_state_management.policy_id` — **if this is missing**, new backing indices come up with no policy, and ISM coordinator must sweep them in (every ~10 min by default). For reliable enrolment, this setting should be present.
- `composed_of` — list of component templates merged into this one. Last-wins on conflicts; component templates are applied in order, then the top-level template wins.
- `data_stream.timestamp_field` — must be `@timestamp` for the standard OpenSearch data-stream tooling.

### 3. Inspect each composed component template

```bash
starsearch-cli '_component_template/<component-name>'
```

The policy_id setting often belongs in a shared component template (e.g. `observability-common`) rather than each per-app index template — so a single edit applies to every data stream that composes it.

### 4. Inspect the current write index

```bash
starsearch-cli '_plugins/_ism/explain/.ds-<stream>-<latest-gen>'
```

Look for:
- `policy_id` — null means the index isn't enrolled (the bug we're diagnosing).
- `state` / `step` — current execution position.

### 5. (Cross-reference) Inspect the policy's `ism_template`

The policy may have an `ism_template` block that's *supposed* to auto-stamp the policy_id on matching indices during ISM coordinator sweeps:

```bash
starsearch-cli ilm policy show <policy-name>
# look at policy.ism_template[*].index_patterns
```

Pitfall: `ism_template` patterns must match the *backing-index* names (`.ds-<stream>-*`), not the data-stream name. And it's only applied at coordinator sweep time, leaving a race window after rollover. For deterministic enrolment, prefer setting `policy_id` directly in the index/component template (step 2).

## What "good" looks like

- Index template has `template.settings.index.plugins.index_state_management.policy_id` set to the right policy.
- Component template `observability-common` (or equivalent) is in `composed_of` and either provides the setting itself or doesn't override it.
- Policy's `ism_template` is still present as a backstop, with patterns that match the backing-index naming.
- New rollovers result in backing indices that immediately show `policy_id: <name>` in the explain output (no 10-min delay).
