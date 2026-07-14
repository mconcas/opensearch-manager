import requests
import json
import sys
from datetime import datetime, timedelta
import urllib3

# Disable SSL warnings when verify_ssl is False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


COLORS = {
    "hot": "\033[91m",      # red
    "warm": "\033[93m",     # orange/yellow
    "cold": "\033[94m",     # blue
    "reset": "\033[0m"
}

# Status colors for jobs / policy execution tables
STATUS_COLORS = {
    "failed":     "\033[91m",  # red
    "retrying":   "\033[91m",  # red
    "running":    "\033[93m",  # yellow
    "in_progress":"\033[93m",  # yellow
    "starting":   "\033[93m",  # yellow
    "condition_not_met": "\033[93m",
    "completed":  "\033[92m",  # green
    "success":    "\033[92m",  # green
    "ok":         "\033[92m",  # green
    "URGENT":     "\033[91m",
    "HIGH":       "\033[93m",
    "NORMAL":     "",
    "LOW":        "\033[94m",
    "reset":      "\033[0m"
}


def format_duration(value, unit="ms"):
    """Format a duration value into a compact human-readable string.

    unit: 'ms' or 'ns'.
    """
    if value is None:
        return "-"
    try:
        v = int(value)
    except (TypeError, ValueError):
        return "-"
    if unit == "ns":
        v = v // 1_000_000  # to ms
    if v < 1000:
        return f"{v}ms"
    seconds = v / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{int(minutes)}m{int(seconds % 60)}s"
    hours = minutes / 60.0
    if hours < 24:
        return f"{int(hours)}h{int(minutes % 60)}m"
    days = hours / 24.0
    return f"{int(days)}d{int(hours % 24)}h"


def _detect_distribution(base_url, auth, verify_ssl):
    """Return True if the cluster behind base_url is OpenSearch."""
    try:
        resp = requests.get(f"{base_url}/", auth=auth, verify=verify_ssl)
        info = resp.json()
        return "opensearch" in info.get("version", {}).get("distribution", "").lower()
    except Exception:
        return False


def parse_age_to_days(age_str):
    """Convert age string like '30d', '2h' to days."""
    if age_str.endswith("d"):
        return int(age_str[:-1])
    elif age_str.endswith("h"):
        return int(age_str[:-1]) / 24
    elif age_str.endswith("m"):
        return int(age_str[:-1]) / (24 * 60)
    return 0


def format_bytes(bytes_val):
    """Format bytes into human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}PB"


def set_policy_delete_phase(config, policy_name, days, target=None):
    """Add or update delete phase in an ILM policy."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Get current policy
    policy_resp = requests.get(f"{base_url}/_ilm/policy/{policy_name}", auth=auth, verify=verify_ssl)
    if policy_resp.status_code != 200:
        return {"error": f"Policy '{policy_name}' not found"}

    policy_data = policy_resp.json()
    policy = policy_data[policy_name]["policy"]

    # Add/update delete phase
    if "phases" not in policy:
        policy["phases"] = {}

    policy["phases"]["delete"] = {
        "min_age": f"{days}d",
        "actions": {
            "delete": {
                "delete_searchable_snapshot": True
            }
        }
    }

    # Update policy
    update_resp = requests.put(
        f"{base_url}/_ilm/policy/{policy_name}",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"policy": policy})
    )

    if update_resp.status_code in [200, 201]:
        return {
            "success": True,
            "policy": policy_name,
            "delete_after": f"{days}d",
            "message": f"Policy updated. Indices will be deleted after {days} days from creation."
        }
    else:
        return {"error": update_resp.text}


def set_policy_warm_phase(config, policy_name, days, target=None):
    """Add or update warm phase in an ILM policy."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Get current policy
    policy_resp = requests.get(f"{base_url}/_ilm/policy/{policy_name}", auth=auth, verify=verify_ssl)
    if policy_resp.status_code != 200:
        return {"error": f"Policy '{policy_name}' not found"}

    policy_data = policy_resp.json()
    policy = policy_data[policy_name]["policy"]

    # Add/update warm phase
    if "phases" not in policy:
        policy["phases"] = {}

    policy["phases"]["warm"] = {
        "min_age": f"{days}d",
        "actions": {
            "set_priority": {
                "priority": 50
            }
        }
    }

    # Update policy
    update_resp = requests.put(
        f"{base_url}/_ilm/policy/{policy_name}",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"policy": policy}),
        auth=auth,
        verify=verify_ssl
    )

    if update_resp.status_code in [200, 201]:
        return {
            "success": True,
            "policy": policy_name,
            "warm_after": f"{days}d",
            "message": f"Policy updated. Indices will move to warm after {days} days."
        }
    else:
        return {"error": update_resp.text}


def set_policy_cold_phase(config, policy_name, days, target=None):
    """Add or update cold phase in an ILM policy."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Get current policy
    policy_resp = requests.get(f"{base_url}/_ilm/policy/{policy_name}", auth=auth, verify=verify_ssl)
    if policy_resp.status_code != 200:
        return {"error": f"Policy '{policy_name}' not found"}

    policy_data = policy_resp.json()
    policy = policy_data[policy_name]["policy"]

    # Add/update cold phase
    if "phases" not in policy:
        policy["phases"] = {}

    policy["phases"]["cold"] = {
        "min_age": f"{days}d",
        "actions": {
            "set_priority": {
                "priority": 0
            }
        }
    }

    # Update policy
    update_resp = requests.put(
        f"{base_url}/_ilm/policy/{policy_name}",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"policy": policy}),
        auth=auth,
        verify=verify_ssl
    )

    if update_resp.status_code in [200, 201]:
        return {
            "success": True,
            "policy": policy_name,
            "cold_after": f"{days}d",
            "message": f"Policy updated. Indices will move to cold after {days} days."
        }
    else:
        return {"error": update_resp.text}


def set_policy_rollover(config, policy_name, max_size, max_docs, target=None):
    """Add or update rollover settings in an ILM policy."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Get current policy
    policy_resp = requests.get(f"{base_url}/_ilm/policy/{policy_name}", auth=auth, verify=verify_ssl)
    if policy_resp.status_code != 200:
        return {"error": f"Policy '{policy_name}' not found"}

    policy_data = policy_resp.json()
    policy = policy_data[policy_name]["policy"]

    # Add/update hot phase with rollover
    if "phases" not in policy:
        policy["phases"] = {}
    if "hot" not in policy["phases"]:
        policy["phases"]["hot"] = {"min_age": "0ms", "actions": {}}
    if "actions" not in policy["phases"]["hot"]:
        policy["phases"]["hot"]["actions"] = {}

    rollover_action = {}
    if max_size:
        rollover_action["max_primary_shard_size"] = max_size
    if max_docs:
        rollover_action["max_docs"] = int(max_docs)

    policy["phases"]["hot"]["actions"]["rollover"] = rollover_action

    # Update policy
    update_resp = requests.put(
        f"{base_url}/_ilm/policy/{policy_name}",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"policy": policy}),
        auth=auth,
        verify=verify_ssl
    )

    if update_resp.status_code in [200, 201]:
        return {
            "success": True,
            "policy": policy_name,
            "rollover": rollover_action,
            "message": f"Policy updated with rollover: {rollover_action}"
        }
    else:
        return {"error": update_resp.text}


def delete_index(config, index_name, target=None):
    """Delete an index."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Delete the index
    delete_resp = requests.delete(f"{base_url}/{index_name}", auth=auth, verify=verify_ssl)

    if delete_resp.status_code == 200:
        return {
            "success": True,
            "index": index_name,
            "message": f"Index '{index_name}' deleted successfully"
        }
    elif delete_resp.status_code == 404:
        return {"error": f"Index '{index_name}' not found"}
    else:
        return {"error": delete_resp.text}


# ES/OpenSearch field types that OpenSearch Dashboards renders with a proper
# type icon. Anything NOT in this set shows the generic "?" (unknown) icon in
# the index-pattern field list — those are the ones the user is usually hunting.
KNOWN_OSD_FIELD_TYPES = {
    # string family
    "text", "keyword", "wildcard", "constant_keyword", "match_only_text",
    "version", "string", "search_as_you_type",
    # number family
    "long", "integer", "short", "byte", "double", "float", "half_float",
    "scaled_float", "unsigned_long", "token_count",
    # date
    "date", "date_nanos",
    # misc recognised
    "boolean", "ip", "geo_point", "geo_shape",
    "object", "nested", "histogram", "murmur3", "attachment",
    # metadata fields
    "_source", "_id", "_index", "_type",
}

# Field types that OSD treats as string-like (icon renders as text/string).
STRING_LIKE_FIELD_TYPES = {
    "text", "keyword", "wildcard", "constant_keyword", "match_only_text",
    "version", "string", "search_as_you_type",
}


