"""Index State Management: policies, enrolment, templates, data streams, jobs."""

import fnmatch
import json
import time
from datetime import datetime

from .client import ApiError
from .output import (BLUE, GREEN, MAGENTA, RED, RESET, STATUS_COLORS, YELLOW,
                     format_bytes, format_duration, table)

# ISM state names are user-defined, so this is a convention: states named after
# a data tier get its colour, anything else prints uncoloured.
STATE_COLORS = {"hot": RED, "warm": YELLOW, "cold": BLUE}

# Indices ISM is actively working on, as opposed to idle or finished ones.
ACTIVE_STATUSES = {"running", "in_progress", "starting", "retrying", "failed",
                   "condition_not_met"}

SYSTEM_PREFIXES = (".opendistro", ".kibana", ".opensearch", ".plugins")


def explain(client, pattern="*"):
    """Per-index ISM explain output, minus the summary keys it mixes in."""
    data = client.fetch(f"_plugins/_ism/explain/{pattern}")
    return {name: info for name, info in data.items() if isinstance(info, dict)}


def _policy_id(info):
    return (info.get("index.plugins.index_state_management.policy_id")
            or info.get("policy_id"))


# --------------------------------------------------------------------------
# ism list - policy and state per index, largest first
# --------------------------------------------------------------------------

def list_indices(client, show_all=False):
    stats = client.fetch("*/_stats/store").get("indices", {})
    rows = []
    for name, info in explain(client).items():
        policy = _policy_id(info)
        if policy is None and not show_all:
            continue
        size = (stats.get(name, {}).get("total", {})
                .get("store", {}).get("size_in_bytes", 0))
        state = info.get("state") or {}
        rows.append({
            "index": name,
            "size": format_bytes(size),
            "size_bytes": size,
            "policy": policy or "unmanaged",
            "state": state.get("name", "-") if policy else "-",
        })
    rows.sort(key=lambda row: row["size_bytes"], reverse=True)
    return rows


def print_indices(rows):
    if not rows:
        print("No indices with ISM policies found")
        return
    table(rows,
          [("Index", "index"), ("Size", "size"), ("Policy", "policy"), ("State", "state")],
          row_color=lambda row: STATE_COLORS.get(row["state"], ""))


# --------------------------------------------------------------------------
# ism status - how each policy is actually executing
# --------------------------------------------------------------------------

def policy_status(client, index_filter=None, failed_only=False):
    now_ms = int(datetime.now().timestamp() * 1000)
    rows = []
    for name, info in explain(client, index_filter or "*").items():
        policy = _policy_id(info)
        if not policy:
            continue
        state, action = info.get("state") or {}, info.get("action") or {}
        step, retry_info = info.get("step") or {}, info.get("retry_info") or {}

        status = (step.get("step_status") or "").lower() or "unknown"
        failed = bool(action.get("failed") or retry_info.get("failed"))
        if failed and status not in ("failed", "retrying"):
            status = "failed"
        if failed_only and status not in ("failed", "retrying"):
            continue

        message = info.get("info") or {}
        if isinstance(message, dict):
            message = message.get("cause") or message.get("message") or ""
        rows.append({
            "index": name,
            "policy": policy,
            "state": state.get("name"),
            "action": action.get("name"),
            "step": step.get("name"),
            "step_status": status,
            "retries": int(action.get("consumed_retries")
                           or retry_info.get("consumed_retries") or 0),
            "time_in_step": (format_duration(now_ms - step["start_time"])
                             if step.get("start_time") else "-"),
            "error": str(message).strip() or ("(see ISM history)" if failed else ""),
        })

    rank = {"failed": 0, "retrying": 1, "running": 2, "in_progress": 2,
            "starting": 3, "condition_not_met": 4, "completed": 5}
    rows.sort(key=lambda row: (rank.get(row["step_status"], 9), row["index"]))
    return rows


def print_policy_status(rows):
    if not rows:
        print("No indices match the filter")
        return
    table(rows, [
        ("Index", "index"), ("Policy", "policy"), ("State", "state"),
        ("Action", "action"), ("Step", "step"), ("Status", "step_status"),
        ("Retries", "retries"), ("In Step", "time_in_step"),
    ], row_color=lambda row: STATUS_COLORS.get(row["step_status"], ""))

    failures = [row for row in rows
                if row["step_status"] in ("failed", "retrying") and row["error"]]
    if failures:
        print("\nErrors:")
        for row in failures:
            print(f"  {RED}✗{RESET} {row['index']} [{row['step']}] {row['error']}")

    counts = {}
    for row in rows:
        counts[row["step_status"]] = counts.get(row["step_status"], 0) + 1
    print(f"\nTotal: {len(rows)} index(es) - "
          + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))


