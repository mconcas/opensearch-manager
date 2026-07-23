"""Indices, field mappings, and the field cache Dashboards keeps for a pattern."""

import json

from .client import ApiError
from .output import GREEN, RED, YELLOW, paint

# OpenSearch mapping type -> the type Dashboards displays, mirroring its
# castEsToKbnFieldTypeName(). A type missing from this table is one Dashboards
# cannot render, and shows up as the "?" icon in the field list.
OSD_TYPES = {
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

STRING_TYPES = {mapping for mapping, osd in OSD_TYPES.items()
                if osd == "string" and not mapping.startswith("_")}


def delete_index(client, name):
    client.fetch(name, method="DELETE")
    return f"Deleted index '{name}'"


# --------------------------------------------------------------------------
# Field capabilities
# --------------------------------------------------------------------------

def field_caps(client, pattern, non_keyword=False, conflicts=False, unknown=False):
    """Field types across a pattern, as Dashboards would resolve them.

    A field mapped differently by two matching indices is a conflict; a field
    whose type Dashboards does not know renders as "?" there. The flags narrow
    the report to exactly those cases.
    """
    data = client.fetch(f"{pattern}/_field_caps", params={"fields": "*"})
    raw = data.get("fields", {})

    fields = []
    for name, by_type in sorted(raw.items()):
        types = sorted(by_type)
        # Internal metadata (_seq_no, _version, ...) is not in the field list
        # Dashboards shows, so it is never flagged as unknown.
        metadata = name.startswith("_") or all(t.startswith("_") for t in types)
        entry = {
            "field": name,
            "types": types,
            "conflict": len(types) > 1,
            "unknown": not metadata and any(t not in OSD_TYPES for t in types),
            "string_like": all(t in STRING_TYPES for t in types),
            "aggregatable": any(spec.get("aggregatable") for spec in by_type.values()),
            "searchable": any(spec.get("searchable") for spec in by_type.values()),
        }
        if entry["conflict"]:
            entry["indices_by_type"] = {t: spec["indices"]
                                        for t, spec in by_type.items() if spec.get("indices")}
        if conflicts and not entry["conflict"]:
            continue
        if unknown and not entry["unknown"]:
            continue
        if non_keyword and entry["string_like"]:
            continue
        fields.append(entry)

    return {
        "pattern": pattern,
        "indices": data.get("indices", []),
        "total_fields": len(raw),
        "reported_fields": len(fields),
        "fields": fields,
    }


def print_field_caps(result):
    print(f"\nPattern: {result['pattern']}")
    print(f"Matching indices: {len(result['indices'])}")
    print(f"Fields: {result['reported_fields']} shown / {result['total_fields']} total")
    print("=" * 80)

    if not result["fields"]:
        print("(no fields match the given filters)")
        return

    for field in result["fields"]:
        flags = []
        if field["unknown"]:
            flags.append(paint("?unknown", YELLOW))
        if field["conflict"]:
            flags.append(paint("CONFLICT", RED))
        suffix = "" if field["aggregatable"] else " (not aggregatable)"
        print(f"  {field['field']:<50} {','.join(field['types'])}{suffix}"
              + (f"  [{' '.join(flags)}]" if flags else ""))
        for mapping_type, indices in (field.get("indices_by_type") or {}).items():
            shown = ", ".join(indices[:3]) + (" ..." if len(indices) > 3 else "")
            print(f"      {mapping_type}: {shown}")

    print("=" * 80)
    print(f"{sum(1 for f in result['fields'] if f['unknown'])} field(s) render as "
          f"'?' (unknown type), "
          f"{sum(1 for f in result['fields'] if f['conflict'])} conflict(s)")


# --------------------------------------------------------------------------
# Index-pattern field cache
# --------------------------------------------------------------------------

def refresh_index_pattern(client, pattern_id, apply=False):
    """Rebuild a pattern's cached field list from the live mapping.

    Dashboards caches the field list inside the index-pattern saved object and
    only rewrites it when someone presses "Refresh field list"; until then,
    aggregations and controls cannot see fields added to the mapping since.
    This is that button. Without `apply` nothing is written.
    """
    if client.use_osd_api:
        raise ApiError("Refresh needs direct .kibana access; this target is "
                       "configured for the Dashboards API")

    path = f".kibana/_doc/index-pattern:{pattern_id}"
    source = client.fetch(path)["_source"]
    pattern = source.get("index-pattern", {})
    title = pattern.get("title")
    if not title:
        raise ApiError(f"Index pattern '{pattern_id}' has no title")

    try:
        cached = json.loads(pattern.get("fields", "[]"))
    except (ValueError, TypeError):
        cached = []
    by_name = {field["name"]: field for field in cached}

    live = client.fetch(f"{title}/_field_caps", params={"fields": "*"}).get("fields", {})
    fresh = _index_pattern_fields({name: spec for name, spec in live.items()
                                   if not name.startswith("_")})

    # Meta fields (_source, _score, ...) and scripted fields are kept: some are
    # absent from _field_caps entirely and Dashboards preserves them too.
    preserved = [f for f in cached if f["name"].startswith("_") or f.get("scripted")]
    preserved_names = {f["name"] for f in preserved}
    fresh = [f for f in fresh if f["name"] not in preserved_names]
    for field in fresh:
        field["count"] = by_name.get(field["name"], {}).get("count", 0)

    fields = sorted(preserved + fresh, key=lambda field: field["name"])
    result = {
        "pattern_id": pattern_id,
        "title": title,
        "old_field_count": len(cached),
        "new_field_count": len(fields),
        "added": sorted({f["name"] for f in fields} - set(by_name)),
        "removed": sorted(set(by_name) - {f["name"] for f in fields}),
        "applied": False,
    }
    if apply:
        pattern["fields"] = json.dumps(fields)
        source["index-pattern"] = pattern
        client.fetch(path, method="PUT", json=source)
        result["applied"] = True
    return result


def _index_pattern_fields(by_name):
    """The cached field list Dashboards builds from a _field_caps response."""
    primary = {name: sorted(spec)[0] if spec else None for name, spec in by_name.items()}

    fields = []
    for name in sorted(by_name):
        by_type = by_name[name]
        mapping_types = sorted(by_type)
        osd_types = {OSD_TYPES.get(t, "unknown") for t in mapping_types}
        aggregatable = any(spec.get("aggregatable") for spec in by_type.values())
        field = {
            "count": 0,
            "name": name,
            "type": osd_types.pop() if len(osd_types) == 1 else "conflict",
            # `esTypes` is the key Dashboards writes; it means the raw mapping types.
            "esTypes": mapping_types,
            "scripted": False,
            "searchable": any(spec.get("searchable") for spec in by_type.values()),
            "aggregatable": aggregatable,
            "readFromDocValues": (
                aggregatable
                and mapping_types[0] not in ("text", "geo_shape", "flattened")
                and not mapping_types[0].startswith("_")
            ),
        }
        # A dotted field whose parent is a leaf is a multi-field, like
        # `host.name.keyword` under the text field `host.name`. A parent that
        # is an object is just a path, not a multi-field.
        if "." in name:
            parent = name.rsplit(".", 1)[0]
            if primary.get(parent) not in (None, "object", "nested"):
                field["subType"] = {"multi": {"parent": parent}}
        fields.append(field)
    return fields


def print_refresh(result):
    mode = "APPLIED" if result["applied"] else "DRY-RUN (nothing written)"
    print(f"\nIndex pattern: {result['pattern_id']}  ({result['title']})")
    print(f"Mode: {mode}")
    print(f"Cached fields: {result['old_field_count']} -> {result['new_field_count']}")
    print("=" * 80)
    for name in result["added"]:
        print(paint(f"    + {name}", GREEN))
    for name in result["removed"]:
        print(paint(f"    - {name}", RED))
    if not result["added"] and not result["removed"]:
        print("Cache already matches the live mapping - nothing to refresh.")
    print("=" * 80)
    if not result["applied"]:
        print("Re-run without --dry-run to write the refreshed field list.")