def get_field_caps(config, pattern, target=None,
                   only_non_keyword=False, only_conflicts=False,
                   only_unknown=False):
    """Inspect field types across an index pattern via the _field_caps API.

    Maps to what OpenSearch Dashboards shows in the index-pattern field list:
      - a field with a type NOT in KNOWN_OSD_FIELD_TYPES renders as "?" (unknown)
      - a field mapped as more than one type across matching indices is a conflict

    Filters (applied to the reported set):
      only_non_keyword - drop fields whose type is string-like (keyword/text/...)
      only_conflicts   - keep only fields with >1 type across indices
      only_unknown     - keep only fields OSD would render with the "?" icon
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    resp = requests.get(
        f"{base_url}/{pattern}/_field_caps",
        params={"fields": "*"},
        auth=auth, verify=verify_ssl,
    )

    if resp.status_code == 404:
        return {"error": f"No indices match pattern '{pattern}'"}
    if resp.status_code != 200:
        return {"error": resp.text}

    data = resp.json()
    raw_fields = data.get("fields", {})

    fields = []
    for name, type_map in sorted(raw_fields.items()):
        types = sorted(type_map.keys())
        is_conflict = len(types) > 1
        # Internal metadata fields (type/name starting with "_", e.g. _seq_no,
        # _version, _field_names) aren't shown in OSD's field list at all, so
        # don't flag them as the user-facing "?" icon.
        is_metadata = name.startswith("_") or all(t.startswith("_") for t in types)
        is_unknown = (not is_metadata) and any(
            t not in KNOWN_OSD_FIELD_TYPES for t in types
        )
        is_string_like = all(t in STRING_LIKE_FIELD_TYPES for t in types)

        # Aggregatable / searchable are reported per-type; collapse to "any".
        aggregatable = any(spec.get("aggregatable") for spec in type_map.values())
        searchable = any(spec.get("searchable") for spec in type_map.values())

        entry = {
            "field": name,
            "types": types,
            "conflict": is_conflict,
            "unknown": is_unknown,
            "string_like": is_string_like,
            "aggregatable": aggregatable,
            "searchable": searchable,
        }
        if is_conflict:
            # surface which indices carry which type, if provided
            entry["indices_by_type"] = {
                t: spec.get("indices")
                for t, spec in type_map.items() if spec.get("indices")
            }

        if only_conflicts and not is_conflict:
            continue
        if only_unknown and not is_unknown:
            continue
        if only_non_keyword and is_string_like:
            continue
        fields.append(entry)

    return {
        "pattern": pattern,
        "indices": data.get("indices", []),
        "total_fields": len(raw_fields),
        "reported_fields": len(fields),
        "fields": fields,
    }


def print_field_caps(result):
    """Pretty-print get_field_caps output. Returns an exit code."""
    if "error" in result:
        print(json.dumps(result, indent=2))
        return 1

    red = STATUS_COLORS.get("failed", "")
    reset = COLORS["reset"]
    yellow = COLORS["warm"]

    print(f"\nPattern: {result['pattern']}")
    print(f"Matching indices: {len(result['indices'])}")
    print(f"Fields: {result['reported_fields']} shown / {result['total_fields']} total")
    print("=" * 80)

    if not result["fields"]:
        print("(no fields match the given filters)")
        return 0

    for f in result["fields"]:
        flags = []
        if f["unknown"]:
            flags.append(f"{yellow}?unknown{reset}")
        if f["conflict"]:
            flags.append(f"{red}CONFLICT{reset}")
        flag_str = ("  [" + " ".join(flags) + "]") if flags else ""
        types_str = ",".join(f["types"])
        agg = "" if f["aggregatable"] else " (not aggregatable)"
        print(f"  {f['field']:<50} {types_str}{agg}{flag_str}")
        if f.get("indices_by_type"):
            for t, idxs in f["indices_by_type"].items():
                shown = ", ".join(idxs[:3]) + (" ..." if len(idxs) > 3 else "")
                print(f"      {t}: {shown}")

    print("=" * 80)
    n_unknown = sum(1 for f in result["fields"] if f["unknown"])
    n_conflict = sum(1 for f in result["fields"] if f["conflict"])
    print(f"{n_unknown} field(s) render as '?' (unknown type), {n_conflict} conflict(s)")
    return 0


# ES type -> OpenSearch Dashboards field type, mirroring OSD's
# castEsToKbnFieldTypeName(). Anything unmapped becomes "unknown", and a field
# whose indices disagree on the kbn type is collapsed to "conflict" (same as the
# OSD field list).
_ES_TO_KBN_TYPE = {
    "text": "string", "keyword": "string", "string": "string",
    "match_only_text": "string", "constant_keyword": "string",
    "wildcard": "string", "version": "string", "search_as_you_type": "string",
    "date": "date", "date_nanos": "date",
    "boolean": "boolean",
    "byte": "number", "double": "number", "float": "number",
    "half_float": "number", "integer": "number", "long": "number",
    "scaled_float": "number", "short": "number", "unsigned_long": "number",
    "token_count": "number",
    "geo_point": "geo_point", "geo_shape": "geo_shape",
    "ip": "ip", "attachment": "attachment", "murmur3": "murmur3",
    "nested": "nested", "object": "object", "histogram": "histogram",
    "_source": "_source", "_id": "string", "_index": "string", "_type": "string",
}


def _kbn_type(es_type):
    return _ES_TO_KBN_TYPE.get(es_type, "unknown")


def _should_read_from_doc_values(aggregatable, es_type):
    # Mirror of OSD's shouldReadFieldFromDocValues().
    return (
        aggregatable
        and es_type != "text"
        and not es_type.startswith("_")
        and es_type not in ("geo_shape", "flattened")
    )


def _build_index_pattern_fields(field_caps_fields):
    """Rebuild the OSD index-pattern 'fields' list from a _field_caps response.

    Replicates the shape OSD's _fields_for_wildcard produces so the refreshed
    saved object is byte-compatible with what the "Refresh field list" button
    writes: type/esTypes, searchable, aggregatable, readFromDocValues, and
    subType.multi.parent for multi-fields (e.g. jwt.username.keyword).
    """
    # Primary es type per field, so we can classify parents for multi-fields.
    primary_es_type = {}
    for name, type_map in field_caps_fields.items():
        types = sorted(type_map.keys())
        primary_es_type[name] = types[0] if types else None

    fields = []
    for name in sorted(field_caps_fields.keys()):
        type_map = field_caps_fields[name]
        es_types = sorted(type_map.keys())
        kbn_types = {_kbn_type(t) for t in es_types}

        aggregatable = any(spec.get("aggregatable") for spec in type_map.values())
        searchable = any(spec.get("searchable") for spec in type_map.values())

        if len(kbn_types) > 1:
            kbn_type = "conflict"
        else:
            kbn_type = next(iter(kbn_types))

        entry = {
            "count": 0,
            "name": name,
            "type": kbn_type,
            "esTypes": es_types,
            "scripted": False,
            "searchable": searchable,
            "aggregatable": aggregatable,
            "readFromDocValues": _should_read_from_doc_values(
                aggregatable, es_types[0]
            ),
        }

        # Multi-field detection: a dotted field whose parent is a leaf (not an
        # object/nested) is a multi-field, e.g. jwt.username.keyword under the
        # text field jwt.username. Parents that are objects (jwt) are plain
        # nested paths, not multi-fields.
        if "." in name:
            parent = name.rsplit(".", 1)[0]
            parent_es = primary_es_type.get(parent)
            if parent_es is not None and parent_es not in ("object", "nested"):
                entry["subType"] = {"multi": {"parent": parent}}

        fields.append(entry)

    return fields


def refresh_index_pattern(config, pattern_id, target=None, apply=False):
    """Refresh an index pattern's cached field list from the live mapping.

    This is the CLI equivalent of the OSD "Refresh field list" button: OSD keeps
    a cached copy of the mapping's fields inside the index-pattern saved object
    (in .kibana), and that cache goes stale when new fields are added to the
    mapping after the pattern was last refreshed. Aggregations/Controls read the
    cached list, so newly-mapped fields (and their .keyword sub-fields) won't
    appear until the cache is refreshed.

    With apply=False (default) nothing is written: the added/removed field diff
    is returned so the caller can review before mutating .kibana.
    """
    from .cli import (get_server, get_auth, get_verify_ssl,
                      get_cluster_base_url, use_dashboards_api)

    server, _ = get_server(config, target)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)
    cluster_url = get_cluster_base_url(server)

    if use_dashboards_api(server):
        return {"error": "refresh via Dashboards API not implemented; this "
                         "target uses direct .kibana access only"}

    # .kibana is a cluster index — use the cluster endpoint, not dashboards.
    doc_url = f"{cluster_url}/.kibana/_doc/index-pattern:{pattern_id}"

    resp = requests.get(doc_url, auth=auth, verify=verify_ssl)
    if resp.status_code == 404:
        return {"error": f"Index pattern '{pattern_id}' not found in .kibana"}
    if resp.status_code != 200:
        return {"error": resp.text}

    doc = resp.json()
    source = doc["_source"]
    ip = source.get("index-pattern", {})
    title = ip.get("title")
    if not title:
        return {"error": f"Saved object index-pattern:{pattern_id} has no title"}

    try:
        old_fields = json.loads(ip.get("fields", "[]"))
    except (ValueError, TypeError):
        old_fields = []
    old_by_name = {f["name"]: f for f in old_fields}

    # Live field capabilities for the pattern's title.
    fc = requests.get(
        f"{cluster_url}/{title}/_field_caps",
        params={"fields": "*"}, auth=auth, verify=verify_ssl,
    )
    if fc.status_code == 404:
        return {"error": f"No indices match pattern title '{title}'"}
    if fc.status_code != 200:
        return {"error": fc.text}
    raw_fields = fc.json().get("fields", {})

    fresh_regular = _build_index_pattern_fields(
        {n: tm for n, tm in raw_fields.items() if not n.startswith("_")}
    )

    # Preserve meta fields (_source/_id/_index/_score ...) and any scripted
    # fields from the existing cache — OSD keeps these across a refresh and some
    # (e.g. _score) don't appear in _field_caps at all.
    preserved = [f for f in old_fields
                 if f["name"].startswith("_") or f.get("scripted")]
    preserved_names = {f["name"] for f in preserved}
    fresh_regular = [f for f in fresh_regular if f["name"] not in preserved_names]

    # Carry over popularity counts for fields that already existed.
    for f in fresh_regular:
        old = old_by_name.get(f["name"])
        if old and old.get("count"):
            f["count"] = old["count"]

    new_fields = preserved + fresh_regular
    new_fields.sort(key=lambda f: f["name"])

    old_names = set(old_by_name.keys())
    new_names = {f["name"] for f in new_fields}
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)

    result = {
        "pattern_id": pattern_id,
        "title": title,
        "old_field_count": len(old_fields),
        "new_field_count": len(new_fields),
        "added": added,
        "removed": removed,
        "applied": False,
    }

    if not apply:
        result["dry_run"] = True
        return result

    # Write the refreshed field list back, preserving all other attributes.
    ip["fields"] = json.dumps(new_fields)
    source["index-pattern"] = ip
    put = requests.put(
        doc_url, json=source, auth=auth, verify=verify_ssl,
        headers={"Content-Type": "application/json"},
    )
    if put.status_code not in (200, 201):
        result["error"] = put.text
        return result
    result["applied"] = True
    return result


def print_refresh_index_pattern(result):
    """Pretty-print refresh_index_pattern output. Returns an exit code."""
    if "error" in result:
        print(json.dumps(result, indent=2))
        return 1

    green = STATUS_COLORS.get("completed", "")
    red = STATUS_COLORS.get("failed", "")
    reset = COLORS["reset"]

    mode = "DRY-RUN (no changes written)" if result.get("dry_run") else \
           ("APPLIED" if result.get("applied") else "NOT APPLIED")
    print(f"\nIndex pattern: {result['pattern_id']}  ({result['title']})")
    print(f"Mode: {mode}")
    print(f"Cached fields: {result['old_field_count']} -> {result['new_field_count']}")
    print("=" * 80)

    added, removed = result["added"], result["removed"]
    if added:
        print(f"{green}+ {len(added)} field(s) to be added:{reset}")
        for name in added:
            print(f"    + {name}")
    if removed:
        print(f"{red}- {len(removed)} field(s) to be removed:{reset}")
        for name in removed:
            print(f"    - {name}")
    if not added and not removed:
        print("Cache already matches the live mapping — nothing to refresh.")
    print("=" * 80)

    if result.get("dry_run"):
        print("Re-run without --dry-run to write the refreshed field list to .kibana.")
    return 0


def delete_index_pattern(config, pattern_id, target=None):
    """Delete an index pattern from .kibana or Dashboards API."""
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, get_cluster_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API (requires osd-xsrf header for DELETE)
        base_url = get_base_url(server)
        headers = {'osd-xsrf': 'true'}
        delete_resp = requests.delete(f"{base_url}/api/saved_objects/index-pattern/{pattern_id}", auth=auth, verify=verify_ssl, headers=headers)
    else:
        # Use direct .kibana index access (cluster index, not the Dashboards endpoint)
        cluster_url = get_cluster_base_url(server)
        delete_resp = requests.delete(f"{cluster_url}/.kibana/_doc/index-pattern:{pattern_id}", auth=auth, verify=verify_ssl)

    if delete_resp.status_code == 200:
        return {
            "success": True,
            "pattern_id": pattern_id,
            "message": f"Index pattern '{pattern_id}' deleted successfully"
        }
    elif delete_resp.status_code == 404:
        return {"error": f"Index pattern '{pattern_id}' not found"}
    else:
        return {"error": delete_resp.text}


def get_index_lifecycle_info(config, target=None, show_all=False):
    """Get ILM info for all indices with their lifecycle timelines."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Detect if this is OpenSearch or Elasticsearch
    cluster_resp = requests.get(f"{base_url}/", auth=auth, verify=verify_ssl)
    cluster_info = cluster_resp.json()
    is_opensearch = "opensearch" in cluster_info.get("version", {}).get("distribution", "").lower()

    if is_opensearch:
        # OpenSearch uses ISM (Index State Management)
        indices_resp = requests.get(f"{base_url}/_plugins/_ism/explain/*", auth=auth, verify=verify_ssl)
        policies_resp = requests.get(f"{base_url}/_plugins/_ism/policies", auth=auth, verify=verify_ssl)
    else:
        # Elasticsearch uses ILM
        indices_resp = requests.get(f"{base_url}/*/_ilm/explain", auth=auth, verify=verify_ssl)
        policies_resp = requests.get(f"{base_url}/_ilm/policy", auth=auth, verify=verify_ssl)

    indices_data = indices_resp.json()
    policies = policies_resp.json()

    # Get index stats for sizes
    stats_resp = requests.get(f"{base_url}/*/_stats/store", auth=auth, verify=verify_ssl)
    stats_data = stats_resp.json()

    results = []

    # Handle different response formats
    if is_opensearch:
        # OpenSearch: flat dict with index names as keys
        indices_dict = indices_data
    else:
        # Elasticsearch: nested under "indices" key
        indices_dict = indices_data.get("indices", {})

    for index_name, info in indices_dict.items():
        # Skip non-index metadata keys (e.g., total_managed_indices in OpenSearch)
        if not isinstance(info, dict):
            continue

        # Check if index has a policy (different fields for ES vs OpenSearch)
        if is_opensearch:
            has_policy = info.get("index.plugins.index_state_management.policy_id") is not None
            policy_name = info.get("index.plugins.index_state_management.policy_id")
        else:
            has_policy = "policy" in info
            policy_name = info.get("policy")

        # Skip unmanaged indices unless show_all is True
        if not has_policy:
            if not show_all:
                continue
            # Add unmanaged index
            size_bytes = stats_data.get("indices", {}).get(index_name, {}).get("total", {}).get("store", {}).get("size_in_bytes", 0)
            results.append({
                "index": index_name,
                "policy": "unmanaged",
                "phase": "-",
                "age": "-",
                "size_bytes": size_bytes,
                "size": format_bytes(size_bytes),
                "warm_at": "",
                "cold_at": "",
                "delete_at": ""
            })
            continue

        # Get size
        size_bytes = stats_data.get("indices", {}).get(index_name, {}).get("total", {}).get("store", {}).get("size_in_bytes", 0)

        if is_opensearch:
            # OpenSearch ISM - simpler structure
            state_name = info.get("state", {}).get("name", "unknown") if isinstance(info.get("state"), dict) else "unknown"
            result = {
                "index": index_name,
                "policy": policy_name,
                "phase": state_name,  # ISM uses "state" instead of "phase"
                "age": "-",
                "size_bytes": size_bytes,
                "size": format_bytes(size_bytes),
                "warm_at": "",
                "cold_at": "",
                "delete_at": ""
            }
        else:
            # Elasticsearch ILM - full lifecycle processing
            policy = policies.get(policy_name, {}).get("policy", {})
            phases = policy.get("phases", {})

            result = {
                "index": index_name,
                "policy": policy_name,
                "phase": info.get("phase", "unknown"),
                "age": info.get("age", "unknown"),
                "size_bytes": size_bytes,
                "size": format_bytes(size_bytes),
                "warm_at": "",
                "cold_at": "",
                "delete_at": ""
            }

            # Calculate when transitions happen using lifecycle_date_millis
            lifecycle_date = info.get("lifecycle_date_millis")
            if lifecycle_date:
                created = datetime.fromtimestamp(int(lifecycle_date) / 1000)

                for phase_name in ["warm", "cold", "delete"]:
                    if phase_name in phases:
                        min_age = phases[phase_name].get("min_age", "0d")
                    days = parse_age_to_days(min_age)
                    transition_date = created + timedelta(days=days)
                    result[f"{phase_name}_at"] = transition_date.strftime("%Y-%m-%d")

        results.append(result)

    # Sort by size descending
    results.sort(key=lambda x: x["size_bytes"], reverse=True)

    return results


def print_table(results):
    """Print results as a formatted table."""
    if not results:
        print("No indices with ILM policies found")
        return

    # Define columns
    headers = ["Index", "Size", "Policy", "Phase", "Age", "Warm At", "Cold At", "Delete At"]

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for r in results:
        col_widths[0] = max(col_widths[0], len(r["index"]))
        col_widths[1] = max(col_widths[1], len(r["size"]))
        col_widths[2] = max(col_widths[2], len(r["policy"]))
        col_widths[3] = max(col_widths[3], len(r["phase"]))
        col_widths[4] = max(col_widths[4], len(r["age"]))
        col_widths[5] = max(col_widths[5], len(r["warm_at"] or "-"))
        col_widths[6] = max(col_widths[6], len(r["cold_at"] or "-"))
        col_widths[7] = max(col_widths[7], len(r["delete_at"] or "-"))

    # Print header
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_row)
    print("-" * len(header_row))

    # Print rows
    for r in results:
        phase = r["phase"]
        color = COLORS.get(phase, "")
        reset = COLORS["reset"] if color else ""

        row = [
            f"{color}{r['index'].ljust(col_widths[0])}{reset}",
            f"{color}{r['size'].ljust(col_widths[1])}{reset}",
            f"{color}{r['policy'].ljust(col_widths[2])}{reset}",
            f"{color}{r['phase'].ljust(col_widths[3])}{reset}",
            f"{color}{r['age'].ljust(col_widths[4])}{reset}",
            f"{color}{(r['warm_at'] or '-').ljust(col_widths[5])}{reset}",
            f"{color}{(r['cold_at'] or '-').ljust(col_widths[6])}{reset}",
            f"{color}{(r['delete_at'] or '-').ljust(col_widths[7])}{reset}"
        ]
        print("  ".join(row))


def list_workspaces(config, target=None):
    """List OpenSearch Dashboards workspaces on the target (id, name, description).

    Uses the Dashboards `POST /api/workspaces/_list` API, which is global (not
    itself workspace-scoped). Requires the target to have a 'dashboards' endpoint.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    if not use_dashboards_api(server):
        return {"error": "Workspaces require a 'dashboards' endpoint in the target config"}

    base_url = get_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    resp = requests.post(
        f"{base_url}/api/workspaces/_list",
        headers={"osd-xsrf": "true", "Content-Type": "application/json"},
        json={},
        auth=auth,
        verify=verify_ssl,
    )
    if resp.status_code != 200:
        return {"error": f"Failed to list workspaces: HTTP {resp.status_code}: {resp.text}"}

    try:
        body = resp.json()
    except ValueError:
        return {"error": f"Unexpected response: {resp.text}"}

    # Response shape: {"success": true, "result": {"workspaces": [...]}} across OSD versions;
    # tolerate a bare list under `result` too.
    result = body.get("result", body)
    workspaces = result.get("workspaces", result) if isinstance(result, dict) else result
    if not isinstance(workspaces, list):
        return {"error": f"Unexpected response: {json.dumps(body)}"}

    return [
        {
            "id": ws.get("id"),
            "name": ws.get("name"),
            "description": ws.get("description", ""),
        }
        for ws in workspaces
    ]


def print_workspaces(results):
    """Pretty-print the workspace list from list_workspaces()."""
    if not results:
        print("No workspaces found.")
        return
    print(f"\n{'ID':<24} {'NAME':<30} DESCRIPTION")
    print("=" * 90)
    for ws in results:
        print(f"{(ws.get('id') or ''):<24} {(ws.get('name') or ''):<30} {ws.get('description') or ''}")
    print(f"\nTotal: {len(results)} workspace(s)")


def list_dashboards(config, target=None, obj_type=None, workspace=None):
    """List saved objects (dashboards, visualizations, searches) from .kibana or Dashboards API."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url, get_dashboards_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API (workspace-scoped when a workspace is set)
        api_base = get_dashboards_base_url(server, workspace)
        if obj_type:
            url = f"{api_base}/api/saved_objects/_find?type={obj_type}&per_page=1000"
        else:
            url = f"{api_base}/api/saved_objects/_find?type=dashboard&type=visualization&type=search&per_page=1000"

        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch saved objects: {resp.status_code}"}

        data = resp.json()
        results = []

        for obj in data.get('saved_objects', []):
            obj_id = obj['id']
            obj_type_val = obj['type']
            attrs = obj.get('attributes', {})
            title = attrs.get('title', 'N/A')

            results.append({
                'type': obj_type_val,
                'id': obj_id,
                'title': title
            })
    else:
        # Use direct .kibana index access (cluster index, not the Dashboards endpoint)
        cluster_url = get_cluster_base_url(server)
        url = f"{cluster_url}/.kibana/_search?size=1000"
        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch saved objects: {resp.status_code}"}

        data = resp.json()
        results = []

        for hit in data['hits']['hits']:
            source = hit['_source']
            hit_type = source.get('type', 'unknown')

            if obj_type and hit_type != obj_type:
                continue

            if hit_type not in ['dashboard', 'visualization', 'search']:
                continue

            obj_data = source.get(hit_type, {})
            title = obj_data.get('title', 'N/A')
            obj_id = hit['_id']
            # Remove type prefix if present
            if ':' in obj_id:
                obj_id = obj_id.split(':', 1)[1]

            results.append({
                'type': hit_type,
                'id': obj_id,
                'title': title
            })

    return results


def _count_cached_fields(fields):
    """Return the number of cached fields in an index-pattern's 'fields' attribute.

    OSD stores the cached field list as a JSON-encoded string. Returns 0 when it
    is missing/empty and None when it can't be parsed (shown as 'n/a').
    """
    if not fields:
        return 0
    try:
        return len(json.loads(fields))
    except (ValueError, TypeError):
        return None


