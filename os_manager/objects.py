"""Saved objects: dashboards, visualizations, searches, index patterns.

Every read and write goes through `fetch_objects` / `delete_object` / the
import helpers below, so the two access modes - the Dashboards saved-objects
API and direct `.kibana` index access - are each expressed exactly once.
"""

import fnmatch
import json

from .client import ApiError
from .output import BOLD, GREEN, RED, RESET, YELLOW, table

SAVED_TYPES = ("dashboard", "visualization", "search")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def fetch_objects(client, types):
    """Saved objects of the given types, normalised across both access modes.

    Returns dicts of: type, id, title, attributes, references, workspaces,
    updated_at. Through the Dashboards API the result covers the client's
    workspace only; `.kibana` has no such scope and always holds everything.
    """
    if client.use_osd_api:
        raw = _fetch_via_api(client, types)
    else:
        raw = _fetch_via_kibana_index(client, types)
    return [dict(obj, title=obj["attributes"].get("title") or "N/A") for obj in raw]


def _fetch_via_api(client, types):
    query = "&".join(f"type={otype}" for otype in types)
    page, objects = 1, []
    while True:
        data = client.fetch(
            f"api/saved_objects/_find?{query}&per_page=1000&page={page}", osd=True
        )
        found = data.get("saved_objects", [])
        objects.extend(
            {
                "type": obj["type"],
                "id": obj["id"],
                "attributes": obj.get("attributes", {}),
                "references": obj.get("references", []),
                # Workspace-enabled Dashboards reports 'workspaces'; older
                # builds carry the same idea as 'namespaces'.
                "workspaces": _workspaces(obj.get("workspaces") or obj.get("namespaces")),
                "updated_at": obj.get("updated_at") or "",
            }
            for obj in found
        )
        if not found or len(objects) >= data.get("total", 0):
            return objects
        page += 1


def _fetch_via_kibana_index(client, types):
    data = client.fetch(".kibana/_search?size=10000")
    objects = []
    for hit in data["hits"]["hits"]:
        source = hit["_source"]
        otype = source.get("type")
        if otype not in types:
            continue
        attributes = source.get(otype)
        namespace = source.get("namespace")
        objects.append({
            "type": otype,
            # Saved-object ids are stored prefixed with their type: "dashboard:abc".
            "id": hit["_id"].split(":", 1)[1] if ":" in hit["_id"] else hit["_id"],
            "attributes": attributes if isinstance(attributes, dict) else {},
            "references": source.get("references", []),
            "workspaces": _workspaces([namespace] if namespace else []),
            "updated_at": source.get("updated_at") or "",
        })
    return objects


def _workspaces(values):
    """Workspace ids an object belongs to.

    "default" is dropped: it is the name of the classic saved-objects namespace
    every object carries where workspaces are not in use, so reporting it would
    make a workspace out of their absence.
    """
    return [value for value in (values or []) if value != "default"]


def list_objects(client, obj_type=None):
    """Rows for `osm <type> list`."""
    types = (obj_type,) if obj_type else SAVED_TYPES
    rows = [
        {"type": obj["type"], "id": obj["id"], "title": obj["title"]}
        for obj in fetch_objects(client, types)
    ]
    rows.sort(key=lambda row: (row["type"], row["title"]))
    return rows


def print_objects(rows):
    if not rows:
        print("No objects found")
        return
    table(rows, [("Type", "type"), ("ID", "id"), ("Title", "title")])


def list_index_patterns(client):
    """Rows for `osm index-pattern list`.

    Beyond id and title this reports what tells two similar patterns apart: the
    time field, the workspaces the pattern belongs to, and how stale its field
    cache is - see `osm index-pattern refresh`.
    """
    rows = [
        {
            "id": obj["id"],
            "title": obj["title"],
            "time_field": obj["attributes"].get("timeFieldName"),
            "workspaces": ", ".join(obj["workspaces"]),
            "fields": _cached_field_count(obj["attributes"].get("fields")),
            "updated": obj["updated_at"].replace("T", " ")[:16],
        }
        for obj in fetch_objects(client, ("index-pattern",))
    ]
    rows.sort(key=lambda row: row["title"])
    return rows