# --------------------------------------------------------------------------
# ism settings / schedule - why the plugin ticks when it does
# --------------------------------------------------------------------------

def settings(client):
    """Effective `plugins.index_state_management.*` settings and their source."""
    data = client.fetch("_cluster/settings?include_defaults=true&flat_settings=true")
    prefix = "plugins.index_state_management."
    merged = {}
    # Later sources win: persistent overrides transient overrides defaults.
    for source in ("defaults", "transient", "persistent"):
        for key, value in (data.get(source) or {}).items():
            if key.startswith(prefix):
                merged[key] = {"setting": key, "value": value, "source": source}
    return sorted(merged.values(), key=lambda row: row["setting"])


def print_settings(rows):
    if not rows:
        print("No plugins.index_state_management.* settings found")
        return
    table(rows, [("Setting", "setting"), ("Value", "value"), ("Source", "source")],
          row_color=lambda row: "" if row["source"] == "defaults" else YELLOW)


def schedules(client, index_filter=None):
    """Each managed index's baked-in tick interval.

    The interval is copied from the cluster's `job_interval` when the managed
    index is created and is never revised afterwards, so an old index keeps
    ticking at whatever the setting was back then.
    """
    body = {
        "size": 1000,
        "query": {"exists": {"field": "managed_index"}},
        "_source": ["managed_index.index", "managed_index.policy_id",
                    "managed_index.policy_seq_no", "managed_index.schedule"],
    }
    hits = client.fetch(".opendistro-ism-config/_search", json=body)["hits"]["hits"]
    rows = []
    for hit in hits:
        managed = hit.get("_source", {}).get("managed_index") or {}
        name = managed.get("index")
        if index_filter and not fnmatch.fnmatchcase(name or "", index_filter):
            continue
        interval = (managed.get("schedule") or {}).get("interval") or {}
        rows.append({
            "index": name,
            "policy": managed.get("policy_id"),
            "interval": interval.get("period"),
            "unit": interval.get("unit"),
            "policy_seq_no": managed.get("policy_seq_no"),
        })
    rows.sort(key=lambda row: (row["interval"] or 0, row["index"] or ""))
    return rows


def print_schedules(rows):
    if not rows:
        print("No managed indices found")
        return
    table(rows, [("Index", "index"), ("Policy", "policy"), ("Interval", "interval"),
                 ("Unit", "unit"), ("Policy Seq", "policy_seq_no")])
    distribution = {}
    for row in rows:
        key = (row["interval"], row["unit"])
        distribution[key] = distribution.get(key, 0) + 1
    print("\nInterval distribution:")
    for (period, unit), count in sorted(distribution.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>4} index(es) on {period} {unit}")


# --------------------------------------------------------------------------
# Policy inspection
# --------------------------------------------------------------------------

def get_policy(client, name):
    return client.fetch(f"_plugins/_ism/policies/{name}")


def policy_version(client, index_filter=None, include_orphans=False):
    """Per-index policy version against the policy's current version.

    An index is *drifted* when it still runs an older revision of its policy,
    *not enrolled* when it carries a policy_id but ISM never built state for it,
    and an *orphan* when it has no policy_id at all - the outcome of a rollover
    that created a backing index before the template could stamp one.
    """
    current = {}

    def current_seq(policy):
        if policy not in current:
            try:
                current[policy] = get_policy(client, policy).get("_seq_no")
            except ApiError:
                current[policy] = None
        return current[policy]

    rows = []
    for name, info in explain(client, index_filter or "*").items():
        policy = _policy_id(info)
        if not policy:
            if not include_orphans or name.startswith(SYSTEM_PREFIXES):
                continue
            rows.append({"index": name, "policy": None, "index_seq_no": None,
                         "current_seq_no": None, "drift": False, "enrolled": False,
                         "orphan": True, "state": None, "step_status": None})
            continue

        index_seq = info.get("policy_seq_no")
        latest = current_seq(policy)
        state, step = info.get("state") or {}, info.get("step") or {}
        enrolled = index_seq is not None and bool(state)
        rows.append({
            "index": name,
            "policy": policy,
            "index_seq_no": index_seq,
            "current_seq_no": latest,
            "drift": enrolled and latest is not None and index_seq != latest,
            "enrolled": enrolled,
            "orphan": False,
            "state": state.get("name"),
            "step_status": step.get("step_status"),
        })

    rows.sort(key=lambda row: (_version_rank(row), row["index"]))
    return rows