def list_index_patterns(config, target=None):
    """List all index patterns from .kibana index or Dashboards API."""
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, get_cluster_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API
        base_url = get_base_url(server)
        url = f"{base_url}/api/saved_objects/_find?type=index-pattern&per_page=1000"
        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch saved objects: {resp.status_code}"}

        data = resp.json()
        results = []

        for obj in data.get('saved_objects', []):
            pattern_id = obj['id']
            attrs = obj.get('attributes', {})
            title = attrs.get('title', 'N/A')
            # Workspace scoping: prefer OSD 'workspaces', fall back to 'namespaces'.
            workspaces = obj.get('workspaces') or obj.get('namespaces') or []

            results.append({
                'id': pattern_id,
                'title': title,
                'time_field': attrs.get('timeFieldName') or '',
                'workspaces': workspaces,
                'updated_at': obj.get('updated_at') or '',
                'cached_fields': _count_cached_fields(attrs.get('fields')),
            })
    else:
        # Use direct .kibana index access (cluster index, not the Dashboards endpoint)
        cluster_url = get_cluster_base_url(server)
        url = f"{cluster_url}/.kibana/_search?size=1000"
        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch saved objects: {resp.status_code}"}

        data = resp.json()
        results = []

        for hit in data['hits']['hits']:
            source = hit['_source']
            hit_type = source.get('type', 'unknown')

            if hit_type != 'index-pattern':
                continue

            obj_data = source.get('index-pattern', {})
            title = obj_data.get('title', 'N/A')
            obj_id = hit['_id']
            # Remove type prefix if present
            if ':' in obj_id:
                obj_id = obj_id.split(':', 1)[1]
            # Direct .kibana docs carry a single 'namespace' string.
            namespace = source.get('namespace')
            workspaces = [namespace] if namespace else []

            results.append({
                'id': obj_id,
                'title': title,
                'time_field': obj_data.get('timeFieldName') or '',
                'workspaces': workspaces,
                'updated_at': source.get('updated_at') or '',
                'cached_fields': _count_cached_fields(obj_data.get('fields')),
            })

    return results


def delete_saved_object(config, obj_id, obj_type, target=None, workspace=None):
    """Delete a saved object (dashboard, visualization, or search) from .kibana or Dashboards API.

    Args:
        config: Configuration dictionary
        obj_id: ID of the object to delete
        obj_type: Type of object - "dashboard", "visualization", or "search"
        target: Optional server name
        workspace: Optional OSD workspace id to scope the deletion to
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url, get_dashboards_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API (requires osd-xsrf header for DELETE),
        # workspace-scoped when a workspace is set.
        api_base = get_dashboards_base_url(server, workspace)
        headers = {'osd-xsrf': 'true'}
        delete_resp = requests.delete(f"{api_base}/api/saved_objects/{obj_type}/{obj_id}", auth=auth, verify=verify_ssl, headers=headers)
        if delete_resp.status_code == 200:
            return {
                "success": True,
                "id": obj_id,
                "type": obj_type,
                "message": f"{obj_type.capitalize()} '{obj_id}' deleted successfully"
            }
        elif delete_resp.status_code == 404:
            return {"error": f"{obj_type.capitalize()} '{obj_id}' not found"}
        else:
            return {"error": delete_resp.text}
    else:
        # Use direct .kibana index access (cluster index, not the Dashboards endpoint)
        cluster_url = get_cluster_base_url(server)
        # Try with type prefix first
        delete_resp = requests.delete(f"{cluster_url}/.kibana/_doc/{obj_type}:{obj_id}", auth=auth, verify=verify_ssl)

        if delete_resp.status_code == 200:
            return {
                "success": True,
                "id": obj_id,
                "type": obj_type,
                "message": f"{obj_type.capitalize()} '{obj_id}' deleted successfully"
            }
        elif delete_resp.status_code == 404:
            # Try without prefix
            delete_resp = requests.delete(f"{cluster_url}/.kibana/_doc/{obj_id}", auth=auth, verify=verify_ssl)
            if delete_resp.status_code == 200:
                return {
                    "success": True,
                    "id": obj_id,
                    "type": obj_type,
                    "message": f"{obj_type.capitalize()} '{obj_id}' deleted successfully"
                }
            return {"error": f"{obj_type.capitalize()} '{obj_id}' not found"}
        else:
            return {"error": delete_resp.text}


def print_saved_objects(results):
    """Print saved objects (dashboards/visualizations/searches/index-patterns) as a table."""
    if not results:
        print("No objects found")
        return

    # Check if results have 'type' field (saved objects) or just 'id' and 'title' (index patterns)
    has_type = results and 'type' in results[0]

    if has_type:
        # Calculate column widths for saved objects
        type_width = max(len(r['type']) for r in results) if results else 4
        type_width = max(type_width, len('Type'))
        id_width = max(len(r['id']) for r in results) if results else 2
        id_width = max(id_width, len('ID'))
        title_width = max(len(r['title']) for r in results) if results else 5
        title_width = max(title_width, len('Title'))

        # Print header
        header = f"{'Type'.ljust(type_width)}  {'ID'.ljust(id_width)}  {'Title'.ljust(title_width)}"
        print(header)
        print("-" * len(header))

        # Print rows
        for r in results:
            print(f"{r['type'].ljust(type_width)}  {r['id'].ljust(id_width)}  {r['title'].ljust(title_width)}")
    else:
        # Index patterns: show the richer attributes when available, falling back
        # to the plain ID/Title view for older-shaped results.
        def _cached(r):
            n = r.get('cached_fields')
            return 'n/a' if n is None else str(n)

        def _workspaces(r):
            return ', '.join(r.get('workspaces') or []) or '-'

        def _updated(r):
            # Trim the ISO timestamp to minute precision for a compact column.
            return (r.get('updated_at') or '').replace('T', ' ')[:16]

        columns = [
            ('ID', lambda r: r['id']),
            ('Title', lambda r: r['title']),
            ('Time Field', lambda r: r.get('time_field') or '-'),
            ('Workspaces', _workspaces),
            ('Fields', _cached),
            ('Updated', _updated),
        ]

        widths = []
        for name, getter in columns:
            widths.append(max([len(name)] + [len(getter(r)) for r in results]))

        header = "  ".join(name.ljust(w) for (name, _), w in zip(columns, widths))
        print(header)
        print("-" * len(header))

        for r in results:
            print("  ".join(getter(r).ljust(w) for (_, getter), w in zip(columns, widths)))


def list_detectors(config, target=None):
    """List all anomaly detection detectors from OpenSearch/Elasticsearch."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Try OpenSearch anomaly detection plugin API first
    url = f"{base_url}/_plugins/_anomaly_detection/detectors/_search"
    headers = {"Content-Type": "application/json"}
    body = {
        "query": {"match_all": {}},
        "size": 1000
    }

    resp = requests.post(url, headers=headers, json=body, auth=auth, verify=verify_ssl)

    # If that fails, try Elasticsearch ML API
    if resp.status_code == 404 or resp.status_code == 400:
        url = f"{base_url}/_ml/anomaly_detectors"
        resp = requests.get(url, auth=auth, verify=verify_ssl)

    if resp.status_code != 200:
        return {"error": f"Failed to fetch detectors: {resp.status_code} - {resp.text}"}

    data = resp.json()
    results = []

    # Handle OpenSearch response format
    if 'hits' in data and 'hits' in data['hits']:
        for hit in data['hits']['hits']:
            detector = hit.get('_source', {})
            detector_id = hit.get('_id', detector.get('detector_id', 'unknown'))
            name = detector.get('name', 'N/A')

            results.append({
                'id': detector_id,
                'title': name,
                'type': 'detector'
            })
    # Handle Elasticsearch response format
    elif 'jobs' in data:
        for job in data['jobs']:
            results.append({
                'id': job.get('job_id', 'unknown'),
                'title': job.get('description', job.get('job_id', 'N/A')),
                'type': 'detector'
            })
    # Handle direct detector list
    elif isinstance(data, dict) and 'detectors' in data:
        for detector in data['detectors']:
            detector_id = detector.get('detector_id', detector.get('id', 'unknown'))
            name = detector.get('name', 'N/A')
            results.append({
                'id': detector_id,
                'title': name,
                'type': 'detector'
            })

    return results