def _cached_field_count(fields):
    """Fields in a pattern's cache, or None when it cannot be read.

    Dashboards stores the cached field list as a JSON-encoded string.
    """
    if not fields:
        return 0
    try:
        return len(json.loads(fields))
    except (ValueError, TypeError):
        return None


def print_index_patterns(rows):
    if not rows:
        print("No index patterns found")
        return
    table(rows, [("ID", "id"), ("Title", "title"), ("Time Field", "time_field"),
                 ("Workspaces", "workspaces"), ("Fields", "fields"),
                 ("Updated", "updated")])


def list_workspaces(client):
    """Workspaces defined on the target's Dashboards instance.

    The `_list` API is itself global rather than workspace-scoped, so it is the
    way to discover the ids `-w` takes.
    """
    if not client.use_osd_api:
        raise ApiError(f"Target '{client.name}' has no 'dashboards' endpoint, "
                       f"so it has no workspaces")
    resp = client.request("POST", "api/workspaces/_list", osd=True, scoped=False,
                          json={})
    if resp.status_code == 404:
        raise ApiError(f"Dashboards at {client.osd_url} has no workspaces API; "
                       f"the workspace feature is not enabled there")
    if not resp.ok:
        raise ApiError(f"Failed to list workspaces: HTTP {resp.status_code}: "
                       f"{resp.text.strip()}")
    try:
        data = resp.json()
    except ValueError:
        raise ApiError(f"Unexpected response from the workspaces API: {resp.text.strip()}")
    # Dashboards wraps the list in {"success": true, "result": {"workspaces": [...]}};
    # some versions put the list straight under "result".
    result = data.get("result", data) if isinstance(data, dict) else data
    found = result.get("workspaces", result) if isinstance(result, dict) else result
    if not isinstance(found, list):
        raise ApiError(f"Unexpected response from the workspaces API: {found}")
    rows = [
        {
            "id": workspace.get("id"),
            "name": workspace.get("name"),
            "description": workspace.get("description"),
        }
        for workspace in found
    ]
    rows.sort(key=lambda row: row["name"] or "")
    return rows


def print_workspaces(rows):
    if not rows:
        print("No workspaces found")
        return
    table(rows, [("ID", "id"), ("Name", "name"), ("Description", "description")])


# --------------------------------------------------------------------------
# Export / import
# --------------------------------------------------------------------------

def export_objects(client, obj_ids=None, obj_type=None):
    """Saved objects as ndjson, prefixed with an index-pattern id -> title map.

    Queries and filters are stripped from `searchSourceJSON` so an exported
    object lands on the other cluster showing everything rather than whatever
    was pinned when it was saved.
    """
    types = (obj_type,) if obj_type else SAVED_TYPES
    patterns = {
        obj["id"]: obj["title"]
        for obj in fetch_objects(client, ("index-pattern",))
        if obj["title"] != "N/A"
    }

    lines = [json.dumps({"_index_pattern_map": patterns})]
    for obj in fetch_objects(client, types):
        if obj_ids and obj["id"] not in obj_ids:
            continue
        lines.append(json.dumps({
            "id": obj["id"],
            "type": obj["type"],
            "attributes": _strip_pinned_query(obj["attributes"]),
            "references": obj["references"],
        }))
    return "\n".join(lines)


def _strip_pinned_query(attributes):
    meta = attributes.get("kibanaSavedObjectMeta")
    if not isinstance(meta, dict) or "searchSourceJSON" not in meta:
        return attributes
    try:
        source = json.loads(meta["searchSourceJSON"])
    except (ValueError, TypeError):
        return attributes
    if isinstance(source.get("query"), dict):
        source["query"]["query"] = ""
    if "filter" in source:
        source["filter"] = []
    meta["searchSourceJSON"] = json.dumps(source)
    return attributes