def _version_rank(row):
    if row["orphan"]:
        return 0
    if not row["enrolled"]:
        return 1
    return 2 if row["drift"] else 3


def print_policy_version(rows):
    if not rows:
        print("No managed indices found")
        return
    colors = {0: MAGENTA, 1: RED, 2: YELLOW, 3: GREEN}
    display = [dict(row, rank=_version_rank(row),
                    enrolled="yes" if row["enrolled"] else "no",
                    drift="yes" if row["drift"] else "no") for row in rows]
    table(display, [
        ("Index", "index"), ("Policy", "policy"), ("Index Seq", "index_seq_no"),
        ("Current Seq", "current_seq_no"), ("Enrolled", "enrolled"),
        ("Drift", "drift"), ("State", "state"), ("Step Status", "step_status"),
    ], row_color=lambda row: colors[row["rank"]])

    counts = [0, 0, 0, 0]
    for row in rows:
        counts[_version_rank(row)] += 1
    parts = [f"{GREEN}{counts[3]} in sync{RESET}",
             f"{YELLOW}{counts[2]} drifted{RESET}",
             f"{RED}{counts[1]} not enrolled{RESET}"]
    if counts[0]:
        parts.append(f"{MAGENTA}{counts[0]} orphan{RESET}")
    print(f"\nTotal: {len(rows)} index(es) - " + ", ".join(parts))


def needs_attention(rows):
    """True when any index is drifted, un-enrolled, or an orphan."""
    return any(_version_rank(row) < 3 for row in rows)


# --------------------------------------------------------------------------
# Policy mutation - every edit is a read-modify-write under CAS
# --------------------------------------------------------------------------

def _update_policy(client, name, mutate):
    """Apply `mutate(policy) -> (before, after)` to a policy and store it back.

    The write is conditional on the sequence number that was read, so a
    concurrent edit fails with HTTP 409 rather than silently winning.
    """
    document = client.fetch(f"_plugins/_ism/policies/{name}")
    policy = document.get("policy")
    if not isinstance(policy, dict):
        raise ApiError(f"Policy '{name}' has no 'policy' body")

    before, after = mutate(policy)
    result = {"policy": name, "before": before, "after": after,
              "seq_no": document.get("_seq_no"), "changed": before != after}
    if not result["changed"]:
        result["new_seq_no"] = document.get("_seq_no")
        return result

    written = client.fetch(
        f"_plugins/_ism/policies/{name}?if_seq_no={document['_seq_no']}"
        f"&if_primary_term={document['_primary_term']}",
        method="PUT", json={"policy": policy},
    )
    result["new_seq_no"] = written.get("_seq_no")
    return result


def print_policy_change(result, subject):
    tag = " [no-op]" if not result["changed"] else ""
    print(f"  {GREEN}✓{RESET} {subject}{tag}  "
          f"_seq_no {result['seq_no']} -> {result['new_seq_no']}")
    print(f"      before: {json.dumps(result['before'])}")
    print(f"      after:  {json.dumps(result['after'])}")


def _apply_conditions(conditions, updates):
    """Merge `updates` into `conditions`; the value "none" drops a key."""
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and value.lower() == "none":
            conditions.pop(key, None)
        else:
            conditions[key] = value
    return conditions


def set_rollover(client, name, state_name="hot", **conditions):
    """Edit the rollover conditions of one state, leaving the rest untouched."""

    def mutate(policy):
        state = next((s for s in policy.get("states", [])
                      if s.get("name") == state_name), None)
        if state is None:
            raise ApiError(f"State '{state_name}' not found in policy '{name}'")
        action = next((a for a in state.get("actions", [])
                       if isinstance(a, dict) and "rollover" in a), None)
        if action is None:
            raise ApiError(f"State '{state_name}' has no rollover action; "
                           f"add one to the policy first")
        rollover = action["rollover"] or {}
        before = dict(rollover)
        action["rollover"] = _apply_conditions(rollover, conditions)
        return before, dict(action["rollover"])

    return _update_policy(client, name, mutate)