def export_detectors(config, target=None, detector_ids=None):
    """Export anomaly detection detectors to ndjson format."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    ndjson_lines = []

    # First, get all detectors
    url = f"{base_url}/_plugins/_anomaly_detection/detectors/_search"
    headers = {"Content-Type": "application/json"}
    body = {
        "query": {"match_all": {}},
        "size": 1000
    }

    resp = requests.post(url, headers=headers, json=body, auth=auth, verify=verify_ssl)

    # If that fails, try Elasticsearch ML API
    if resp.status_code == 404 or resp.status_code == 400:
        url = f"{base_url}/_ml/anomaly_detectors"
        resp = requests.get(url, auth=auth, verify=verify_ssl)

    if resp.status_code != 200:
        return {"error": f"Failed to fetch detectors: {resp.status_code} - {resp.text}"}

    data = resp.json()

    # Handle OpenSearch response format
    if 'hits' in data and 'hits' in data['hits']:
        for hit in data['hits']['hits']:
            detector = hit.get('_source', {})
            detector_id = hit.get('_id', detector.get('detector_id', 'unknown'))

            # Filter by detector_ids if specified
            if detector_ids and detector_id not in detector_ids:
                continue

            # Export detector configuration
            export_obj = {
                'id': detector_id,
                'type': 'detector',
                'detector': detector
            }

            ndjson_lines.append(json.dumps(export_obj))

    # Handle Elasticsearch response format
    elif 'jobs' in data:
        for job in data['jobs']:
            job_id = job.get('job_id', 'unknown')

            # Filter by detector_ids if specified
            if detector_ids and job_id not in detector_ids:
                continue

            export_obj = {
                'id': job_id,
                'type': 'detector',
                'detector': job
            }

            ndjson_lines.append(json.dumps(export_obj))

    # Handle direct detector list
    elif isinstance(data, dict) and 'detectors' in data:
        for detector in data['detectors']:
            detector_id = detector.get('detector_id', detector.get('id', 'unknown'))

            # Filter by detector_ids if specified
            if detector_ids and detector_id not in detector_ids:
                continue

            export_obj = {
                'id': detector_id,
                'type': 'detector',
                'detector': detector
            }

            ndjson_lines.append(json.dumps(export_obj))

    return '\n'.join(ndjson_lines) if ndjson_lines else ''


def export_saved_objects(config, target=None, obj_ids=None, obj_type=None, workspace=None):
    """Export saved objects (dashboards/visualizations/searches) to ndjson format with index-pattern mapping."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url, get_dashboards_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    index_pattern_map = {}
    ndjson_lines = []

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API (workspace-scoped when a workspace is set)
        api_base = get_dashboards_base_url(server, workspace)
        ip_resp = requests.get(f"{api_base}/api/saved_objects/_find?type=index-pattern&per_page=1000", auth=auth, verify=verify_ssl)
        if ip_resp.status_code != 200:
            return {"error": f"Failed to fetch index patterns: {ip_resp.status_code}"}

        ip_data = ip_resp.json()

        for obj in ip_data.get('saved_objects', []):
            obj_id = obj['id']
            title = obj.get('attributes', {}).get('title')
            if title:
                index_pattern_map[obj_id] = title

        url = f"{api_base}/api/saved_objects/_find?type=dashboard&type=visualization&type=search&per_page=1000"
        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch saved objects: {resp.status_code}"}

        data = resp.json()

        # Add index-pattern mapping as first line (metadata)
        ndjson_lines.append(json.dumps({"_index_pattern_map": index_pattern_map}))

        for obj in data.get('saved_objects', []):
            obj_id = obj['id']
            hit_type = obj['type']

            if obj_type and hit_type != obj_type:
                continue
            if obj_ids and obj_id not in obj_ids:
                continue

            export_obj = {
                'id': obj_id,
                'type': hit_type,
                'attributes': obj.get('attributes', {})
            }

            if 'kibanaSavedObjectMeta' in export_obj['attributes']:
                meta = export_obj['attributes']['kibanaSavedObjectMeta']
                if 'searchSourceJSON' in meta:
                    try:
                        search_source = json.loads(meta['searchSourceJSON'])
                        if 'query' in search_source:
                            if isinstance(search_source['query'], dict):
                                search_source['query']['query'] = ''
                        if 'filter' in search_source:
                            search_source['filter'] = []
                        meta['searchSourceJSON'] = json.dumps(search_source)
                    except:
                        pass

            if 'references' in obj:
                export_obj['references'] = obj['references']

            ndjson_lines.append(json.dumps(export_obj))
    else:
        # Use direct .kibana index access (cluster index, not the Dashboards endpoint)
        cluster_url = get_cluster_base_url(server)
        resp = requests.get(f"{cluster_url}/.kibana/_search?size=1000", auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch saved objects: {resp.status_code}"}

        data = resp.json()

        for hit in data['hits']['hits']:
            source = hit['_source']
            if source.get('type') == 'index-pattern':
                full_id = hit['_id']
                obj_id = full_id.split(':', 1)[1] if ':' in full_id else full_id
                title = source.get('index-pattern', {}).get('title')
                if title:
                    index_pattern_map[obj_id] = title

        ndjson_lines.append(json.dumps({"_index_pattern_map": index_pattern_map}))

        for hit in data['hits']['hits']:
            source = hit['_source']
            hit_type = source.get('type', 'unknown')
            full_id = hit['_id']

            obj_id = full_id.split(':', 1)[1] if ':' in full_id else full_id

            if obj_type and hit_type != obj_type:
                continue
            if obj_ids and obj_id not in obj_ids:
                continue
            if hit_type not in ['dashboard', 'visualization', 'search']:
                continue

            obj = {
                'id': obj_id,
                'type': hit_type,
                'attributes': source[hit_type]
            }

            if 'kibanaSavedObjectMeta' in obj['attributes']:
                meta = obj['attributes']['kibanaSavedObjectMeta']
                if 'searchSourceJSON' in meta:
                    try:
                        search_source = json.loads(meta['searchSourceJSON'])
                        if 'query' in search_source:
                            if isinstance(search_source['query'], dict):
                                search_source['query']['query'] = ''
                        if 'filter' in search_source:
                            search_source['filter'] = []
                        meta['searchSourceJSON'] = json.dumps(search_source)
                    except:
                        pass

            if 'references' in source:
                obj['references'] = source['references']

            ndjson_lines.append(json.dumps(obj))

    return '\n'.join(ndjson_lines)


def _flatten_mapping_fields(properties, prefix=""):
    """Recursively flatten an Elasticsearch/OpenSearch mapping 'properties' dict into dotted field paths.

    Handles:
      - Regular properties (e.g. 'message' -> type: text)
      - Multi-fields / sub-fields (e.g. 'message.keyword' via 'fields' key)
      - Nested/object properties (via nested 'properties' key)

    Returns a set of strings like {'message', 'message.keyword', 'host', 'host.name'}.
    """
    result = set()
    for field_name, field_def in properties.items():
        if not isinstance(field_def, dict):
            continue
        full_name = f"{prefix}{field_name}"
        result.add(full_name)

        # Multi-fields (e.g. text field with a .keyword sub-field)
        sub_fields = field_def.get("fields", {})
        if isinstance(sub_fields, dict):
            for sf_name in sub_fields:
                result.add(f"{full_name}.{sf_name}")

        # Nested / object properties
        sub_props = field_def.get("properties", {})
        if isinstance(sub_props, dict) and sub_props:
            result |= _flatten_mapping_fields(sub_props, prefix=f"{full_name}.")

    return result


def _extract_vis_fields(vis_obj):
    """Extract all field references from a visualization's visState and searchSourceJSON.

    Parses:
      - visState.aggs[].params.field (bucket/metric aggregation fields)
      - visState.aggs[].params.orderBy when it references a field
      - visState.params.field (e.g. for metric visualizations)
      - searchSourceJSON.filter[].meta.key (filter field references)
      - searchSourceJSON.filter[].query.match_phrase keys
      - visState.params.series[].fields (TSVB / timeline)

    Returns a list of dicts: [{'field': 'message.keyword', 'context': 'agg "Terms" (id: 2)'}]
    """
    fields = []
    attrs = vis_obj.get("attributes", {})

    # Parse visState
    vis_state_raw = attrs.get("visState")
    if isinstance(vis_state_raw, str):
        try:
            vis_state = json.loads(vis_state_raw)
        except (json.JSONDecodeError, ValueError):
            return fields
    elif isinstance(vis_state_raw, dict):
        vis_state = vis_state_raw
    else:
        return fields

    vis_type = vis_state.get("type", "unknown")

    # Walk aggregations
    aggs = vis_state.get("aggs", [])
    if isinstance(aggs, list):
        for agg in aggs:
            if not isinstance(agg, dict):
                continue
            params = agg.get("params", {})
            agg_type = agg.get("type", agg.get("schema", ""))
            agg_id = agg.get("id", "?")

            # Main field
            field = params.get("field")
            if field and isinstance(field, str):
                context = f'agg "{agg_type}" (id: {agg_id})'
                fields.append({"field": field, "context": context})

            # Some aggs have sub-aggs or custom fields
            order_by = params.get("orderBy")
            if isinstance(order_by, str) and order_by.startswith("_") is False and order_by not in ("_key", "_count", "_term"):
                # orderBy can reference another agg id — skip those
                pass

            # customLabel doesn't count, but json field in params does
            json_field = params.get("json")
            if isinstance(json_field, str) and json_field.strip():
                try:
                    custom_agg = json.loads(json_field)
                    _extract_fields_from_dict(custom_agg, fields, context=f'agg "{agg_type}" (id: {agg_id}) custom JSON')
                except (json.JSONDecodeError, ValueError):
                    pass

    # Walk params for TSVB and metric-type visualizations
    vis_params = vis_state.get("params", {})
    if isinstance(vis_params, dict):
        # Direct field reference
        pfield = vis_params.get("field")
        if pfield and isinstance(pfield, str):
            fields.append({"field": pfield, "context": f"vis params.field ({vis_type})"})

        # TSVB series
        series_list = vis_params.get("series", [])
        if isinstance(series_list, list):
            for i, series in enumerate(series_list):
                if not isinstance(series, dict):
                    continue
                metrics = series.get("metrics", [])
                if isinstance(metrics, list):
                    # Collect all metric IDs in this series so we can
                    # distinguish pipeline-agg internal refs from real fields.
                    metric_ids = {m.get("id") for m in metrics
                                  if isinstance(m, dict) and m.get("id")}
                    for m in metrics:
                        if isinstance(m, dict):
                            mfield = m.get("field")
                            if mfield and isinstance(mfield, str) and mfield not in metric_ids:
                                fields.append({"field": mfield, "context": f"TSVB series[{i}] metric"})
                split_by_field = series.get("terms_field")
                if split_by_field and isinstance(split_by_field, str):
                    fields.append({"field": split_by_field, "context": f"TSVB series[{i}] terms_field"})

    # Walk searchSourceJSON for filter field references
    meta = attrs.get("kibanaSavedObjectMeta", {})
    if isinstance(meta, dict):
        ss_raw = meta.get("searchSourceJSON")
        if isinstance(ss_raw, str):
            try:
                ss = json.loads(ss_raw)
                filters = ss.get("filter", [])
                if isinstance(filters, list):
                    for f in filters:
                        if not isinstance(f, dict):
                            continue
                        fmeta = f.get("meta", {})
                        if isinstance(fmeta, dict):
                            fkey = fmeta.get("key")
                            if fkey and isinstance(fkey, str):
                                fields.append({"field": fkey, "context": "searchSource filter meta.key"})
                        fquery = f.get("query", {})
                        if isinstance(fquery, dict):
                            for match_type in ("match_phrase", "match", "term", "range"):
                                if match_type in fquery and isinstance(fquery[match_type], dict):
                                    for fld in fquery[match_type]:
                                        fields.append({"field": fld, "context": f"searchSource filter {match_type}"})
            except (json.JSONDecodeError, ValueError):
                pass

    return fields


def _extract_fields_from_dict(d, fields_list, context=""):
    """Recursively extract 'field' keys from a nested dict (e.g. custom agg JSON)."""
    if isinstance(d, dict):
        for k, v in d.items():
            if k == "field" and isinstance(v, str):
                fields_list.append({"field": v, "context": context})
            else:
                _extract_fields_from_dict(v, fields_list, context)
    elif isinstance(d, list):
        for item in d:
            _extract_fields_from_dict(item, fields_list, context)


def _resolve_ip_for_object(obj, index_patterns):
    """Find the index-pattern id associated with a saved object via its references."""
    refs = obj.get("references", [])
    for ref in refs:
        if ref.get("type") == "index-pattern":
            return ref.get("id")
    return None


def validate_dashboards(config, target=None, dashboard_ids=None, verbose=False, workspace=None):
    """Validate dashboards for common problems: broken references, missing indices, bad queries.

    Args:
        config: Configuration dictionary
        target: Optional server name
        dashboard_ids: Optional list of dashboard IDs to validate (None = all)
        verbose: If True, include passing checks in the output
        workspace: Optional OSD workspace id to scope the lookup to

    Returns:
        dict with 'dashboards' (per-dashboard results) and 'global' (cross-cutting issues)
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_dashboards_base_url, get_cluster_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    cluster_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    issues_global = []
    dashboard_results = []

    # ── Step 1: Collect all saved objects and index patterns ──
    all_objects = {}   # id -> {type, title, attributes, references}
    index_patterns = {}  # id -> {title, timeFieldName, fields}

    if use_dashboards_api(server):
        # Fetch saved objects via Dashboards API (workspace-scoped when set)
        api_base = get_dashboards_base_url(server, workspace)
        for obj_type_q in ["dashboard", "visualization", "search", "index-pattern"]:
            page = 1
            while True:
                url = f"{api_base}/api/saved_objects/_find?type={obj_type_q}&per_page=1000&page={page}"
                resp = requests.get(url, auth=auth, verify=verify_ssl)
                if resp.status_code != 200:
                    issues_global.append({"level": "error", "message": f"Failed to fetch {obj_type_q} objects: HTTP {resp.status_code}"})
                    break
                data = resp.json()
                for obj in data.get("saved_objects", []):
                    oid = obj["id"]
                    otype = obj["type"]
                    attrs = obj.get("attributes", {})
                    refs = obj.get("references", [])
                    all_objects[f"{otype}:{oid}"] = {
                        "type": otype,
                        "id": oid,
                        "title": attrs.get("title", "N/A"),
                        "attributes": attrs,
                        "references": refs,
                    }
                    if otype == "index-pattern":
                        index_patterns[oid] = {
                            "title": attrs.get("title", ""),
                            "timeFieldName": attrs.get("timeFieldName"),
                        }
                total = data.get("total", 0)
                fetched = data.get("page", 1) * data.get("per_page", 1000)
                if fetched >= total:
                    break
                page += 1
    else:
        # Direct .kibana access
        url = f"{cluster_url}/.kibana/_search?size=10000"
        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch .kibana objects: HTTP {resp.status_code}"}
        data = resp.json()
        for hit in data["hits"]["hits"]:
            source = hit["_source"]
            otype = source.get("type", "unknown")
            full_id = hit["_id"]
            oid = full_id.split(":", 1)[1] if ":" in full_id else full_id
            attrs = source.get(otype, {})
            refs = source.get("references", [])
            all_objects[f"{otype}:{oid}"] = {
                "type": otype,
                "id": oid,
                "title": attrs.get("title", "N/A") if isinstance(attrs, dict) else "N/A",
                "attributes": attrs if isinstance(attrs, dict) else {},
                "references": refs,
            }
            if otype == "index-pattern":
                ip_attrs = source.get("index-pattern", {})
                if isinstance(ip_attrs, dict):
                    index_patterns[oid] = {
                        "title": ip_attrs.get("title", ""),
                        "timeFieldName": ip_attrs.get("timeFieldName"),
                    }

    # ── Step 2: Get cluster indices, aliases, and data streams (for index-pattern resolution) ──
    cluster_indices = set()
    cluster_aliases = set()
    data_stream_names = set()
    data_stream_backing_indices = set()  # backing indices of data streams
    try:
        cat_resp = requests.get(f"{cluster_url}/_cat/indices?format=json&h=index", auth=auth, verify=verify_ssl)
        if cat_resp.status_code == 200:
            for entry in cat_resp.json():
                cluster_indices.add(entry.get("index", ""))
        alias_resp = requests.get(f"{cluster_url}/_cat/aliases?format=json&h=alias", auth=auth, verify=verify_ssl)
        if alias_resp.status_code == 200:
            for entry in alias_resp.json():
                cluster_aliases.add(entry.get("alias", ""))
        # Fetch data streams — these don't appear in _cat/indices or _cat/aliases
        ds_resp = requests.get(f"{cluster_url}/_data_stream", auth=auth, verify=verify_ssl)
        if ds_resp.status_code == 200:
            ds_data = ds_resp.json()
            for ds in ds_data.get("data_streams", []):
                ds_name = ds.get("name", "")
                if ds_name:
                    data_stream_names.add(ds_name)
                for backing in ds.get("indices", []):
                    idx_name = backing.get("index_name", "")
                    if idx_name:
                        data_stream_backing_indices.add(idx_name)
    except Exception as e:
        issues_global.append({"level": "warning", "message": f"Could not fetch cluster indices: {e}"})

    # Combined set of all resolvable names
    all_resolvable = cluster_indices | cluster_aliases | data_stream_names | data_stream_backing_indices

    def pattern_matches_any_index(pattern_title):
        """Check if an index-pattern title matches at least one cluster index, alias, or data stream."""
        import fnmatch
        for name in all_resolvable:
            if fnmatch.fnmatch(name, pattern_title):
                return True
        return False

    def get_index_fields(pattern_title):
        """Get the full flattened field set by letting the cluster resolve the pattern.

        Calls GET /<pattern>/_mapping directly so the cluster handles data streams,
        aliases, and wildcards natively — no client-side fnmatch needed.

        Returns a set of dotted field paths, e.g. {'message', 'message.keyword', 'host', 'host.name', '@timestamp'}.
        """
        try:
            # Let the cluster resolve the pattern (works for indices, aliases, and data streams)
            mapping_resp = requests.get(f"{cluster_url}/{pattern_title}/_mapping", auth=auth, verify=verify_ssl)
            if mapping_resp.status_code == 200:
                mapping_data = mapping_resp.json()
                # Merge fields from all resolved indices (in case pattern matches multiple)
                all_fields = set()
                for idx_name, idx_info in mapping_data.items():
                    props = idx_info.get("mappings", {}).get("properties", {})
                    all_fields |= _flatten_mapping_fields(props)
                if all_fields:
                    return all_fields
        except Exception:
            pass
        return None

    # Cache for index field lookups (pattern_title -> field set)
    _field_cache = {}

    def get_index_fields_cached(pattern_title):
        """Cached wrapper around get_index_fields to avoid repeated mapping fetches."""
        if pattern_title not in _field_cache:
            _field_cache[pattern_title] = get_index_fields(pattern_title)
        return _field_cache[pattern_title]

    # ── Step 3: Validate index patterns globally ──
    for ip_id, ip_info in index_patterns.items():
        title = ip_info["title"]
        if not title:
            issues_global.append({"level": "error", "message": f"Index pattern '{ip_id}' has no title/pattern defined"})
            continue
        if not pattern_matches_any_index(title):
            issues_global.append({
                "level": "error",
                "message": f"Index pattern '{title}' (id: {ip_id}) does not match any cluster index or alias",
            })
        else:
            # Check time field
            time_field = ip_info.get("timeFieldName")
            if time_field:
                fields = get_index_fields_cached(title)
                if fields is not None and time_field not in fields:
                    issues_global.append({
                        "level": "warning",
                        "message": f"Index pattern '{title}': time field '{time_field}' not found in index mapping",
                    })

    # ── Step 4: Validate each dashboard ──
    dashboards = {k: v for k, v in all_objects.items() if v["type"] == "dashboard"}
    if dashboard_ids:
        dashboards = {k: v for k, v in dashboards.items() if v["id"] in dashboard_ids}

    for dkey, dashboard in dashboards.items():
        d_issues = []
        d_title = dashboard["title"]
        d_id = dashboard["id"]
        refs = dashboard.get("references", [])

        # Track what this dashboard depends on
        referenced_vis = []
        referenced_search = []
        referenced_ip = []

        for ref in refs:
            ref_type = ref.get("type", "")
            ref_id = ref.get("id", "")
            ref_name = ref.get("name", "")
            lookup_key = f"{ref_type}:{ref_id}"

            if ref_type == "visualization":
                referenced_vis.append(ref_id)
                if lookup_key not in all_objects:
                    d_issues.append({"level": "error", "check": "broken-reference",
                                     "message": f"Referenced visualization '{ref_id}' (name: {ref_name}) not found"})
            elif ref_type == "search":
                referenced_search.append(ref_id)
                if lookup_key not in all_objects:
                    d_issues.append({"level": "error", "check": "broken-reference",
                                     "message": f"Referenced search '{ref_id}' (name: {ref_name}) not found"})
            elif ref_type == "index-pattern":
                referenced_ip.append(ref_id)
                if ref_id not in index_patterns:
                    d_issues.append({"level": "error", "check": "broken-reference",
                                     "message": f"Referenced index pattern '{ref_id}' (name: {ref_name}) not found"})
                elif not pattern_matches_any_index(index_patterns[ref_id]["title"]):
                    d_issues.append({"level": "error", "check": "missing-index",
                                     "message": f"Index pattern '{index_patterns[ref_id]['title']}' has no matching indices"})

        # Also walk into referenced visualizations/searches to check their refs and fields
        for vis_id in referenced_vis:
            vis_key = f"visualization:{vis_id}"
            vis_obj = all_objects.get(vis_key)
            if not vis_obj:
                continue
            vis_refs = vis_obj.get("references", [])
            vis_ip_id = None  # track the index pattern this vis uses
            for ref in vis_refs:
                ref_type = ref.get("type", "")
                ref_id = ref.get("id", "")
                if ref_type == "index-pattern" and ref_id not in index_patterns:
                    d_issues.append({"level": "error", "check": "broken-reference",
                                     "message": f"Visualization '{vis_obj['title']}' references missing index pattern '{ref_id}'"})
                elif ref_type == "index-pattern" and ref_id in index_patterns:
                    vis_ip_id = ref_id
                    ip_title = index_patterns[ref_id]["title"]
                    if not pattern_matches_any_index(ip_title):
                        d_issues.append({"level": "error", "check": "missing-index",
                                         "message": f"Visualization '{vis_obj['title']}' uses index pattern '{ip_title}' with no matching indices"})
                elif ref_type == "search":
                    s_key = f"search:{ref_id}"
                    if s_key not in all_objects:
                        d_issues.append({"level": "error", "check": "broken-reference",
                                         "message": f"Visualization '{vis_obj['title']}' references missing search '{ref_id}'"})
                    else:
                        # The search may provide the index pattern
                        srch_obj = all_objects[s_key]
                        for sref in srch_obj.get("references", []):
                            if sref.get("type") == "index-pattern":
                                vis_ip_id = vis_ip_id or sref.get("id")

            # If vis doesn't have direct IP reference, check if its linked search has one
            if not vis_ip_id:
                vis_ip_id = _resolve_ip_for_object(vis_obj, index_patterns)

            # ── Field-level validation for this visualization ──
            if vis_ip_id and vis_ip_id in index_patterns:
                ip_title = index_patterns[vis_ip_id]["title"]
                mapping_fields = get_index_fields_cached(ip_title)
                if mapping_fields is not None:
                    vis_fields = _extract_vis_fields(vis_obj)
                    for fref in vis_fields:
                        fname = fref["field"]
                        # Skip internal/special fields
                        if fname.startswith("_") or fname == "*":
                            continue
                        if fname not in mapping_fields:
                            d_issues.append({
                                "level": "error",
                                "check": "missing-field",
                                "message": (
                                    f"Visualization '{vis_obj['title']}' (id: {vis_id}) "
                                    f"references field '{fname}' not found in index '{ip_title}' "
                                    f"[{fref['context']}]"
                                ),
                            })

            # Validate searchSourceJSON in visualization
            _validate_search_source(vis_obj, d_issues, "Visualization")

        for srch_id in referenced_search:
            srch_key = f"search:{srch_id}"
            srch_obj = all_objects.get(srch_key)
            if not srch_obj:
                continue
            srch_refs = srch_obj.get("references", [])
            srch_ip_id = None
            for ref in srch_refs:
                ref_type = ref.get("type", "")
                ref_id = ref.get("id", "")
                if ref_type == "index-pattern" and ref_id not in index_patterns:
                    d_issues.append({"level": "error", "check": "broken-reference",
                                     "message": f"Search '{srch_obj['title']}' references missing index pattern '{ref_id}'"})
                elif ref_type == "index-pattern" and ref_id in index_patterns:
                    srch_ip_id = ref_id
                    ip_title = index_patterns[ref_id]["title"]
                    if not pattern_matches_any_index(ip_title):
                        d_issues.append({"level": "error", "check": "missing-index",
                                         "message": f"Search '{srch_obj['title']}' uses index pattern '{ip_title}' with no matching indices"})

            # ── Field-level validation for saved searches (columns) ──
            if srch_ip_id and srch_ip_id in index_patterns:
                ip_title = index_patterns[srch_ip_id]["title"]
                mapping_fields = get_index_fields_cached(ip_title)
                if mapping_fields is not None:
                    # Check columns referenced in the search
                    columns = srch_obj.get("attributes", {}).get("columns", [])
                    if isinstance(columns, list):
                        for col in columns:
                            if isinstance(col, str) and not col.startswith("_") and col != "*":
                                if col not in mapping_fields:
                                    d_issues.append({
                                        "level": "error",
                                        "check": "missing-field",
                                        "message": (
                                            f"Search '{srch_obj['title']}' (id: {srch_id}) "
                                            f"references column '{col}' not found in index '{ip_title}'"
                                        ),
                                    })

            # Validate searchSourceJSON in search
            _validate_search_source(srch_obj, d_issues, "Search")

        # Check dashboard's own panelsJSON is parseable
        panels_json = dashboard["attributes"].get("panelsJSON")
        if panels_json and isinstance(panels_json, str):
            try:
                json.loads(panels_json)
            except json.JSONDecodeError as e:
                d_issues.append({"level": "error", "check": "invalid-json",
                                 "message": f"Dashboard panelsJSON is malformed: {e}"})

        # Check if dashboard has no panels at all
        if not refs and not panels_json:
            d_issues.append({"level": "warning", "check": "empty-dashboard",
                             "message": "Dashboard has no panels or references"})

        dashboard_results.append({
            "id": d_id,
            "title": d_title,
            "issues": d_issues,
            "status": "ok" if not d_issues else (
                "error" if any(i["level"] == "error" for i in d_issues) else "warning"
            ),
        })

    return {
        "dashboards": dashboard_results,
        "global_issues": issues_global,
        "summary": {
            "total_dashboards": len(dashboard_results),
            "ok": sum(1 for d in dashboard_results if d["status"] == "ok"),
            "warnings": sum(1 for d in dashboard_results if d["status"] == "warning"),
            "errors": sum(1 for d in dashboard_results if d["status"] == "error"),
            "global_issues": len(issues_global),
        },
    }


def _validate_search_source(obj, issues_list, label_prefix):
    """Validate the searchSourceJSON inside a saved object's kibanaSavedObjectMeta."""
    attrs = obj.get("attributes", {})
    meta = attrs.get("kibanaSavedObjectMeta", {})
    if not isinstance(meta, dict):
        return

    search_source_raw = meta.get("searchSourceJSON")
    if not search_source_raw:
        return

    if not isinstance(search_source_raw, str):
        return

    try:
        search_source = json.loads(search_source_raw)
    except json.JSONDecodeError as e:
        issues_list.append({
            "level": "error",
            "check": "invalid-query",
            "message": f"{label_prefix} '{obj.get('title', obj.get('id', '?'))}': searchSourceJSON is malformed JSON: {e}",
        })
        return

    # Check for obviously broken query structures
    query = search_source.get("query")
    if isinstance(query, dict):
        lang = query.get("language", "")
        query_str = query.get("query", "")
        # Detect common issues: mismatched braces in KQL/Lucene
        if isinstance(query_str, str) and query_str.strip():
            open_parens = query_str.count("(")
            close_parens = query_str.count(")")
            if open_parens != close_parens:
                issues_list.append({
                    "level": "warning",
                    "check": "invalid-query",
                    "message": f"{label_prefix} '{obj.get('title', obj.get('id', '?'))}': query has mismatched parentheses ({lang}): '{query_str}'",
                })

    # Check for filters referencing unknown fields (basic structural check)
    filters = search_source.get("filter", [])
    if isinstance(filters, list):
        for f in filters:
            if isinstance(f, dict) and f.get("meta", {}).get("disabled") is True:
                continue
            if isinstance(f, dict) and "query" in f:
                fq = f["query"]
                if isinstance(fq, dict):
                    # Check match_phrase or match with empty key
                    for match_type in ("match_phrase", "match"):
                        if match_type in fq:
                            match_val = fq[match_type]
                            if isinstance(match_val, dict) and not match_val:
                                issues_list.append({
                                    "level": "warning",
                                    "check": "invalid-query",
                                    "message": f"{label_prefix} '{obj.get('title', obj.get('id', '?'))}': filter has empty {match_type} clause",
                                })


def import_saved_objects(config, ndjson_content, target=None, obj_type=None, workspace=None):
    """Import saved objects from ndjson.

    When the target has a 'dashboards' endpoint, this uses the OpenSearch
    Dashboards `_import` saved-objects API — optionally scoped to a workspace
    via `/w/<id>/`. That is the only path that tags objects with a workspace so
    they show up inside it; writing straight to the `.kibana` index (the
    fallback below, used only for cluster-only targets) leaves them
    unassociated and therefore invisible in workspace-enabled OSD.

    Args:
        config: Configuration dictionary
        ndjson_content: NDJSON formatted string with saved objects
        target: Optional target name
        obj_type: Optional filter - only import objects of this type
        workspace: Optional OSD workspace id to import into
    """
    from .cli import (get_server, get_auth, get_verify_ssl, get_cluster_base_url,
                      get_dashboards_base_url, get_workspace, use_dashboards_api)

    server, _ = get_server(config, target)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    lines = ndjson_content.strip().split('\n')

    # Clean the payload: drop metadata lines and (optionally) type-mismatched objects.
    kept = []
    skipped = []
    for line in lines:
        if not line.strip():
            continue
        obj = json.loads(line)
        if '_index_pattern_map' in obj:
            continue
        if obj_type and obj.get('type') != obj_type:
            skipped.append({'id': obj.get('id', 'unknown'),
                            'reason': f"Type mismatch (expected {obj_type}, got {obj.get('type')})"})
            continue
        kept.append(obj)

    ws = get_workspace(server, workspace)

    if use_dashboards_api(server):
        # Preferred path: OSD saved-objects _import API (workspace-scoped when set).
        api_base = get_dashboards_base_url(server, workspace)
        url = f"{api_base}/api/saved_objects/_import?overwrite=true"
        payload = ('\n'.join(json.dumps(o) for o in kept) + '\n').encode('utf-8')
        files = {'file': ('export.ndjson', payload, 'application/ndjson')}
        resp = requests.post(url, headers={'osd-xsrf': 'true'}, files=files,
                             auth=auth, verify=verify_ssl)
        try:
            body = resp.json()
        except ValueError:
            body = {'raw': resp.text}
        return {
            'method': 'dashboards_import_api',
            'workspace': ws,
            'status_code': resp.status_code,
            'success': bool(body.get('success')) if isinstance(body, dict) else False,
            'successCount': body.get('successCount') if isinstance(body, dict) else None,
            'errors': body.get('errors') if isinstance(body, dict) else None,
            'skipped': skipped,
        }

    # Fallback: cluster-only target (no 'dashboards' endpoint) — write directly
    # to the .kibana cluster index. NOTE: this does not associate objects with
    # any workspace.
    if ws:
        print("Warning: --workspace is ignored without a 'dashboards' endpoint "
              "configured; objects are written to .kibana unscoped.")
    cluster_url = get_cluster_base_url(server)
    imported = []
    for obj in kept:
        doc = {obj['type']: obj['attributes'], 'type': obj['type']}
        if 'references' in obj:
            doc['references'] = obj['references']
        import_resp = requests.put(
            f"{cluster_url}/.kibana/_doc/{obj['type']}:{obj['id']}",
            headers={"Content-Type": "application/json"},
            json=doc,
            auth=auth,
            verify=verify_ssl
        )
        imported.append({
            'id': obj['id'],
            'type': obj['type'],
            'title': obj.get('attributes', {}).get('title', 'N/A'),
            'status': import_resp.status_code,
            'success': import_resp.status_code in [200, 201]
        })

    return {'method': '.kibana_direct', 'imported': imported, 'skipped': skipped}


# ---------------------------------------------------------------------------
# Jobs / running work inspection
# ---------------------------------------------------------------------------

# Internal-noise actions filtered out of `jobs list` by default.
_NOISY_TASK_ACTIONS_PREFIXES = (
    "cluster:monitor/",
    "indices:monitor/",
    "internal:",
)


def list_running_tasks(config, target=None, show_all=False, action_filter=None):
    """List currently running tasks via the _tasks API.

    Args:
        show_all: include monitoring/internal noise.
        action_filter: optional substring; only tasks whose action contains it are kept.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    resp = requests.get(
        f"{base_url}/_tasks?detailed=true",
        auth=auth,
        verify=verify_ssl,
    )
    if resp.status_code != 200:
        return {"error": f"Failed to fetch tasks: {resp.status_code} - {resp.text}"}

    data = resp.json()
    results = []
    for node_id, node_info in data.get("nodes", {}).items():
        node_name = node_info.get("name", node_id)
        for task_id, task in node_info.get("tasks", {}).items():
            action = task.get("action", "")
            if not show_all and any(action.startswith(p) for p in _NOISY_TASK_ACTIONS_PREFIXES):
                continue
            if action_filter and action_filter not in action:
                continue

            description = task.get("description", "") or ""
            if len(description) > 80:
                description = description[:77] + "..."

            results.append({
                "task_id": task_id,
                "node": node_name,
                "action": action,
                "running_time": format_duration(task.get("running_time_in_nanos"), unit="ns"),
                "running_time_ms": (task.get("running_time_in_nanos") or 0) // 1_000_000,
                "cancellable": task.get("cancellable", False),
                "parent_task": task.get("parent_task_id", "-"),
                "description": description,
            })

    # Show oldest (longest-running) first.
    results.sort(key=lambda r: r["running_time_ms"], reverse=True)
    return results


def list_pending_cluster_tasks(config, target=None):
    """List pending master-level cluster tasks (_cluster/pending_tasks)."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    resp = requests.get(
        f"{base_url}/_cluster/pending_tasks",
        auth=auth,
        verify=verify_ssl,
    )
    if resp.status_code != 200:
        return {"error": f"Failed to fetch pending tasks: {resp.status_code} - {resp.text}"}

    data = resp.json()
    results = []
    for t in data.get("tasks", []):
        source = t.get("source", "") or ""
        if len(source) > 90:
            source = source[:87] + "..."
        results.append({
            "insert_order": t.get("insert_order"),
            "priority": t.get("priority", "-"),
            "time_in_queue": t.get("time_in_queue", format_duration(t.get("time_in_queue_millis"))),
            "time_in_queue_ms": t.get("time_in_queue_millis", 0),
            "source": source,
        })

    results.sort(key=lambda r: r["time_in_queue_ms"], reverse=True)
    return results


