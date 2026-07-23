"""Anomaly detection detectors."""

import json

SEARCH = "_plugins/_anomaly_detection/detectors/_search"
QUERY = {"query": {"match_all": {}}, "size": 1000}


def fetch_detectors(client, detector_ids=None):
    hits = client.fetch(SEARCH, method="POST", json=QUERY)["hits"]["hits"]
    return [
        {"id": hit["_id"], "detector": hit.get("_source", {})}
        for hit in hits
        if not detector_ids or hit["_id"] in detector_ids
    ]


def list_detectors(client):
    rows = [{"type": "detector", "id": entry["id"],
             "title": entry["detector"].get("name", "N/A")}
            for entry in fetch_detectors(client)]
    rows.sort(key=lambda row: row["title"])
    return rows


def export_detectors(client, detector_ids=None):
    return "\n".join(
        json.dumps({"id": entry["id"], "type": "detector",
                    "detector": entry["detector"]})
        for entry in fetch_detectors(client, detector_ids)
    )