def set_transition(client, name, from_state, to_state, conditions, position="first"):
    """Upsert a transition out of `from_state` into `to_state`.

    A transition is matched by target state plus the exact set of condition
    keys, so `--min-index-age 30d` updates the age-based transition and leaves
    a size-based one to `to_state` alone. Dropping every condition of the
    matched transition removes the transition itself.
    """

    def mutate(policy):
        state = next((s for s in policy.get("states", [])
                      if s.get("name") == from_state), None)
        if state is None:
            raise ApiError(f"State '{from_state}' not found in policy '{name}'")
        transitions = state.setdefault("transitions", [])
        before = json.loads(json.dumps(transitions))

        match = next((
            i for i, t in enumerate(transitions)
            if isinstance(t, dict) and t.get("state_name") == to_state
            and set(t.get("conditions") or {}) == set(conditions)
        ), None)

        if match is not None:
            merged = _apply_conditions(dict(transitions[match].get("conditions") or {}),
                                       conditions)
            if merged:
                transitions[match]["conditions"] = merged
            else:
                transitions.pop(match)
        else:
            fresh = _apply_conditions({}, conditions)
            if not fresh:
                raise ApiError("All conditions were 'none' and no matching "
                               "transition exists to remove")
            transitions.insert(0 if position == "first" else len(transitions),
                               {"state_name": to_state, "conditions": fresh})
        return before, transitions

    return _update_policy(client, name, mutate)


def edit_ism_template(client, name, replace=(), add=(), remove=(),
                      entry_index=0, priority=None):
    """Edit the `ism_template` entries that decide which indices a policy claims.

    Replacements run first, then removals (entries left with no patterns are
    dropped), then additions and the priority, both against the entry at
    `entry_index` as it stands after the removals.
    """

    def mutate(policy):
        entries = policy.setdefault("ism_template", [])
        if not isinstance(entries, list):
            raise ApiError("ism_template is not a list")
        before = json.loads(json.dumps(entries))
        index = entry_index

        for old, new in replace:
            for entry in entries:
                patterns = entry.get("index_patterns") or []
                entry["index_patterns"] = list(dict.fromkeys(
                    new if pattern == old else pattern for pattern in patterns))

        if remove:
            surviving, dropped_before = [], 0
            for i, entry in enumerate(entries):
                patterns = [p for p in (entry.get("index_patterns") or [])
                            if p not in remove]
                entry["index_patterns"] = patterns
                if patterns:
                    surviving.append(entry)
                elif i < index:
                    dropped_before += 1
            entries[:] = surviving
            index = max(0, index - dropped_before)

        if add and not entries:
            entries.append({"index_patterns": [], "priority": 100})
            index = 0
        if (add or priority is not None) and not 0 <= index < len(entries):
            raise ApiError(f"entry-index {index} is out of range "
                           f"({len(entries)} entries)")
        if add:
            patterns = entries[index].get("index_patterns") or []
            entries[index]["index_patterns"] = list(dict.fromkeys(
                [*patterns, *add]))
        if priority is not None:
            entries[index]["priority"] = priority

        now_ms = int(time.time() * 1000)
        for i, entry in enumerate(entries):
            if i >= len(before) or entry != before[i]:
                entry["last_updated_time"] = now_ms
        return before, entries

    return _update_policy(client, name, mutate)


# --------------------------------------------------------------------------
# Enrolment and repair
# --------------------------------------------------------------------------

def change_policy(client, pattern, policy_id, state=None):
    """Move indices onto the current version of a policy.

    `change_policy` only touches indices ISM already manages, so indices it
    reports as unmanaged are enrolled with `add` instead.
    """
    body = {"policy_id": policy_id}
    if state:
        body["state"] = state
    result = client.fetch(f"_plugins/_ism/change_policy/{pattern}",
                          method="POST", json=body)

    unmanaged = [failure.get("index_name") for failure in result.get("failed_indices", [])
                 if "not being managed" in (failure.get("reason") or "").lower()]
    if not unmanaged:
        return result

    failures = [failure for failure in result.get("failed_indices", [])
                if "not being managed" not in (failure.get("reason") or "").lower()]
    added = 0
    for index in filter(None, unmanaged):
        response = client.fetch(f"_plugins/_ism/add/{index}", method="POST",
                                json={"policy_id": policy_id})
        added += int(response.get("updated_indices") or 0)
        failures.extend(response.get("failed_indices") or [])

    result["updated_indices"] = int(result.get("updated_indices") or 0) + added
    result["failed_indices"] = failures
    return result