def list_policy_jobs(config, target=None):
    """List in-flight ISM/ILM policy work: indices currently being acted on by lifecycle.

    Filters the per-index explain output down to rows whose step is in a non-terminal
    state (running / retrying / failed / starting / condition_not_met).
    """
    rows = get_policy_status(config, target=target)
    if isinstance(rows, dict) and "error" in rows:
        return rows

    active_statuses = {
        "running", "in_progress", "starting", "retrying", "failed", "condition_not_met"
    }
    return [r for r in rows if r["step_status"] in active_statuses]


def get_policy_status(config, target=None, index_filter=None, failed_only=False):
    """Per-index lifecycle execution status (current step, action, retries, errors).

    Works against OpenSearch ISM (_plugins/_ism/explain) and Elasticsearch ILM
    (_ilm/explain). Returns a normalized list of dicts.

    Args:
        index_filter: optional index name / pattern (e.g. "logs-*"). Defaults to '*'.
        failed_only: keep only rows whose step is failed or retrying.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    is_opensearch = _detect_distribution(base_url, auth, verify_ssl)
    target_pattern = index_filter or "*"

    now_ms = int(datetime.now().timestamp() * 1000)

    if is_opensearch:
        url = f"{base_url}/_plugins/_ism/explain/{target_pattern}"
        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch ISM explain: {resp.status_code} - {resp.text}"}
        data = resp.json()
    else:
        url = f"{base_url}/{target_pattern}/_ilm/explain"
        resp = requests.get(url, auth=auth, verify=verify_ssl)
        if resp.status_code != 200:
            return {"error": f"Failed to fetch ILM explain: {resp.status_code} - {resp.text}"}
        data = resp.json().get("indices", {})

    results = []
    for index_name, info in data.items():
        if not isinstance(info, dict):
            continue

        if is_opensearch:
            policy_id = (
                info.get("index.plugins.index_state_management.policy_id")
                or info.get("policy_id")
            )
            if not policy_id:
                # Index is not managed by ISM; skip.
                continue

            state = info.get("state") or {}
            action = info.get("action") or {}
            step = info.get("step") or {}
            retry_info = info.get("retry_info") or {}
            info_msg = info.get("info") or {}

            step_status = (step.get("step_status") or "").lower() or "unknown"
            failed_flag = bool(action.get("failed") or retry_info.get("failed"))
            if failed_flag and step_status not in ("failed", "retrying"):
                step_status = "failed"
            retries = action.get("consumed_retries") or retry_info.get("consumed_retries") or 0

            step_start = step.get("start_time")
            time_in_step = format_duration(now_ms - step_start) if step_start else "-"

            error = ""
            if isinstance(info_msg, dict):
                error = info_msg.get("cause") or info_msg.get("message") or ""
            elif isinstance(info_msg, str):
                error = info_msg
            if not error and failed_flag:
                error = "(see ISM history)"

            row = {
                "index": index_name,
                "policy": policy_id,
                "phase": state.get("name") or "-",
                "action": action.get("name") or "-",
                "step": step.get("name") or "-",
                "step_status": step_status,
                "retries": int(retries) if retries is not None else 0,
                "time_in_step": time_in_step,
                "error": (error or "").strip(),
            }
        else:
            if not info.get("managed"):
                continue
            phase = info.get("phase", "-")
            action_name = info.get("action", "-")
            step_name = info.get("step", "-")
            failed_step = info.get("failed_step")
            retries = info.get("failed_step_retry_count", 0) or 0

            if failed_step:
                step_status = "retrying" if info.get("is_auto_retryable_error") else "failed"
                step_name = f"{step_name} (failed: {failed_step})"
            elif step_name in ("complete", "completed"):
                step_status = "completed"
            else:
                step_status = "running"

            step_info = info.get("step_info") or {}
            if isinstance(step_info, dict):
                error = (
                    step_info.get("reason")
                    or step_info.get("message")
                    or step_info.get("type")
                    or ""
                )
            else:
                error = str(step_info)

            row = {
                "index": index_name,
                "policy": info.get("policy", "-"),
                "phase": phase,
                "action": action_name,
                "step": step_name,
                "step_status": step_status,
                "retries": int(retries),
                "time_in_step": format_duration(info.get("step_time_millis") and now_ms - info["step_time_millis"]),
                "error": (error or "").strip(),
            }

        if failed_only and row["step_status"] not in ("failed", "retrying"):
            continue

        results.append(row)

    # Sort: failures first, then by index name.
    sort_rank = {"failed": 0, "retrying": 1, "running": 2, "in_progress": 2,
                 "starting": 3, "condition_not_met": 4, "completed": 5}
    results.sort(key=lambda r: (sort_rank.get(r["step_status"], 9), r["index"]))
    return results


# ---------------------------------------------------------------------------
# Printers for the jobs / policy-status tables
# ---------------------------------------------------------------------------

def _print_columns(rows, columns):
    """Print rows as a simple aligned table.

    columns: list of (header, key, color_key_or_None) tuples.
    """
    if not rows:
        return

    headers = [c[0] for c in columns]
    widths = [len(h) for h in headers]
    for r in rows:
        for i, (_, key, _) in enumerate(columns):
            widths[i] = max(widths[i], len(str(r.get(key, "") or "-")))

    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_row)
    print("-" * len(header_row))

    for r in rows:
        cells = []
        for i, (_, key, color_key) in enumerate(columns):
            val = str(r.get(key, "") or "-")
            color = ""
            if color_key:
                color = STATUS_COLORS.get(str(r.get(color_key, "")), "")
            reset = STATUS_COLORS["reset"] if color else ""
            cells.append(f"{color}{val.ljust(widths[i])}{reset}")
        print("  ".join(cells))


def print_running_tasks(results):
    if not results:
        print("No running tasks")
        return
    _print_columns(results, [
        ("Task",        "task_id",      None),
        ("Node",        "node",         None),
        ("Action",      "action",       None),
        ("Running",     "running_time", None),
        ("Parent",      "parent_task",  None),
        ("Description", "description",  None),
    ])
    print(f"\nTotal: {len(results)} task(s)")


def print_pending_tasks(results):
    if not results:
        print("No pending cluster tasks")
        return
    _print_columns(results, [
        ("Order",    "insert_order",  None),
        ("Priority", "priority",      "priority"),
        ("Waiting",  "time_in_queue", None),
        ("Source",   "source",        None),
    ])
    print(f"\nTotal: {len(results)} pending task(s)")


# ---------------------------------------------------------------------------
# Policy inspection / mutation (ISM and ILM)
# ---------------------------------------------------------------------------

def get_policy(config, policy_name, target=None):
    """Fetch a single ISM (OpenSearch) or ILM (Elasticsearch) policy by name."""
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    is_opensearch = _detect_distribution(base_url, auth, verify_ssl)
    if is_opensearch:
        url = f"{base_url}/_plugins/_ism/policies/{policy_name}"
    else:
        url = f"{base_url}/_ilm/policy/{policy_name}"

    resp = requests.get(url, auth=auth, verify=verify_ssl)
    if resp.status_code == 404:
        return {"error": f"Policy '{policy_name}' not found"}
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    return resp.json()


def get_ism_settings(config, target=None):
    """Fetch all `plugins.index_state_management.*` cluster settings with their
    effective value and source (persistent / transient / default).

    Returns a list of dicts: {"key": ..., "value": ..., "source": ...}.
    OpenSearch only — ILM has a different (and limited) set of cluster knobs.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    is_opensearch = _detect_distribution(base_url, auth, verify_ssl)
    if not is_opensearch:
        return {"error": "ilm settings is OpenSearch ISM-only"}

    resp = requests.get(
        f"{base_url}/_cluster/settings?include_defaults=true&flat_settings=true",
        auth=auth, verify=verify_ssl,
    )
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    data = resp.json()

    PREFIX = "plugins.index_state_management."
    # Higher priority overrides lower: persistent > transient > defaults.
    merged = {}
    for source in ("defaults", "transient", "persistent"):
        block = data.get(source, {}) or {}
        for k, v in block.items():
            if k.startswith(PREFIX):
                merged[k] = {"key": k, "value": v, "source": source}
    return sorted(merged.values(), key=lambda r: r["key"])


