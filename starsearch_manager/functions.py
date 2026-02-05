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


def delete_index_pattern(config, pattern_id, target=None):
    """Delete an index pattern from .kibana or Dashboards API."""
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    base_url = get_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API (requires osd-xsrf header for DELETE)
        headers = {'osd-xsrf': 'true'}
        delete_resp = requests.delete(f"{base_url}/api/saved_objects/index-pattern/{pattern_id}", auth=auth, verify=verify_ssl, headers=headers)
    else:
        # Use direct .kibana index access
        delete_resp = requests.delete(f"{base_url}/.kibana/_doc/index-pattern:{pattern_id}", auth=auth, verify=verify_ssl)

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


def list_dashboards(config, target=None, obj_type=None):
    """List saved objects (dashboards, visualizations, searches) from .kibana or Dashboards API."""
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    base_url = get_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API
        if obj_type:
            url = f"{base_url}/api/saved_objects/_find?type={obj_type}&per_page=1000"
        else:
            url = f"{base_url}/api/saved_objects/_find?type=dashboard&type=visualization&type=search&per_page=1000"

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
        # Use direct .kibana index access
        url = f"{base_url}/.kibana/_search?size=1000"
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


def list_index_patterns(config, target=None):
    """List all index patterns from .kibana index or Dashboards API."""
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    base_url = get_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API
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

            results.append({
                'id': pattern_id,
                'title': title
            })
    else:
        # Use direct .kibana index access (Elasticsearch/OpenSearch)
        url = f"{base_url}/.kibana/_search?size=1000"
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

            results.append({
                'id': obj_id,
                'title': title
            })

    return results


def delete_saved_object(config, obj_id, obj_type, target=None):
    """Delete a saved object (dashboard, visualization, or search) from .kibana or Dashboards API.

    Args:
        config: Configuration dictionary
        obj_id: ID of the object to delete
        obj_type: Type of object - "dashboard", "visualization", or "search"
        target: Optional server name
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    base_url = get_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API (requires osd-xsrf header for DELETE)
        headers = {'osd-xsrf': 'true'}
        delete_resp = requests.delete(f"{base_url}/api/saved_objects/{obj_type}/{obj_id}", auth=auth, verify=verify_ssl, headers=headers)
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
        # Use direct .kibana index access
        # Try with type prefix first
        delete_resp = requests.delete(f"{base_url}/.kibana/_doc/{obj_type}:{obj_id}", auth=auth, verify=verify_ssl)

        if delete_resp.status_code == 200:
            return {
                "success": True,
                "id": obj_id,
                "type": obj_type,
                "message": f"{obj_type.capitalize()} '{obj_id}' deleted successfully"
            }
        elif delete_resp.status_code == 404:
            # Try without prefix
            delete_resp = requests.delete(f"{base_url}/.kibana/_doc/{obj_id}", auth=auth, verify=verify_ssl)
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
        # Calculate column widths for index patterns (no type field)
        id_width = max(len(r['id']) for r in results) if results else 2
        id_width = max(id_width, len('ID'))
        title_width = max(len(r['title']) for r in results) if results else 5
        title_width = max(title_width, len('Title'))

        # Print header
        header = f"{'ID'.ljust(id_width)}  {'Title'.ljust(title_width)}"
        print(header)
        print("-" * len(header))

        # Print rows
        for r in results:
            print(f"{r['id'].ljust(id_width)}  {r['title'].ljust(title_width)}")


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


def export_saved_objects(config, target=None, obj_ids=None, obj_type=None):
    """Export saved objects (dashboards/visualizations/searches) to ndjson format with index-pattern mapping."""
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url, use_dashboards_api

    server, _ = get_server(config, target)
    base_url = get_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    index_pattern_map = {}
    ndjson_lines = []

    if use_dashboards_api(server):
        # Use OpenSearch Dashboards API
        ip_resp = requests.get(f"{base_url}/api/saved_objects/_find?type=index-pattern&per_page=1000", auth=auth, verify=verify_ssl)
        if ip_resp.status_code != 200:
            return {"error": f"Failed to fetch index patterns: {ip_resp.status_code}"}

        ip_data = ip_resp.json()

        for obj in ip_data.get('saved_objects', []):
            obj_id = obj['id']
            title = obj.get('attributes', {}).get('title')
            if title:
                index_pattern_map[obj_id] = title

        url = f"{base_url}/api/saved_objects/_find?type=dashboard&type=visualization&type=search&per_page=1000"
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
        # Use direct .kibana index access
        resp = requests.get(f"{base_url}/.kibana/_search?size=1000", auth=auth, verify=verify_ssl)
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


def import_saved_objects(config, ndjson_content, target=None, obj_type=None):
    """Import saved objects from ndjson directly to .kibana index.

    Args:
        config: Configuration dictionary
        ndjson_content: NDJSON formatted string with saved objects
        target: Optional server name
        obj_type: Optional filter - only import objects of this type
    """
    from .cli import get_server, get_auth, get_verify_ssl, get_base_url

    server, _ = get_server(config, target)
    base_url = get_base_url(server)
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)

    lines = ndjson_content.strip().split('\n')

    imported = []
    skipped = []

    for line in lines:
        if not line.strip():
            continue

        obj = json.loads(line)

        # Skip metadata lines
        if '_index_pattern_map' in obj:
            continue

        # Filter by type if specified
        if obj_type and obj.get('type') != obj_type:
            skipped.append({'id': obj.get('id', 'unknown'), 'reason': f"Type mismatch (expected {obj_type}, got {obj.get('type')})"})
            continue

        # Build document for .kibana index
        doc = {
            obj['type']: obj['attributes'],
            'type': obj['type']
        }
        if 'references' in obj:
            doc['references'] = obj['references']

        # Import by writing directly to .kibana index
        import_resp = requests.put(
            f"{base_url}/.kibana/_doc/{obj['type']}:{obj['id']}",
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

    return {'imported': imported, 'skipped': skipped}