def import_objects(client, ndjson, obj_type=None):
    """Import ndjson produced by `export_objects` (or by Dashboards itself)."""
    objects, skipped = [], []
    for line in ndjson.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if "_index_pattern_map" in obj:
            continue
        if obj_type and obj.get("type") != obj_type:
            skipped.append({"id": obj.get("id"), "type": obj.get("type")})
            continue
        objects.append(obj)

    if not objects:
        return {"imported": [], "skipped": skipped}
    imported = (_import_via_api(client, objects) if client.use_osd_api
                else _import_via_kibana_index(client, objects))
    return {"imported": imported, "skipped": skipped}


def _import_via_api(client, objects):
    """Upload through the Dashboards import API, which runs its migrations."""
    payload = "\n".join(json.dumps(obj) for obj in objects)
    result = client.fetch(
        "api/saved_objects/_import?overwrite=true", method="POST", osd=True,
        files={"file": ("objects.ndjson", payload, "application/ndjson")},
    )
    errors = {
        (err.get("type"), err.get("id")): err.get("error")
        for err in result.get("errors", [])
    }
    return [
        {
            "id": obj["id"],
            "type": obj["type"],
            "title": obj.get("attributes", {}).get("title", "N/A"),
            "error": errors.get((obj["type"], obj["id"])),
        }
        for obj in objects
    ]


def _import_via_kibana_index(client, objects):
    """Write straight into `.kibana` - the only route without Dashboards.

    Objects written this way are tagged with no workspace, so a workspace-aware
    Dashboards shows them only in the global scope.
    """
    if client.workspace:
        print(f"Warning: target '{client.name}' has no 'dashboards' endpoint; "
              f"writing to .kibana unscoped, workspace '{client.workspace}' ignored")
    imported = []
    for obj in objects:
        document = {"type": obj["type"], obj["type"]: obj["attributes"]}
        if obj.get("references"):
            document["references"] = obj["references"]
        resp = client.request(
            "PUT", f".kibana/_doc/{obj['type']}:{obj['id']}", json=document
        )
        imported.append({
            "id": obj["id"],
            "type": obj["type"],
            "title": obj.get("attributes", {}).get("title", "N/A"),
            "error": None if resp.ok else resp.text.strip(),
        })
    return imported


def print_import(result):
    """Print an import result. Returns how many objects failed."""
    for obj in result["imported"]:
        ok = obj["error"] is None
        icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        print(f"  {icon} {obj['type']}/{obj['id']}  {obj['title']}")
        if not ok:
            print(f"      {obj['error']}")
    for obj in result["skipped"]:
        print(f"  - skipped {obj['type']}/{obj['id']} (type filtered out)")
    failed = sum(1 for obj in result["imported"] if obj["error"])
    print(f"\nImported {len(result['imported']) - failed}, failed {failed}, "
          f"skipped {len(result['skipped'])}")
    return failed


# --------------------------------------------------------------------------
# Deletion
# --------------------------------------------------------------------------

def delete_object(client, obj_id, obj_type):
    """Delete one saved object of any type, including index patterns."""
    if client.use_osd_api:
        client.fetch(f"api/saved_objects/{obj_type}/{obj_id}", method="DELETE", osd=True)
    else:
        client.fetch(f".kibana/_doc/{obj_type}:{obj_id}", method="DELETE")
    return f"Deleted {obj_type} '{obj_id}'"


# --------------------------------------------------------------------------
# Dashboard validation
# --------------------------------------------------------------------------