def retry(client, pattern, state=None):
    body = {"state": state} if state else None
    return client.fetch(f"_plugins/_ism/retry/{pattern}", method="POST", json=body)


def rollover(client, name):
    return client.fetch(f"{name}/_rollover", method="POST")


def print_index_operation(result, subject):
    updated = result.get("updated_indices", result.get("updated", "-"))
    failures = result.get("failed_indices") or []
    icon = f"{RED}✗{RESET}" if failures else f"{GREEN}✓{RESET}"
    print(f"  {icon} {subject}  updated={updated}"
          + (f" failed={len(failures)}" if failures else ""))
    for failure in failures:
        name = failure.get("index_name") or failure.get("index") or "?"
        print(f"      {RED}✗{RESET} {name}: {failure.get('reason') or '(no reason)'}")


# --------------------------------------------------------------------------
# Templates - where a policy gets stamped onto new indices
# --------------------------------------------------------------------------

TEMPLATE_KINDS = {
    "index": ("_index_template", "index_templates", "index_template"),
    "component": ("_component_template", "component_templates", "component_template"),
}


def _templates(client, kind, name_filter=None):
    endpoint, envelope, inner = TEMPLATE_KINDS[kind]
    data = client.fetch(endpoint + (f"/{name_filter}" if name_filter else ""))
    return [(entry.get("name", "-"), entry.get(inner, {}))
            for entry in data.get(envelope, [])]


def _settings_policy(template):
    """The ISM policy_id in a template's settings, dotted or nested."""
    settings = (template.get("template") or {}).get("settings") or {}
    nested = settings.get("index")
    if isinstance(nested, dict):
        policy = ((nested.get("plugins") or {})
                  .get("index_state_management") or {}).get("policy_id")
        if policy:
            return policy
    return settings.get("index.plugins.index_state_management.policy_id")


def list_component_templates(client, name_filter=None):
    rows = [{"name": name, "policy_id": _settings_policy(template),
             "version": template.get("version")}
            for name, template in _templates(client, "component", name_filter)]
    rows.sort(key=lambda row: row["name"])
    return rows


def print_component_templates(rows):
    if not rows:
        print("No component templates found")
        return
    table(rows, [("Name", "name"), ("Policy ID", "policy_id"), ("Version", "version")],
          total="component template(s)")


def list_index_templates(client, name_filter=None):
    """Index templates with the policy they apply, inline or via composed_of."""
    inherited = {name: _settings_policy(template)
                 for name, template in _templates(client, "component")}

    rows = []
    for name, template in _templates(client, "index", name_filter):
        inline = _settings_policy(template)
        composed = template.get("composed_of") or []
        # OpenSearch merges composed_of in order, so the last one wins.
        source = next((c for c in reversed(composed) if inherited.get(c)), None)
        rows.append({
            "name": name,
            "index_patterns": ",".join(template.get("index_patterns") or []),
            "policy_id": inline or (inherited.get(source) if source else None),
            "source": "inline" if inline else (f"via {source}" if source else None),
            "composed_of": ",".join(composed),
        })
    rows.sort(key=lambda row: row["name"])
    return rows


def print_index_templates(rows):
    if not rows:
        print("No index templates found")
        return
    table(rows, [("Name", "name"), ("Patterns", "index_patterns"),
                 ("Policy ID", "policy_id"), ("Source", "source"),
                 ("Composed Of", "composed_of")], total="index template(s)")