def print_ism_settings(rows):
    if isinstance(rows, dict) and "error" in rows:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No plugins.index_state_management.* cluster settings found")
        return
    headers = ["Setting", "Value", "Source"]
    widths = [len(h) for h in headers]
    for r in rows:
        widths[0] = max(widths[0], len(r["key"]))
        widths[1] = max(widths[1], len(str(r["value"])))
        widths[2] = max(widths[2], len(r["source"]))
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        # Highlight non-default sources so overrides stand out.
        color = "\033[93m" if r["source"] != "defaults" else ""
        reset = "\033[0m" if color else ""
        print(color + fmt.format(r["key"], str(r["value"]), r["source"]) + reset)


def get_ism_schedules(config, target=None, index_filter=None):
    """Fetch baked-in `schedule.interval` from each managed_index doc in
    .opendistro-ism-config.

    These per-index schedules are set at managed_index creation (from the
    cluster `plugins.index_state_management.job_interval` at that moment) and
    are NOT updated when the cluster setting changes — that's the load-bearing
    fact when reasoning about tick frequency on an already-managed index.

    Returns a list of dicts:
        {"index": ..., "policy_id": ..., "interval": <int>, "unit": "Minutes",
         "start_time_ms": <epoch ms>, "policy_seq_no": ...}
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    is_opensearch = _detect_distribution(base_url, auth, verify_ssl)
    if not is_opensearch:
        return {"error": "ilm schedule is OpenSearch ISM-only"}

    body = {
        "size": 1000,
        "query": {"exists": {"field": "managed_index"}},
        "_source": [
            "managed_index.index",
            "managed_index.policy_id",
            "managed_index.policy_seq_no",
            "managed_index.schedule",
        ],
    }
    resp = requests.get(
        f"{base_url}/.opendistro-ism-config/_search",
        auth=auth, verify=verify_ssl,
        headers={"Content-Type": "application/json"},
        json=body,
    )
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text}"}

    rows = []
    for hit in resp.json().get("hits", {}).get("hits", []):
        mi = hit.get("_source", {}).get("managed_index") or {}
        idx = mi.get("index")
        if index_filter and not _glob_match(idx, index_filter):
            continue
        sched = mi.get("schedule", {}).get("interval", {}) or {}
        rows.append({
            "index": idx,
            "policy_id": mi.get("policy_id"),
            "policy_seq_no": mi.get("policy_seq_no"),
            "interval": sched.get("period"),
            "unit": sched.get("unit"),
            "start_time_ms": sched.get("start_time"),
        })
    rows.sort(key=lambda r: (r["interval"] or 0, r["index"] or ""))
    return rows


def _glob_match(name, pattern):
    if not pattern or pattern == "*":
        return True
    import fnmatch
    return fnmatch.fnmatchcase(name or "", pattern)


def print_ism_schedules(rows):
    if isinstance(rows, dict) and "error" in rows:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No managed indices found")
        return
    from collections import Counter
    dist = Counter((r["interval"], r["unit"]) for r in rows)

    headers = ["Index", "Policy", "Interval", "Unit", "Policy Seq"]
    widths = [len(h) for h in headers]
    for r in rows:
        widths[0] = max(widths[0], len(r["index"] or ""))
        widths[1] = max(widths[1], len(r["policy_id"] or ""))
        widths[2] = max(widths[2], len(str(r["interval"])))
        widths[3] = max(widths[3], len(r["unit"] or ""))
        widths[4] = max(widths[4], len(str(r["policy_seq_no"])))
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        print(fmt.format(
            r["index"] or "-",
            r["policy_id"] or "-",
            str(r["interval"]),
            r["unit"] or "-",
            str(r["policy_seq_no"]),
        ))
    print("\nInterval distribution:")
    for (period, unit), n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4} index(es) on {period} {unit}")


def get_policy_version_drift(config, target=None, index_filter=None, include_orphans=False):
    """Compare each managed index's policy version to the latest version of that policy.

    Returns a list of dicts:
        {
            "index": ".ds-...",
            "policy": "observability-retention",
            "index_seq_no": 1505267,
            "current_seq_no": 1512556,
            "drift": True / False,
            "enrolled": True / False,   # False if policy_id is set but no state exists
            "orphan": True / False,     # True if no policy_id setting at all
            "state": "hot" | "-" ...,
            "step_status": "...",
        }

    When include_orphans=True, also emits rows for indices that have no
    `policy_id` setting at all (the rollover-template race outcome: a new
    backing index came up without ISM stamping a policy). Orphans are
    restricted to non-system indices (skips `.opendistro*`, `.kibana*`,
    `.opensearch*`) so the output isn't polluted by internal indices.

    OpenSearch only — ILM doesn't expose a comparable seq_no.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    is_opensearch = _detect_distribution(base_url, auth, verify_ssl)
    if not is_opensearch:
        return {"error": "policy version drift is OpenSearch ISM-only (no equivalent in ILM)"}

    target_pattern = index_filter or "*"
    resp = requests.get(
        f"{base_url}/_plugins/_ism/explain/{target_pattern}",
        auth=auth, verify=verify_ssl,
    )
    if resp.status_code != 200:
        return {"error": f"Failed to fetch ISM explain: {resp.status_code} - {resp.text}"}
    data = resp.json()

    # Cache current policy seq_no per policy_id so we hit the policies API at most once each.
    policy_meta_cache = {}
    def _policy_seq(policy_name):
        if policy_name in policy_meta_cache:
            return policy_meta_cache[policy_name]
        pr = requests.get(
            f"{base_url}/_plugins/_ism/policies/{policy_name}",
            auth=auth, verify=verify_ssl,
        )
        if pr.status_code == 200:
            j = pr.json()
            policy_meta_cache[policy_name] = j.get("_seq_no")
        else:
            policy_meta_cache[policy_name] = None
        return policy_meta_cache[policy_name]

    SYSTEM_PREFIXES = (".opendistro", ".kibana", ".opensearch", ".plugins")

    rows = []
    for index_name, info in data.items():
        if not isinstance(info, dict):
            continue
        policy_id = (
            info.get("index.plugins.index_state_management.policy_id")
            or info.get("policy_id")
        )
        if not policy_id:
            if not include_orphans:
                continue
            if index_name.startswith(SYSTEM_PREFIXES):
                continue
            rows.append({
                "index": index_name,
                "policy": None,
                "index_seq_no": None,
                "current_seq_no": None,
                "drift": False,
                "enrolled": False,
                "orphan": True,
                "state": "-",
                "step_status": "-",
            })
            continue

        index_seq = info.get("policy_seq_no")
        current_seq = _policy_seq(policy_id)
        state = info.get("state") or {}
        step = info.get("step") or {}
        enrolled = index_seq is not None and bool(state)
        drift = (
            enrolled
            and current_seq is not None
            and index_seq != current_seq
        )

        rows.append({
            "index": index_name,
            "policy": policy_id,
            "index_seq_no": index_seq,
            "current_seq_no": current_seq,
            "drift": drift,
            "enrolled": enrolled,
            "orphan": False,
            "state": (state.get("name") if state else None) or "-",
            "step_status": (step.get("step_status") or "-") if step else "-",
        })

    # Stable sort: orphan first, then not-enrolled, then drifted, then in-sync.
    def _rank(r):
        if r.get("orphan"):
            return 0
        if not r["enrolled"]:
            return 1
        if r["drift"]:
            return 2
        return 3
    rows.sort(key=lambda r: (_rank(r), r["index"]))
    return rows


def print_policy_version_drift(rows):
    """Print policy version drift table."""
    if isinstance(rows, dict) and "error" in rows:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No managed indices found")
        return

    headers = ["Index", "Policy", "Index Seq", "Current Seq", "Enrolled", "Drift", "State", "Step Status"]
    widths = [len(h) for h in headers]
    for r in rows:
        widths[0] = max(widths[0], len(r["index"]))
        widths[1] = max(widths[1], len(str(r["policy"])))
        widths[2] = max(widths[2], len(str(r["index_seq_no"] if r["index_seq_no"] is not None else "-")))
        widths[3] = max(widths[3], len(str(r["current_seq_no"] if r["current_seq_no"] is not None else "-")))
        widths[6] = max(widths[6], len(r["state"] or "-"))
        widths[7] = max(widths[7], len(r["step_status"] or "-"))

    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_row)
    print("-" * len(header_row))

    for r in rows:
        if r.get("orphan"):
            color = "\033[95m"     # magenta — no policy_id at all
        elif not r["enrolled"]:
            color = "\033[91m"     # red — not enrolled
        elif r["drift"]:
            color = "\033[93m"     # yellow — stale version
        else:
            color = "\033[92m"     # green — in sync
        reset = "\033[0m"
        line = [
            r["index"].ljust(widths[0]),
            (r["policy"] or "-").ljust(widths[1]),
            str(r["index_seq_no"] if r["index_seq_no"] is not None else "-").ljust(widths[2]),
            str(r["current_seq_no"] if r["current_seq_no"] is not None else "-").ljust(widths[3]),
            ("yes" if r["enrolled"] else "no").ljust(widths[4]),
            ("yes" if r["drift"] else "no").ljust(widths[5]),
            (r["state"] or "-").ljust(widths[6]),
            (r["step_status"] or "-").ljust(widths[7]),
        ]
        print(color + "  ".join(line) + reset)

    n_orphan = sum(1 for r in rows if r.get("orphan"))
    n_drift = sum(1 for r in rows if r["drift"])
    n_unenrolled = sum(1 for r in rows if not r["enrolled"] and not r.get("orphan"))
    n_ok = len(rows) - n_drift - n_unenrolled - n_orphan
    parts = [
        f"\033[92m{n_ok} in sync\033[0m",
        f"\033[93m{n_drift} drifted\033[0m",
        f"\033[91m{n_unenrolled} not enrolled\033[0m",
    ]
    if n_orphan:
        parts.append(f"\033[95m{n_orphan} orphan\033[0m")
    print(f"\nTotal: {len(rows)} index(es) — " + ", ".join(parts))