def validate_dashboards(client, dashboard_ids=None):
    """Walk dashboard -> visualization -> search -> index pattern -> cluster.

    Reports broken references, index patterns that resolve to nothing, fields
    referenced by a visualization but absent from the mapping, and malformed
    queries or panel JSON.
    """
    objects = {
        f"{obj['type']}:{obj['id']}": obj
        for obj in fetch_objects(client, SAVED_TYPES + ("index-pattern",))
    }
    patterns = {
        obj["id"]: {
            "title": obj["attributes"].get("title", ""),
            "time_field": obj["attributes"].get("timeFieldName"),
        }
        for obj in objects.values() if obj["type"] == "index-pattern"
    }

    resolver = _IndexResolver(client)
    global_issues = []
    for pattern_id, pattern in patterns.items():
        title = pattern["title"]
        if not title:
            global_issues.append(_issue("error", "missing-index",
                                        f"Index pattern '{pattern_id}' has no title"))
            continue
        if not resolver.matches(title):
            global_issues.append(_issue(
                "error", "missing-index",
                f"Index pattern '{title}' (id: {pattern_id}) matches no index, "
                f"alias, or data stream"))
        elif pattern["time_field"]:
            fields = resolver.fields(title)
            if fields is not None and pattern["time_field"] not in fields:
                global_issues.append(_issue(
                    "warning", "missing-field",
                    f"Index pattern '{title}': time field "
                    f"'{pattern['time_field']}' is not in the mapping"))

    results = []
    for obj in objects.values():
        if obj["type"] != "dashboard":
            continue
        if dashboard_ids and obj["id"] not in dashboard_ids:
            continue
        issues = _validate_dashboard(obj, objects, patterns, resolver)
        results.append({
            "id": obj["id"],
            "title": obj["title"],
            "issues": issues,
            "status": "ok" if not issues else (
                "error" if any(i["level"] == "error" for i in issues) else "warning"
            ),
        })

    results.sort(key=lambda d: d["title"])
    return {
        "dashboards": results,
        "global_issues": global_issues,
        "summary": {
            "total_dashboards": len(results),
            "ok": sum(1 for d in results if d["status"] == "ok"),
            "warnings": sum(1 for d in results if d["status"] == "warning"),
            "errors": sum(1 for d in results if d["status"] == "error"),
            "global_issues": len(global_issues),
        },
    }


def _issue(level, check, message):
    return {"level": level, "check": check, "message": message}


class _IndexResolver:
    """Answers "does this pattern resolve?" and "what fields does it have?".

    Both answers come from the cluster, which already knows how to expand
    wildcards, aliases and data streams; results are cached per pattern.
    """

    def __init__(self, client):
        self.client = client
        self._names = None
        self._fields = {}

    @property
    def names(self):
        if self._names is None:
            names = set()
            for path, key in (("_cat/indices?format=json&h=index", "index"),
                              ("_cat/aliases?format=json&h=alias", "alias")):
                try:
                    names |= {entry.get(key) for entry in self.client.fetch(path)}
                except ApiError:
                    pass
            try:
                for stream in self.client.fetch("_data_stream").get("data_streams", []):
                    names.add(stream.get("name"))
                    names |= {idx.get("index_name") for idx in stream.get("indices", [])}
            except ApiError:
                pass
            self._names = {name for name in names if name}
        return self._names

    def matches(self, pattern):
        return any(fnmatch.fnmatch(name, pattern) for name in self.names)

    def fields(self, pattern):
        """Flattened dotted field paths for a pattern, or None if unavailable."""
        if pattern not in self._fields:
            try:
                mapping = self.client.fetch(f"{pattern}/_mapping")
            except ApiError:
                self._fields[pattern] = None
                return None
            fields = set()
            for index in mapping.values():
                fields |= _flatten(index.get("mappings", {}).get("properties", {}))
            self._fields[pattern] = fields or None
        return self._fields[pattern]


def _flatten(properties, prefix=""):
    """Mapping properties as dotted paths, including multi- and sub-fields."""
    fields = set()
    for name, definition in properties.items():
        if not isinstance(definition, dict):
            continue
        path = f"{prefix}{name}"
        fields.add(path)
        fields |= {f"{path}.{sub}" for sub in definition.get("fields", {})}
        fields |= _flatten(definition.get("properties", {}), prefix=f"{path}.")
    return fields