def set_template_policy(client, kind, name, policy_id):
    """Bake an ISM policy_id into a template, or remove it with "none".

    The rest of the template - mappings, aliases, priority, _meta - is read
    back and written out unchanged.
    """
    endpoint = TEMPLATE_KINDS[kind][0]
    templates = _templates(client, kind, name)
    if not templates:
        raise ApiError(f"{kind.capitalize()} template '{name}' not found")
    template = templates[0][1]

    before = _settings_policy(template)
    settings = (template.setdefault("template", {})).setdefault("settings", {})
    if not isinstance(settings.get("index"), dict):
        settings["index"] = {}
    ism = settings["index"].setdefault("plugins", {}).setdefault(
        "index_state_management", {})

    after = None if policy_id.lower() == "none" else policy_id
    if after is None:
        ism.pop("policy_id", None)
        if not ism:
            settings["index"]["plugins"].pop("index_state_management", None)
        if not settings["index"]["plugins"]:
            settings["index"].pop("plugins", None)
    else:
        ism["policy_id"] = after
    # A stale dotted-form copy would shadow the nested value we just wrote.
    settings.pop("index.plugins.index_state_management.policy_id", None)

    client.fetch(f"{endpoint}/{name}", method="PUT", json=template)
    print(f"  {GREEN}✓{RESET} {kind}-template {name}: "
          f"policy_id {before or '(unset)'} -> {after or '(unset)'}")


# --------------------------------------------------------------------------
# Data streams
# --------------------------------------------------------------------------

def list_data_streams(client, name_filter=None):
    data = client.fetch("_data_stream" + (f"/{name_filter}" if name_filter else ""))
    rows = []
    for stream in data.get("data_streams", []):
        backing = stream.get("indices", [])
        rows.append({
            "name": stream.get("name"),
            "status": stream.get("status"),
            "generation": stream.get("generation"),
            "backing_count": len(backing),
            # The newest backing index is the one being written to.
            "write_index": backing[-1].get("index_name") if backing else None,
            "template": stream.get("template"),
        })
    rows.sort(key=lambda row: row["name"] or "")
    return rows


def print_data_streams(rows):
    if not rows:
        print("No data streams found")
        return
    table(rows, [("Name", "name"), ("Status", "status"), ("Gen", "generation"),
                 ("Backing", "backing_count"), ("Write Idx", "write_index"),
                 ("Template", "template")], total="data stream(s)")


# --------------------------------------------------------------------------
# Jobs - what the cluster is busy with
# --------------------------------------------------------------------------

# Health-check chatter, filtered out of `jobs list` unless --all is given.
NOISY_ACTIONS = ("cluster:monitor/", "indices:monitor/", "internal:")


def running_tasks(client, show_all=False, action_filter=None):
    rows = []
    for node in client.fetch("_tasks?detailed=true").get("nodes", {}).values():
        for task_id, task in node.get("tasks", {}).items():
            action = task.get("action", "")
            if not show_all and action.startswith(NOISY_ACTIONS):
                continue
            if action_filter and action_filter not in action:
                continue
            nanos = task.get("running_time_in_nanos") or 0
            description = task.get("description") or ""
            rows.append({
                "task_id": task_id,
                "node": node.get("name"),
                "action": action,
                "running_time": format_duration(nanos // 1_000_000),
                "running_ms": nanos // 1_000_000,
                "parent_task": task.get("parent_task_id"),
                "description": description[:77] + "..." if len(description) > 80 else description,
            })
    rows.sort(key=lambda row: row["running_ms"], reverse=True)
    return rows


def print_running_tasks(rows):
    if not rows:
        print("No running tasks")
        return
    table(rows, [("Task", "task_id"), ("Node", "node"), ("Action", "action"),
                 ("Running", "running_time"), ("Parent", "parent_task"),
                 ("Description", "description")], total="task(s)")


def pending_tasks(client):
    rows = []
    for task in client.fetch("_cluster/pending_tasks").get("tasks", []):
        source = task.get("source") or ""
        rows.append({
            "insert_order": task.get("insert_order"),
            "priority": task.get("priority"),
            "time_in_queue": task.get("time_in_queue")
                             or format_duration(task.get("time_in_queue_millis")),
            "queue_ms": task.get("time_in_queue_millis", 0),
            "source": source[:87] + "..." if len(source) > 90 else source,
        })
    rows.sort(key=lambda row: row["queue_ms"], reverse=True)
    return rows


def print_pending_tasks(rows):
    if not rows:
        print("No pending cluster tasks")
        return
    table(rows, [("Order", "insert_order"), ("Priority", "priority"),
                 ("Waiting", "time_in_queue"), ("Source", "source")],
          row_color=lambda row: STATUS_COLORS.get(row["priority"], ""),
          total="pending task(s)")


def policy_jobs(client):
    """Managed indices ISM is currently acting on, retrying, or failing."""
    return [row for row in policy_status(client)
            if row["step_status"] in ACTIVE_STATUSES]