def list_index_templates(config, target=None, name_filter=None):
    """List composable index templates: GET _index_template[/pattern].

    Surfaces whether each template carries an ISM policy_id (either inline in
    template.settings or via its composed_of component templates).
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    suffix = f"/{name_filter}" if name_filter else ""
    resp = requests.get(f"{base_url}/_index_template{suffix}", auth=auth, verify=verify_ssl)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    data = resp.json()

    # Build a side cache of component-template policy_ids so we can show inherited ones.
    ct_cache = {}
    ct_resp = requests.get(f"{base_url}/_component_template", auth=auth, verify=verify_ssl)
    if ct_resp.status_code == 200:
        for entry in ct_resp.json().get("component_templates", []):
            ct = entry.get("component_template", {})
            settings = ct.get("template", {}).get("settings", {}) or {}
            pid = None
            try:
                pid = (
                    settings.get("index", {})
                    .get("plugins", {})
                    .get("index_state_management", {})
                    .get("policy_id")
                )
            except AttributeError:
                pid = None
            if not pid:
                pid = settings.get("index.plugins.index_state_management.policy_id")
            ct_cache[entry.get("name")] = pid

    rows = []
    for entry in data.get("index_templates", []):
        it = entry.get("index_template", {})
        settings = it.get("template", {}).get("settings", {}) or {}
        composed_of = it.get("composed_of", []) or []
        # Inline policy id
        inline_pid = None
        try:
            inline_pid = (
                settings.get("index", {})
                .get("plugins", {})
                .get("index_state_management", {})
                .get("policy_id")
            )
        except AttributeError:
            inline_pid = None
        if not inline_pid:
            inline_pid = settings.get("index.plugins.index_state_management.policy_id")
        # Inherited from composed_of (last-wins per OpenSearch merge semantics)
        inherited_pid = None
        inherited_from = None
        for cname in composed_of:
            cpid = ct_cache.get(cname)
            if cpid:
                inherited_pid = cpid
                inherited_from = cname
        effective = inline_pid or inherited_pid
        rows.append({
            "name": entry.get("name", "-"),
            "index_patterns": ",".join(it.get("index_patterns", []) or []),
            "policy_id": effective or "-",
            "source": "inline" if inline_pid else (f"via {inherited_from}" if inherited_pid else "-"),
            "composed_of": ",".join(composed_of) if composed_of else "-",
        })
    rows.sort(key=lambda r: r["name"])
    return rows


def print_index_templates(rows):
    if isinstance(rows, dict) and "error" in rows:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No index templates found")
        return
    _print_columns(rows, [
        ("Name",         "name",           None),
        ("Patterns",     "index_patterns", None),
        ("Policy ID",    "policy_id",      None),
        ("Source",       "source",         None),
        ("Composed Of",  "composed_of",    None),
    ])
    print(f"\nTotal: {len(rows)} index template(s)")


def set_index_template_policy(config, target=None, template_name=None, policy_id=None):
    """PUT _index_template/<name> with index.plugins.index_state_management.policy_id
    merged into template.settings. Preserves the rest of the template.

    If policy_id == "none", removes the setting.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    if not template_name:
        return {"error": "template_name is required"}
    if not policy_id:
        return {"error": "policy_id is required (use 'none' to remove)"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    get_resp = requests.get(
        f"{base_url}/_index_template/{template_name}", auth=auth, verify=verify_ssl,
    )
    if get_resp.status_code == 404:
        return {"error": f"Index template '{template_name}' not found"}
    if get_resp.status_code != 200:
        return {"error": f"GET failed: HTTP {get_resp.status_code} - {get_resp.text}"}
    payload = get_resp.json()
    entries = payload.get("index_templates", [])
    if not entries:
        return {"error": f"Index template '{template_name}' returned empty"}
    it = entries[0].get("index_template", {})
    template = it.get("template", {}) or {}
    settings = template.get("settings") or {}

    if not isinstance(settings.get("index"), dict):
        settings["index"] = {}
    index_settings = settings["index"]
    plugins_block = index_settings.setdefault("plugins", {})
    ism_block = plugins_block.setdefault("index_state_management", {})
    before = ism_block.get("policy_id")

    if policy_id.lower() == "none":
        ism_block.pop("policy_id", None)
        if not ism_block:
            plugins_block.pop("index_state_management", None)
        if not plugins_block:
            index_settings.pop("plugins", None)
        after = None
    else:
        ism_block["policy_id"] = policy_id
        after = policy_id

    # Strip any stale dotted-form copy.
    settings.pop("index.plugins.index_state_management.policy_id", None)

    template["settings"] = settings
    it["template"] = template

    # Index template PUT body: pass through everything except readonly fields.
    put_body = {k: v for k, v in it.items() if k not in ("version",)}
    if "version" in it:
        put_body["version"] = it["version"]

    put_resp = requests.put(
        f"{base_url}/_index_template/{template_name}",
        headers={"Content-Type": "application/json"},
        data=json.dumps(put_body),
        auth=auth,
        verify=verify_ssl,
    )
    try:
        put_payload = put_resp.json()
    except ValueError:
        put_payload = {"raw": put_resp.text}

    return {
        "template": template_name,
        "before": before,
        "after": after,
        "status": put_resp.status_code,
        "ok": put_resp.status_code in (200, 201),
        "response": put_payload,
    }


def print_set_index_template_result(result):
    if isinstance(result, dict) and "error" in result and "status" not in result:
        print(json.dumps(result, indent=2))
        return
    icon = "\033[92m✓\033[0m" if result.get("ok") else "\033[91m✗\033[0m"
    print(f"  {icon} index-template={result['template']}  HTTP {result['status']}")
    print(f"      policy_id: {result['before'] or '(unset)'} → {result['after'] or '(unset)'}")
    if not result.get("ok"):
        print(f"      response: {json.dumps(result.get('response'), indent=2)}")


def list_component_templates(config, target=None, name_filter=None):
    """List component templates: GET _component_template[/pattern].

    Returns a list of dicts with name and whether they carry an ISM policy_id setting.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    suffix = f"/{name_filter}" if name_filter else ""
    resp = requests.get(f"{base_url}/_component_template{suffix}", auth=auth, verify=verify_ssl)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    data = resp.json()
    rows = []
    for entry in data.get("component_templates", []):
        ct = entry.get("component_template", {})
        settings = ct.get("template", {}).get("settings", {}) or {}
        # ISM stamps the policy id at index.plugins.index_state_management.policy_id —
        # accept either dotted or nested shape since OpenSearch normalises both.
        flat = json.dumps(settings)
        policy_id = None
        try:
            policy_id = (
                settings.get("index", {})
                .get("plugins", {})
                .get("index_state_management", {})
                .get("policy_id")
            )
        except AttributeError:
            policy_id = None
        if not policy_id and "policy_id" in flat:
            # Could be the dotted form `index.plugins.index_state_management.policy_id`
            policy_id = settings.get("index.plugins.index_state_management.policy_id")
        rows.append({
            "name": entry.get("name", "-"),
            "policy_id": policy_id or "-",
            "version": ct.get("version", "-"),
        })
    rows.sort(key=lambda r: r["name"])
    return rows


def print_component_templates(rows):
    if isinstance(rows, dict) and "error" in rows:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No component templates found")
        return
    _print_columns(rows, [
        ("Name",      "name",      None),
        ("Policy ID", "policy_id", None),
        ("Version",   "version",   None),
    ])
    print(f"\nTotal: {len(rows)} component template(s)")


def set_component_template_policy(config, target=None, template_name=None, policy_id=None):
    """PUT _component_template/<name> with index.plugins.index_state_management.policy_id merged
    into template.settings. Preserves the rest of the template (mappings, aliases, _meta, etc).

    If policy_id == "none" the setting is REMOVED.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    if not template_name:
        return {"error": "template_name is required"}
    if not policy_id:
        return {"error": "policy_id is required (use 'none' to remove)"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    get_resp = requests.get(
        f"{base_url}/_component_template/{template_name}", auth=auth, verify=verify_ssl,
    )
    if get_resp.status_code == 404:
        return {"error": f"Component template '{template_name}' not found"}
    if get_resp.status_code != 200:
        return {"error": f"GET failed: HTTP {get_resp.status_code} - {get_resp.text}"}
    payload = get_resp.json()
    entries = payload.get("component_templates", [])
    if not entries:
        return {"error": f"Component template '{template_name}' returned empty"}
    ct = entries[0].get("component_template", {})
    template = ct.get("template", {}) or {}
    settings = template.get("settings") or {}

    # Normalise to nested form so we have a single place to set the value.
    index_settings = settings.setdefault("index", {}) if isinstance(settings.get("index"), dict) else None
    if index_settings is None:
        # If 'index' was missing or not a dict, replace it.
        settings["index"] = {}
        index_settings = settings["index"]

    plugins_block = index_settings.setdefault("plugins", {})
    ism_block = plugins_block.setdefault("index_state_management", {})

    before = ism_block.get("policy_id")

    if policy_id.lower() == "none":
        ism_block.pop("policy_id", None)
        # Clean up empty parents we may have just created.
        if not ism_block:
            plugins_block.pop("index_state_management", None)
        if not plugins_block:
            index_settings.pop("plugins", None)
        after = None
    else:
        ism_block["policy_id"] = policy_id
        after = policy_id

    # Also strip any stale dotted-form copy that may shadow our nested write.
    settings.pop("index.plugins.index_state_management.policy_id", None)

    template["settings"] = settings
    ct["template"] = template
    # Rebuild PUT body — OpenSearch's _component_template PUT takes the inner template object
    # plus optional _meta and version at the top level.
    put_body = {
        "template": template,
    }
    if "_meta" in ct:
        put_body["_meta"] = ct["_meta"]
    if "version" in ct:
        put_body["version"] = ct["version"]
    if "allow_auto_create" in ct:
        put_body["allow_auto_create"] = ct["allow_auto_create"]

    put_resp = requests.put(
        f"{base_url}/_component_template/{template_name}",
        headers={"Content-Type": "application/json"},
        data=json.dumps(put_body),
        auth=auth,
        verify=verify_ssl,
    )
    try:
        put_payload = put_resp.json()
    except ValueError:
        put_payload = {"raw": put_resp.text}

    return {
        "template": template_name,
        "before": before,
        "after": after,
        "status": put_resp.status_code,
        "ok": put_resp.status_code in (200, 201),
        "response": put_payload,
    }


def print_set_component_template_result(result):
    if isinstance(result, dict) and "error" in result and "status" not in result:
        print(json.dumps(result, indent=2))
        return
    icon = "\033[92m✓\033[0m" if result.get("ok") else "\033[91m✗\033[0m"
    print(f"  {icon} component-template={result['template']}  HTTP {result['status']}")
    print(f"      policy_id: {result['before'] or '(unset)'} → {result['after'] or '(unset)'}")
    if not result.get("ok"):
        print(f"      response: {json.dumps(result.get('response'), indent=2)}")


def set_ism_rollover(config, target=None, policy_name=None, state_name="hot",
                     min_index_age=None, min_size=None, min_doc_count=None,
                     min_primary_shard_size=None):
    """Edit the rollover action in an OpenSearch ISM policy state (default 'hot').

    Each condition arg is one of:
      - a string/int value to set/replace (e.g. "30d", "50gb", 150000000)
      - the sentinel string "none" to REMOVE the condition
      - None to leave the existing value untouched (additive merge)

    Other fields in the rollover action (e.g. `copy_alias`) and the rest of the
    policy are preserved. Uses optimistic concurrency control via if_seq_no /
    if_primary_term, so concurrent edits to the same policy fail cleanly with
    HTTP 409.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    if not policy_name:
        return {"error": "policy_name is required"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    # Fetch current policy with seq_no / primary_term for CAS update.
    get_resp = requests.get(
        f"{base_url}/_plugins/_ism/policies/{policy_name}",
        auth=auth, verify=verify_ssl,
    )
    if get_resp.status_code == 404:
        return {"error": f"Policy '{policy_name}' not found"}
    if get_resp.status_code != 200:
        return {"error": f"GET policy failed: HTTP {get_resp.status_code} - {get_resp.text}"}

    doc = get_resp.json()
    seq_no = doc.get("_seq_no")
    primary_term = doc.get("_primary_term")
    policy = doc.get("policy")
    if not policy or not isinstance(policy, dict):
        return {"error": "policy document missing 'policy' field"}

    states = policy.get("states") or []
    target_state = next((s for s in states if s.get("name") == state_name), None)
    if target_state is None:
        return {"error": f"state '{state_name}' not found in policy '{policy_name}'"}

    # Find the action block containing a 'rollover' key.
    rollover_action = None
    for action in target_state.get("actions", []):
        if isinstance(action, dict) and "rollover" in action:
            rollover_action = action
            break

    if rollover_action is None:
        return {
            "error": (
                f"state '{state_name}' has no rollover action; "
                f"edit the policy manually to add one first"
            )
        }

    rollover = rollover_action.get("rollover") or {}
    if not isinstance(rollover, dict):
        return {"error": "existing rollover field is not an object"}

    before = dict(rollover)

    # Apply changes. "none" sentinel removes; anything else sets.
    def _apply(key, value):
        if value is None:
            return
        if isinstance(value, str) and value.lower() == "none":
            rollover.pop(key, None)
        else:
            rollover[key] = value

    _apply("min_index_age", min_index_age)
    _apply("min_size", min_size)
    _apply("min_doc_count", int(min_doc_count) if min_doc_count not in (None, "none") else min_doc_count)
    _apply("min_primary_shard_size", min_primary_shard_size)

    rollover_action["rollover"] = rollover
    after = dict(rollover)

    # PUT the policy back. ISM requires {"policy": {...}} wrapper.
    put_url = (
        f"{base_url}/_plugins/_ism/policies/{policy_name}"
        f"?if_seq_no={seq_no}&if_primary_term={primary_term}"
    )
    put_resp = requests.put(
        put_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"policy": policy}),
        auth=auth,
        verify=verify_ssl,
    )

    try:
        put_payload = put_resp.json()
    except ValueError:
        put_payload = {"raw": put_resp.text}

    return {
        "policy": policy_name,
        "state": state_name,
        "before": before,
        "after": after,
        "status": put_resp.status_code,
        "ok": put_resp.status_code in (200, 201),
        "old_seq_no": seq_no,
        "new_seq_no": put_payload.get("_seq_no") if isinstance(put_payload, dict) else None,
        "response": put_payload,
    }


def print_set_rollover_result(result):
    """Pretty-print the result of set_ism_rollover."""
    if isinstance(result, dict) and "error" in result and "status" not in result:
        print(json.dumps(result, indent=2))
        return
    icon = "\033[92m✓\033[0m" if result.get("ok") else "\033[91m✗\033[0m"
    print(f"  {icon} policy={result['policy']} state={result['state']} "
          f"HTTP {result['status']}  _seq_no {result['old_seq_no']} → {result.get('new_seq_no')}")
    print(f"      before: {json.dumps(result['before'])}")
    print(f"      after:  {json.dumps(result['after'])}")
    if not result.get("ok"):
        print(f"      response: {json.dumps(result.get('response'), indent=2)}")


def set_ism_transition(config, target=None, policy_name=None,
                       from_state=None, to_state=None,
                       conditions=None, position="first"):
    """Upsert a transition from `from_state` to `to_state` in an OpenSearch ISM policy.

    `conditions` is a dict like {"min_size": "50gb"} or
    {"min_rollover_age": "30d", "min_size": "50gb"}. Upsert is keyed by
    (to_state, frozenset(conditions.keys())): an existing transition whose
    conditions' key set matches exactly is updated in place; otherwise a new
    transition is inserted at `position` ("first" or "last") in the
    from_state's transitions list.

    Pass "none" as a condition VALUE to drop that key. If the resulting
    transition ends up with zero conditions, the transition itself is removed.

    Rest of the policy is preserved. Uses optimistic concurrency control via
    if_seq_no / if_primary_term, so concurrent edits to the same policy fail
    cleanly with HTTP 409.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    if not policy_name:
        return {"error": "policy_name is required"}
    if not from_state or not to_state:
        return {"error": "from_state and to_state are required"}
    if not conditions or not isinstance(conditions, dict):
        return {"error": "at least one condition is required"}
    if position not in ("first", "last"):
        return {"error": "position must be 'first' or 'last'"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    get_resp = requests.get(
        f"{base_url}/_plugins/_ism/policies/{policy_name}",
        auth=auth, verify=verify_ssl,
    )
    if get_resp.status_code == 404:
        return {"error": f"Policy '{policy_name}' not found"}
    if get_resp.status_code != 200:
        return {"error": f"GET policy failed: HTTP {get_resp.status_code} - {get_resp.text}"}

    doc = get_resp.json()
    seq_no = doc.get("_seq_no")
    primary_term = doc.get("_primary_term")
    policy = doc.get("policy")
    if not policy or not isinstance(policy, dict):
        return {"error": "policy document missing 'policy' field"}

    states = policy.get("states") or []
    src_state = next((s for s in states if s.get("name") == from_state), None)
    if src_state is None:
        return {"error": f"state '{from_state}' not found in policy '{policy_name}'"}

    transitions = src_state.setdefault("transitions", [])

    # Match existing transition by (to_state, exact set of condition keys).
    requested_keys = frozenset(conditions.keys())
    match_idx = None
    for i, t in enumerate(transitions):
        if not isinstance(t, dict) or t.get("state_name") != to_state:
            continue
        existing_keys = frozenset((t.get("conditions") or {}).keys())
        if existing_keys == requested_keys:
            match_idx = i
            break

    before_transitions = json.loads(json.dumps(transitions))
    action = None

    if match_idx is not None:
        existing = transitions[match_idx]
        existing_conds = dict(existing.get("conditions") or {})
        for k, v in conditions.items():
            if isinstance(v, str) and v.lower() == "none":
                existing_conds.pop(k, None)
            else:
                existing_conds[k] = v
        if not existing_conds:
            transitions.pop(match_idx)
            action = "removed"
        else:
            existing["conditions"] = existing_conds
            action = "updated"
    else:
        new_conds = {
            k: v for k, v in conditions.items()
            if not (isinstance(v, str) and v.lower() == "none")
        }
        if not new_conds:
            return {"error": "all conditions were 'none' and no matching transition exists to remove"}
        new_transition = {"state_name": to_state, "conditions": new_conds}
        if position == "first":
            transitions.insert(0, new_transition)
        else:
            transitions.append(new_transition)
        action = "inserted"

    put_url = (
        f"{base_url}/_plugins/_ism/policies/{policy_name}"
        f"?if_seq_no={seq_no}&if_primary_term={primary_term}"
    )
    put_resp = requests.put(
        put_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"policy": policy}),
        auth=auth,
        verify=verify_ssl,
    )

    try:
        put_payload = put_resp.json()
    except ValueError:
        put_payload = {"raw": put_resp.text}

    return {
        "policy": policy_name,
        "from_state": from_state,
        "to_state": to_state,
        "action": action,
        "before_transitions": before_transitions,
        "after_transitions": transitions,
        "status": put_resp.status_code,
        "ok": put_resp.status_code in (200, 201),
        "old_seq_no": seq_no,
        "new_seq_no": put_payload.get("_seq_no") if isinstance(put_payload, dict) else None,
        "response": put_payload,
    }


def print_set_transition_result(result):
    """Pretty-print the result of set_ism_transition."""
    if isinstance(result, dict) and "error" in result and "status" not in result:
        print(json.dumps(result, indent=2))
        return
    icon = "\033[92m✓\033[0m" if result.get("ok") else "\033[91m✗\033[0m"
    print(f"  {icon} policy={result['policy']} {result['from_state']} → {result['to_state']} "
          f"[{result['action']}] HTTP {result['status']}  "
          f"_seq_no {result['old_seq_no']} → {result.get('new_seq_no')}")
    print(f"      before: {json.dumps(result['before_transitions'])}")
    print(f"      after:  {json.dumps(result['after_transitions'])}")
    if not result.get("ok"):
        print(f"      response: {json.dumps(result.get('response'), indent=2)}")


def edit_ism_template(config, target=None, policy_name=None,
                      replace_patterns=None, add_patterns=None,
                      remove_patterns=None, entry_index=0, priority=None):
    """Edit the `ism_template` array of an OpenSearch ISM policy.

    Operations are applied in this order on the same in-memory policy doc:
      1. replace_patterns: list of (old, new) — for each pair, every
         occurrence of `old` in any entry's index_patterns is replaced with
         `new`. Idempotent: pairs whose `old` is not found are silently no-op.
      2. remove_patterns: list of patterns — removed from every entry's
         index_patterns. Entries left with empty index_patterns are dropped.
      3. add_patterns: list of patterns — appended to the entry at
         `entry_index` (post-remove state). Skipped if already present there.
      4. priority: if not None, set on the entry at `entry_index`.

    `last_updated_time` is bumped on every entry that actually changed.
    Rest of the policy is preserved. CAS via if_seq_no / if_primary_term.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url
    import time

    if not policy_name:
        return {"error": "policy_name is required"}
    replace_patterns = list(replace_patterns or [])
    add_patterns = list(add_patterns or [])
    remove_patterns = list(remove_patterns or [])
    if not (replace_patterns or add_patterns or remove_patterns or priority is not None):
        return {"error": "at least one of replace/add/remove/priority is required"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    get_resp = requests.get(
        f"{base_url}/_plugins/_ism/policies/{policy_name}",
        auth=auth, verify=verify_ssl,
    )
    if get_resp.status_code == 404:
        return {"error": f"Policy '{policy_name}' not found"}
    if get_resp.status_code != 200:
        return {"error": f"GET policy failed: HTTP {get_resp.status_code} - {get_resp.text}"}

    doc = get_resp.json()
    seq_no = doc.get("_seq_no")
    primary_term = doc.get("_primary_term")
    policy = doc.get("policy")
    if not policy or not isinstance(policy, dict):
        return {"error": "policy document missing 'policy' field"}

    entries = policy.get("ism_template")
    if entries is None:
        entries = []
        policy["ism_template"] = entries
    if not isinstance(entries, list):
        return {"error": "ism_template is not a list"}

    before = json.loads(json.dumps(entries))
    now_ms = int(time.time() * 1000)
    changed_entries = set()

    # 1. replace
    for old, new in replace_patterns:
        for i, entry in enumerate(entries):
            pats = entry.get("index_patterns") or []
            new_pats = [new if p == old else p for p in pats]
            if new_pats != pats:
                # dedupe while preserving order
                seen = set()
                deduped = []
                for p in new_pats:
                    if p not in seen:
                        seen.add(p)
                        deduped.append(p)
                entry["index_patterns"] = deduped
                changed_entries.add(i)

    # 2. remove
    if remove_patterns:
        remove_set = set(remove_patterns)
        for i, entry in enumerate(entries):
            pats = entry.get("index_patterns") or []
            new_pats = [p for p in pats if p not in remove_set]
            if new_pats != pats:
                entry["index_patterns"] = new_pats
                changed_entries.add(i)
        # drop entries with empty index_patterns (track which survive for entry_index remap)
        surviving = []
        dropped_before_index = 0
        for i, entry in enumerate(entries):
            if not entry.get("index_patterns"):
                if i < entry_index:
                    dropped_before_index += 1
                continue
            surviving.append(entry)
        entries[:] = surviving
        # remap entry_index against post-remove array
        entry_index = max(0, entry_index - dropped_before_index)
        # changed_entries indices referred to pre-remove positions; rebuild
        # by checking what differs from `before` now (we'll just stamp time
        # on indices that exist now AND differ).
        changed_entries = {i for i, e in enumerate(entries) if i >= len(before) or e != before[i]}

    # 3. add
    if add_patterns:
        if not entries:
            entries.append({
                "index_patterns": [],
                "priority": 100,
                "last_updated_time": now_ms,
            })
            entry_index = 0
        if entry_index < 0 or entry_index >= len(entries):
            return {"error": f"entry_index {entry_index} out of range (have {len(entries)} entries)"}
        target_entry = entries[entry_index]
        pats = list(target_entry.get("index_patterns") or [])
        added = False
        for p in add_patterns:
            if p not in pats:
                pats.append(p)
                added = True
        if added:
            target_entry["index_patterns"] = pats
            changed_entries.add(entry_index)

    # 4. priority
    if priority is not None:
        if entry_index < 0 or entry_index >= len(entries):
            return {"error": f"entry_index {entry_index} out of range (have {len(entries)} entries)"}
        if entries[entry_index].get("priority") != priority:
            entries[entry_index]["priority"] = priority
            changed_entries.add(entry_index)

    for i in changed_entries:
        if 0 <= i < len(entries):
            entries[i]["last_updated_time"] = now_ms

    after = json.loads(json.dumps(entries))
    if before == after:
        return {
            "policy": policy_name,
            "before_ism_template": before,
            "after_ism_template": after,
            "status": 200,
            "ok": True,
            "old_seq_no": seq_no,
            "new_seq_no": seq_no,
            "no_op": True,
            "response": {"message": "no changes"},
        }

    put_url = (
        f"{base_url}/_plugins/_ism/policies/{policy_name}"
        f"?if_seq_no={seq_no}&if_primary_term={primary_term}"
    )
    put_resp = requests.put(
        put_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"policy": policy}),
        auth=auth,
        verify=verify_ssl,
    )

    try:
        put_payload = put_resp.json()
    except ValueError:
        put_payload = {"raw": put_resp.text}

    return {
        "policy": policy_name,
        "before_ism_template": before,
        "after_ism_template": after,
        "status": put_resp.status_code,
        "ok": put_resp.status_code in (200, 201),
        "old_seq_no": seq_no,
        "new_seq_no": put_payload.get("_seq_no") if isinstance(put_payload, dict) else None,
        "no_op": False,
        "response": put_payload,
    }


def print_edit_ism_template_result(result):
    """Pretty-print the result of edit_ism_template."""
    if isinstance(result, dict) and "error" in result and "status" not in result:
        print(json.dumps(result, indent=2))
        return
    icon = "\033[92m✓\033[0m" if result.get("ok") else "\033[91m✗\033[0m"
    tag = " [no-op]" if result.get("no_op") else ""
    print(f"  {icon} policy={result['policy']}{tag} HTTP {result['status']}  "
          f"_seq_no {result['old_seq_no']} → {result.get('new_seq_no')}")
    print(f"      before: {json.dumps(result['before_ism_template'])}")
    print(f"      after:  {json.dumps(result['after_ism_template'])}")
    if not result.get("ok"):
        print(f"      response: {json.dumps(result.get('response'), indent=2)}")


def change_policy_for_indices(config, target=None, index_patterns=None, policy_id=None,
                              state=None, include_states=None):
    """Call POST _plugins/_ism/change_policy/<idx> for the given pattern(s).

    Args:
        index_patterns: list of concrete index names or wildcard patterns.
        policy_id: ISM policy id to apply.
        state: optional ISM state to start in (otherwise the policy's default_state).
        include_states: optional list of current-state names; only indices currently in
            one of these states will be affected (ISM 'include' filter). Pass None to
            apply to all states.

    Returns a list of result dicts.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    if not policy_id:
        return {"error": "policy_id is required"}
    if not index_patterns:
        return {"error": "at least one index name or pattern is required"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    body = {"policy_id": policy_id}
    if state:
        body["state"] = state
    if include_states:
        body["include"] = [{"state": s} for s in include_states]

    # add endpoint takes only policy_id (no state / include)
    add_body = {"policy_id": policy_id}

    results = []
    for pattern in index_patterns:
        resp = requests.post(
            f"{base_url}/_plugins/_ism/change_policy/{pattern}",
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
            auth=auth,
            verify=verify_ssl,
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}

        # Fall back to _plugins/_ism/add for any indices reported as "not being managed".
        # change_policy only operates on indices that already have an ISM managed-index doc;
        # truly un-managed indices (no policy_id setting) need the add endpoint.
        if isinstance(payload, dict):
            unmanaged = [
                f.get("index_name") for f in payload.get("failed_indices", [])
                if isinstance(f, dict)
                and "not being managed" in (f.get("reason") or "").lower()
            ]
        else:
            unmanaged = []

        add_failures = []
        added_count = 0
        for idx_name in unmanaged:
            if not idx_name:
                continue
            add_resp = requests.post(
                f"{base_url}/_plugins/_ism/add/{idx_name}",
                headers={"Content-Type": "application/json"},
                data=json.dumps(add_body),
                auth=auth,
                verify=verify_ssl,
            )
            try:
                add_payload = add_resp.json()
            except ValueError:
                add_payload = {"raw": add_resp.text}
            if isinstance(add_payload, dict):
                added_count += int(add_payload.get("updated_indices") or 0)
                for f in add_payload.get("failed_indices", []) or []:
                    add_failures.append(f)

        if unmanaged:
            # Stitch the fallback outcome into the response so the printer reflects it.
            if isinstance(payload, dict):
                payload.setdefault("_fallback_add", {})
                payload["_fallback_add"]["attempted"] = len(unmanaged)
                payload["_fallback_add"]["added"] = added_count
                payload["_fallback_add"]["failed"] = add_failures
                # Remove the fallen-back failures from the primary failed list so they don't
                # double-count, and append any genuine add-failures.
                primary_failed = [
                    f for f in payload.get("failed_indices", []) or []
                    if isinstance(f, dict)
                    and "not being managed" not in (f.get("reason") or "").lower()
                ]
                primary_failed.extend(add_failures)
                payload["failed_indices"] = primary_failed
                # Bump updated count to reflect successful adds.
                payload["updated_indices"] = (
                    int(payload.get("updated_indices") or 0) + added_count
                )

        results.append({
            "pattern": pattern,
            "status": resp.status_code,
            "ok": resp.status_code in (200, 201),
            "response": payload,
        })
    return results


def retry_ism_for_indices(config, target=None, index_patterns=None, state=None):
    """POST _plugins/_ism/retry/<idx> for each pattern.

    state: if provided, ISM will retry from this state.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    if not index_patterns:
        return {"error": "at least one index name or pattern is required"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    body = {}
    if state:
        body["state"] = state

    results = []
    for pattern in index_patterns:
        kwargs = dict(auth=auth, verify=verify_ssl,
                      headers={"Content-Type": "application/json"})
        if body:
            kwargs["data"] = json.dumps(body)
        resp = requests.post(f"{base_url}/_plugins/_ism/retry/{pattern}", **kwargs)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        results.append({
            "pattern": pattern,
            "status": resp.status_code,
            "ok": resp.status_code in (200, 201),
            "response": payload,
        })
    return results


def rollover_index(config, target=None, name=None):
    """Manually roll over a data stream or write alias.

    name: data stream name (e.g. 'p2-staging-logs-app-apricot') or write alias.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    if not name:
        return {"error": "data-stream or alias name is required"}

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    resp = requests.post(f"{base_url}/{name}/_rollover", auth=auth, verify=verify_ssl)
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    return {
        "name": name,
        "status": resp.status_code,
        "ok": resp.status_code in (200, 201),
        "response": payload,
    }


def list_data_streams(config, target=None, name_filter=None):
    """List data streams: GET _data_stream[/pattern].

    Returns a list of dicts with name, status, generation, write-index, backing-index count, template.
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_cluster_base_url

    server, _ = get_server(config, target)
    base_url = get_cluster_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    suffix = f"/{name_filter}" if name_filter else ""
    resp = requests.get(f"{base_url}/_data_stream{suffix}", auth=auth, verify=verify_ssl)
    if resp.status_code != 200:
        return {"error": f"Failed to fetch data streams: {resp.status_code} - {resp.text}"}
    data = resp.json()

    rows = []
    for ds in data.get("data_streams", []):
        backing = ds.get("indices", [])
        write_idx = backing[-1].get("index_name") if backing else "-"
        rows.append({
            "name": ds.get("name", "-"),
            "status": ds.get("status", "-"),
            "generation": ds.get("generation", "-"),
            "backing_count": len(backing),
            "write_index": write_idx,
            "template": ds.get("template", "-"),
        })
    rows.sort(key=lambda r: r["name"])
    return rows


def print_data_streams(rows):
    if isinstance(rows, dict) and "error" in rows:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No data streams found")
        return
    _print_columns(rows, [
        ("Name",       "name",          None),
        ("Status",     "status",        None),
        ("Gen",        "generation",    None),
        ("Backing",    "backing_count", None),
        ("Write Idx",  "write_index",   None),
        ("Template",   "template",      None),
    ])
    print(f"\nTotal: {len(rows)} data stream(s)")


def print_change_policy_results(results):
    if isinstance(results, dict) and "error" in results:
        print(json.dumps(results, indent=2))
        return
    for r in results:
        icon = "\033[92m✓\033[0m" if r["ok"] else "\033[91m✗\033[0m"
        resp = r.get("response") or {}
        updated = resp.get("updated_indices", "-")
        # ISM uses 'failed_indices' (list of {index_name, index_uuid, reason}).
        # 'failures' is a boolean flag in the same response.
        failed = resp.get("failed_indices") or []
        # 'updated' may also be top-level for retry-style responses
        if updated == "-":
            updated = resp.get("updated", "-")
        if failed:
            detail = f"updated={updated} failed={len(failed)}"
        else:
            detail = f"updated={updated}"
        print(f"  {icon} {r['pattern']:55s} HTTP {r['status']}  {detail}")
        for f in failed:
            name = f.get("index_name") or f.get("index") or "?"
            reason = f.get("reason") or "(no reason)"
            print(f"      \033[91m✗\033[0m {name}: {reason}")


def print_policy_status(results, show_errors=True):
    if not results:
        print("No indices match the filter")
        return
    columns = [
        ("Index",   "index",       None),
        ("Policy",  "policy",      None),
        ("Phase",   "phase",       None),
        ("Action",  "action",      None),
        ("Step",    "step",        "step_status"),
        ("Status",  "step_status", "step_status"),
        ("Retries", "retries",     None),
        ("In Step", "time_in_step",None),
    ]
    _print_columns(results, columns)

    if show_errors:
        problem_rows = [r for r in results if r["step_status"] in ("failed", "retrying") and r.get("error")]
        if problem_rows:
            print("\nErrors:")
            for r in problem_rows:
                print(f"  \033[91m✗\033[0m {r['index']} [{r['step']}] {r['error']}")

    counts = {}
    for r in results:
        counts[r["step_status"]] = counts.get(r["step_status"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    print(f"\nTotal: {len(results)} index(es) — {summary}")