def _validate_dashboard(dashboard, objects, patterns, resolver):
    issues = []
    for ref in dashboard["references"]:
        child = objects.get(f"{ref.get('type')}:{ref.get('id')}")
        if child is None:
            issues.append(_issue(
                "error", "broken-reference",
                f"Referenced {ref.get('type')} '{ref.get('id')}' not found"))
            continue
        if child["type"] in ("visualization", "search"):
            issues.extend(_validate_child(child, objects, patterns, resolver))

    panels = dashboard["attributes"].get("panelsJSON")
    if isinstance(panels, str):
        try:
            json.loads(panels)
        except json.JSONDecodeError as exc:
            issues.append(_issue("error", "invalid-json",
                                 f"Dashboard panelsJSON is malformed: {exc}"))
    if not dashboard["references"] and not panels:
        issues.append(_issue("warning", "empty-dashboard",
                             "Dashboard has no panels or references"))
    return issues


def _validate_child(obj, objects, patterns, resolver):
    """Check one visualization or saved search and the fields it reads."""
    label = f"{obj['type'].capitalize()} '{obj['title']}' (id: {obj['id']})"
    issues = []
    pattern_id = None

    for ref in obj["references"]:
        ref_type, ref_id = ref.get("type"), ref.get("id")
        if ref_type == "index-pattern":
            if ref_id not in patterns:
                issues.append(_issue("error", "broken-reference",
                                     f"{label} references missing index pattern '{ref_id}'"))
            else:
                pattern_id = pattern_id or ref_id
        elif ref_type == "search":
            search = objects.get(f"search:{ref_id}")
            if search is None:
                issues.append(_issue("error", "broken-reference",
                                     f"{label} references missing search '{ref_id}'"))
            else:
                # A visualization can inherit its index pattern from its search.
                pattern_id = pattern_id or next(
                    (r.get("id") for r in search["references"]
                     if r.get("type") == "index-pattern"), None)

    if pattern_id in patterns:
        title = patterns[pattern_id]["title"]
        if not resolver.matches(title):
            issues.append(_issue("error", "missing-index",
                                 f"{label} uses index pattern '{title}' with no matching indices"))
        else:
            fields = resolver.fields(title)
            if fields is not None:
                for name, context in _referenced_fields(obj):
                    if name.startswith("_") or name == "*" or name in fields:
                        continue
                    issues.append(_issue(
                        "error", "missing-field",
                        f"{label} references field '{name}' not found in "
                        f"'{title}' [{context}]"))

    issues.extend(_validate_search_source(obj, label))
    return issues


def _referenced_fields(obj):
    """(field, context) pairs a visualization or saved search reads."""
    attributes = obj["attributes"]
    fields = []

    for column in attributes.get("columns", []) or []:
        if isinstance(column, str):
            fields.append((column, "search column"))

    state = attributes.get("visState")
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except (ValueError, TypeError):
            state = None
    if isinstance(state, dict):
        for agg in state.get("aggs", []) or []:
            if not isinstance(agg, dict):
                continue
            params = agg.get("params", {})
            context = f'agg "{agg.get("type", "?")}" (id: {agg.get("id", "?")})'
            if isinstance(params.get("field"), str):
                fields.append((params["field"], context))
            # An agg may carry a hand-written JSON body with more field refs.
            try:
                fields += [(name, f"{context} custom JSON")
                           for name in _nested_fields(json.loads(params.get("json") or "{}"))]
            except (ValueError, TypeError):
                pass

        params = state.get("params", {})
        if isinstance(params, dict):
            if isinstance(params.get("field"), str):
                fields.append((params["field"], f'vis params ({state.get("type", "?")})'))
            for i, series in enumerate(params.get("series", []) or []):
                if not isinstance(series, dict):
                    continue
                metrics = series.get("metrics", []) or []
                # Pipeline aggs reference sibling metric ids in `field`; those
                # are not mapping fields.
                metric_ids = {m.get("id") for m in metrics if isinstance(m, dict)}
                for metric in metrics:
                    field = isinstance(metric, dict) and metric.get("field")
                    if isinstance(field, str) and field not in metric_ids:
                        fields.append((field, f"TSVB series[{i}] metric"))
                if isinstance(series.get("terms_field"), str):
                    fields.append((series["terms_field"], f"TSVB series[{i}] terms_field"))

    for filter_ in _search_source(obj).get("filter", []) or []:
        if not isinstance(filter_, dict):
            continue
        key = filter_.get("meta", {}).get("key") if isinstance(filter_.get("meta"), dict) else None
        if isinstance(key, str):
            fields.append((key, "filter"))
        query = filter_.get("query")
        if isinstance(query, dict):
            for clause in ("match_phrase", "match", "term", "range"):
                if isinstance(query.get(clause), dict):
                    fields += [(name, f"filter {clause}") for name in query[clause]]

    return fields


def _nested_fields(node):
    """Every value of a "field" key anywhere inside a nested structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "field" and isinstance(value, str):
                yield value
            else:
                yield from _nested_fields(value)
    elif isinstance(node, list):
        for item in node:
            yield from _nested_fields(item)


def _search_source(obj):
    meta = obj["attributes"].get("kibanaSavedObjectMeta")
    raw = meta.get("searchSourceJSON") if isinstance(meta, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _validate_search_source(obj, label):
    meta = obj["attributes"].get("kibanaSavedObjectMeta")
    raw = meta.get("searchSourceJSON") if isinstance(meta, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        source = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [_issue("error", "invalid-query",
                       f"{label}: searchSourceJSON is malformed: {exc}")]

    issues = []
    query = source.get("query")
    if isinstance(query, dict) and isinstance(query.get("query"), str):
        text = query["query"]
        if text.count("(") != text.count(")"):
            issues.append(_issue(
                "warning", "invalid-query",
                f"{label}: query has mismatched parentheses "
                f"({query.get('language', '?')}): '{text}'"))

    for filter_ in source.get("filter", []) or []:
        if not isinstance(filter_, dict) or filter_.get("meta", {}).get("disabled"):
            continue
        query = filter_.get("query")
        if not isinstance(query, dict):
            continue
        for clause in ("match_phrase", "match"):
            if isinstance(query.get(clause), dict) and not query[clause]:
                issues.append(_issue("warning", "invalid-query",
                                     f"{label}: filter has an empty {clause} clause"))
    return issues


def print_validation(result):
    """Print validation results. Returns the process exit code."""
    summary = result["summary"]

    if result["global_issues"]:
        print(f"\n{BOLD}Global Issues{RESET}")
        print("=" * 60)
        for issue in result["global_issues"]:
            print(f"  {_level_icon(issue)} {issue['message']}")

    print(f"\n{BOLD}Dashboard Validation Results{RESET}")
    print("=" * 60)
    for dashboard in result["dashboards"]:
        icon = {"ok": f"{GREEN}✓{RESET}", "warning": f"{YELLOW}⚠{RESET}"}.get(
            dashboard["status"], f"{RED}✗{RESET}")
        print(f"\n  {icon} {dashboard['title']}  (id: {dashboard['id']})")
        for issue in dashboard["issues"]:
            print(f"      {_level_icon(issue)} [{issue['check']}] {issue['message']}")

    print(f"\n{'=' * 60}")
    print(f"Total: {summary['total_dashboards']} dashboard(s) - "
          f"{GREEN}{summary['ok']} ok{RESET}, "
          f"{YELLOW}{summary['warnings']} warning(s){RESET}, "
          f"{RED}{summary['errors']} error(s){RESET}, "
          f"{summary['global_issues']} global issue(s)")
    return 1 if summary["errors"] or summary["global_issues"] else 0


def _level_icon(issue):
    return f"{RED}✗{RESET}" if issue["level"] == "error" else f"{YELLOW}⚠{RESET}"
