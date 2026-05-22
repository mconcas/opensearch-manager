#!/usr/bin/env python3
import json
import sys
from pathlib import Path
import requests
import yaml
from . import functions

VERSION = "0.1.0"

def load_config():
    config_path = Path.home() / ".starsearch" / "config.json"
    with open(config_path) as f:
        return json.load(f)

def get_server(config, target=None):
    """Get server configuration by name or return the default (first) server.

    Args:
        config: Configuration dictionary containing 'servers' list
        target: Optional server name to look up

    Returns:
        tuple: (server_dict, is_default_bool)

    Raises:
        SystemExit: If target server is not found (prints available servers and exits)
    """
    servers = config["servers"]
    if target:
        for srv in servers:
            if srv["name"] == target:
                return srv, False

        # Target not found - show helpful error message
        print(f"Error: Server '{target}' not found in configuration", file=sys.stderr)
        print(f"\nAvailable servers:", file=sys.stderr)
        for srv in servers:
            print(f"  - {srv['name']}", file=sys.stderr)
        sys.exit(1)

    return servers[0], True  # default server, is_default=True

def get_auth(server):
    """Get auth tuple from server config if username/password are present."""
    username = server.get("username")
    password = server.get("password")
    if username and password:
        return (username, password)
    return None

def get_verify_ssl(server):
    """Get SSL verification setting from server config (default True)."""
    return server.get("verify_ssl", True)

def get_cluster_base_url(server):
    """Construct base URL for OpenSearch/Elasticsearch cluster API access."""
    protocol = server['protocol']
    host = server['host']
    cluster_path = server.get('cluster_path', '')

    if cluster_path:
        # Ensure cluster_path starts with / and doesn't end with /
        if not cluster_path.startswith('/'):
            cluster_path = '/' + cluster_path
        if cluster_path.endswith('/'):
            cluster_path = cluster_path[:-1]
        return f"{protocol}://{host}{cluster_path}"
    return f"{protocol}://{host}"

def get_base_url(server):
    """Construct base URL from server config including optional base_path (for Dashboards API)."""
    protocol = server['protocol']
    host = server['host']
    base_path = server.get('base_path', '')

    if base_path:
        # Ensure base_path starts with / and doesn't end with /
        if not base_path.startswith('/'):
            base_path = '/' + base_path
        if base_path.endswith('/'):
            base_path = base_path[:-1]
        return f"{protocol}://{host}{base_path}"
    return f"{protocol}://{host}"

def use_dashboards_api(server):
    """Check if we should use OpenSearch Dashboards API (true when base_path is set)."""
    return bool(server.get('base_path'))

def load_commands():
    commands_path = Path(__file__).parent / "commands.yaml"
    with open(commands_path) as f:
        return yaml.safe_load(f)

def resolve_endpoint(args):
    commands = load_commands()

    # Try command mapping: search <cmd> <subcmd> -> _<cmd>/<subcmd>
    if args[0] in commands:
        prefix = commands[args[0]]
        if len(args) > 1:
            return f"{prefix}/{'/'.join(args[1:])}"
        return prefix

    # Fallback: treat as raw endpoint
    return " ".join(args)

def handle_export_output(result, use_json, to_file, output_dir="."):
    """Handle export output: print to stdout or write to files.

    Args:
        result: Export result string (ndjson format)
        use_json: Whether to format as JSON
        to_file: Whether to write to files
        output_dir: Directory to write files to (default: current directory)
    """
    if isinstance(result, dict) and "error" in result:
        print(json.dumps(result, indent=2))
        return

    if to_file:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        lines = [json.loads(line) for line in result.strip().split('\n') if line.strip()]
        for line in lines:
            if '_index_pattern_map' in line:
                continue
            obj_id = line['id']
            ext = '.json' if use_json else '.ndjson'
            filename = output_path / f"{obj_id}{ext}"
            with open(filename, 'w') as f:
                if use_json:
                    f.write(json.dumps(line, indent=2))
                else:
                    f.write(json.dumps(line))
            print(f"Exported: {filename}")
    elif use_json:
        lines = [json.loads(line) for line in result.strip().split('\n') if line.strip()]
        print(json.dumps(lines, indent=2))
    else:
        print(result)

def print_validation_results(result, verbose=False):
    """Print dashboard validation results."""
    if isinstance(result, dict) and "error" in result:
        print(json.dumps(result, indent=2))
        return

    summary = result["summary"]
    global_issues = result["global_issues"]
    dashboards = result["dashboards"]

    # Global issues
    if global_issues:
        print("\n\033[1mGlobal Issues\033[0m")
        print("=" * 60)
        for issue in global_issues:
            icon = "\033[91m✗\033[0m" if issue["level"] == "error" else "\033[93m⚠\033[0m"
            print(f"  {icon} {issue['message']}")

    # Per-dashboard results
    print(f"\n\033[1mDashboard Validation Results\033[0m")
    print("=" * 60)

    for d in dashboards:
        if d["status"] == "ok":
            icon = "\033[92m✓\033[0m"
        elif d["status"] == "warning":
            icon = "\033[93m⚠\033[0m"
        else:
            icon = "\033[91m✗\033[0m"

        print(f"\n  {icon} {d['title']}  (id: {d['id']})")

        if d["issues"]:
            for issue in d["issues"]:
                sub_icon = "\033[91m✗\033[0m" if issue["level"] == "error" else "\033[93m⚠\033[0m"
                print(f"      {sub_icon} [{issue.get('check', 'unknown')}] {issue['message']}")
        elif verbose:
            print(f"      All checks passed")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Total: {summary['total_dashboards']} dashboard(s) — "
          f"\033[92m{summary['ok']} ok\033[0m, "
          f"\033[93m{summary['warnings']} warning(s)\033[0m, "
          f"\033[91m{summary['errors']} error(s)\033[0m, "
          f"{summary['global_issues']} global issue(s)")

    # Exit code hint
    if summary["errors"] > 0 or summary["global_issues"] > 0:
        return 1
    return 0

def handle_saved_object_command(args, cfg, target, obj_type):
    """Generic handler for saved object commands (list/export/import/delete)."""
    if len(args) < 2:
        return False

    subcommand = args[1]

    if subcommand == "list":
        # Use appropriate list function based on type
        results = functions.list_dashboards(cfg, target, obj_type=obj_type)

        if isinstance(results, dict) and "error" in results:
            print(json.dumps(results, indent=2))
        else:
            functions.print_saved_objects(results)
        return True

    elif subcommand == "export":
        use_json = "--json" in args

        # Extract --to-file and its optional path
        to_file = False
        output_dir = "."
        type_filter = obj_type  # inherit from caller (e.g. "dashboard"), may be overridden by --type
        filtered_args = []
        i = 2
        while i < len(args):
            if args[i] == "--to-file":
                to_file = True
                # Check if next arg is a path (not a flag or object ID with hyphens at start)
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    # Could be a path - check if it looks like an object ID or a path
                    next_arg = args[i + 1]
                    # If it contains / or is ".", treat as path; otherwise might be object ID
                    if '/' in next_arg or next_arg == '.':
                        output_dir = next_arg
                        i += 2
                        continue
                i += 1
            elif args[i] == "--type":
                valid_types = ("visualization", "dashboard", "search")
                if i + 1 >= len(args):
                    print("Error: --type requires a value: visualization, dashboard, or search")
                    sys.exit(1)
                type_val = args[i + 1]
                if type_val not in valid_types:
                    print(f"Error: invalid type '{type_val}'. Must be one of: {', '.join(valid_types)}")
                    sys.exit(1)
                type_filter = type_val
                i += 2
            elif args[i] == "--json":
                i += 1
            else:
                filtered_args.append(args[i])
                i += 1

        obj_ids = filtered_args if filtered_args else None
        result = functions.export_saved_objects(cfg, target, obj_ids, obj_type=type_filter)
        handle_export_output(result, use_json, to_file, output_dir)
        return True

    elif subcommand == "import":
        if len(args) < 3:
            obj_name = obj_type or "saved-object"
            print(f"Usage: starsearch-cli {obj_name} import <file.ndjson>")
            sys.exit(1)
        filepath = args[2]
        with open(filepath, 'r') as f:
            ndjson_content = f.read()
        result = functions.import_saved_objects(cfg, ndjson_content, target, obj_type=obj_type)
        print(json.dumps(result, indent=2))
        return True

    elif subcommand == "delete":
        if obj_type is None:
            return False  # saved-object doesn't support delete
        if len(args) < 3:
            print(f"Usage: starsearch-cli {obj_type} delete <id>")
            sys.exit(1)
        obj_id = args[2]
        result = functions.delete_saved_object(cfg, obj_id, obj_type, target)
        print(json.dumps(result, indent=2))
        return True

    return False

def query(endpoint, target=None):
    cfg = load_config()
    server, is_default = get_server(cfg, target)

    if is_default:
        print(f"→ {server['name']}")

    base_url = get_cluster_base_url(server)
    url = f"{base_url}/{endpoint}"
    auth = get_auth(server)
    verify_ssl = get_verify_ssl(server)
    response = requests.get(url, auth=auth, verify=verify_ssl)
    try:
        print(json.dumps(response.json(), indent=2))
    except requests.exceptions.JSONDecodeError:
        print(response.text)

def main():
    if len(sys.argv) > 1 and sys.argv[1] in ["-v", "--version"]:
        print(f"starsearch-cli version {VERSION}")
        sys.exit(0)

    if len(sys.argv) < 2 or sys.argv[1] in ["-h", "--help"]:
        print("Usage: starsearch-cli <command> [args] or starsearch-cli <endpoint>")
        print("       starsearch-cli -t|--target <name> <command> [args]")
        print("       starsearch-cli -v|--version")
        print("\nTarget Management:")
        print("  starsearch-cli target list                              - List all configured targets/servers")
        print("\nObject Management:")
        print("  starsearch-cli saved-object list                        - List all saved objects")
        print("  starsearch-cli saved-object export [id1 id2 ...] [--json] [--type <type>] - Export saved objects")
        print("    --type <type>   Filter by type: visualization, dashboard, or search")
        print("  starsearch-cli saved-object import <file.ndjson>        - Import saved objects from ndjson")
        print("")
        print("  starsearch-cli dashboard list                           - List all dashboards")
        print("  starsearch-cli dashboard export [id1 id2 ...] [--json]  - Export dashboards to ndjson")
        print("  starsearch-cli dashboard import <file.ndjson>           - Import dashboards from ndjson")
        print("  starsearch-cli dashboard delete <id>                    - Delete a dashboard")
        print("  starsearch-cli dashboard validate [id ...] [--verbose] [--json] - Validate dashboards")
        print("")
        print("  starsearch-cli visualization list                       - List all visualizations")
        print("  starsearch-cli visualization export [id1 id2 ...] [--json] - Export visualizations to ndjson")
        print("  starsearch-cli visualization import <file.ndjson>       - Import visualizations from ndjson")
        print("  starsearch-cli visualization delete <id>                - Delete a visualization")
        print("")
        print("  starsearch-cli search list                              - List all saved searches")
        print("  starsearch-cli search export [id1 id2 ...] [--json]     - Export searches to ndjson")
        print("  starsearch-cli search import <file.ndjson>              - Import searches from ndjson")
        print("  starsearch-cli search delete <id>                       - Delete a search")
        print("")
        print("  starsearch-cli detector list                            - List all anomaly detection detectors")
        print("  starsearch-cli detector export [id1 id2 ...] [--json] [--to-file [path]] - Export detectors to ndjson")
        print("\nJobs & Policy Status:")
        print("  starsearch-cli jobs list [--all] [--filter <action>] [--json] - List running cluster tasks")
        print("  starsearch-cli jobs pending [--json]                    - List pending master-level tasks")
        print("  starsearch-cli jobs policy [--json]                     - List in-flight ILM/ISM lifecycle work")
        print("  starsearch-cli ilm status [<index>] [--failed] [--json] - Per-index policy execution status")
        print("  starsearch-cli ilm settings [--json]                    - Show plugins.index_state_management.* cluster settings (effective value + source)")
        print("  starsearch-cli ilm schedule [<index-or-pattern>] [--json] - Show per-managed-index baked-in tick interval (from .opendistro-ism-config)")
        print("\nPolicy Inspection & Repair (ISM):")
        print("  starsearch-cli ilm policy show <name>                   - Show full policy definition")
        print("  starsearch-cli ilm policy version [<index-or-pattern>] [--include-orphans] [--json] - Compare per-index policy_seq_no vs current policy")
        print("  starsearch-cli ilm policy set-rollover <name> [--age <d>] [--size <s>] [--docs <n>] [--primary-shard-size <s>] [--state <name>] - Edit ISM rollover action (additive; pass `none` to remove)")
        print("  starsearch-cli ilm policy set-transition <name> <from-state> <to-state> [--min-size <s>] [--min-rollover-age <d>] [--min-index-age <d>] [--min-doc-count <n>] [--position first|last] - Upsert an ISM transition (pass `none` to drop a condition; empty conditions removes the transition)")
        print("  starsearch-cli ilm policy edit-ism-template <name> [--replace-pattern <old> <new>]* [--add-pattern <p>]* [--remove-pattern <p>]* [--entry-index <n>] [--priority <n>] - Edit ism_template entries on an ISM policy")
        print("  starsearch-cli ilm change-policy <index-or-pattern> <policy-id> [--state <state>] - Re-enrol indices on the named policy (lifts version pinning)")
        print("  starsearch-cli ilm retry <index-or-pattern> [--state <state>]   - Retry a failed ISM step")
        print("  starsearch-cli ilm rollover <data-stream-or-alias>      - Manually roll over a data stream / write alias")
        print("  starsearch-cli data-stream list [<pattern>] [--json]    - List data streams with write index & template")
        print("  starsearch-cli component-template list [<pattern>] [--json] - List component templates and any ISM policy_id baked in")
        print("  starsearch-cli component-template set-policy <name> <policy-id|none> - Bake an ISM policy_id into a component template (deterministic enrollment on rollover)")
        print("  starsearch-cli index-template list [<pattern>] [--json]      - List index templates with effective policy_id (inline or via composed_of)")
        print("  starsearch-cli index-template set-policy <name> <policy-id|none> - Bake an ISM policy_id directly into an index template")
        print("\nOther Commands:")
        print("  starsearch-cli ilm list [--all]                         - Show ILM policy info for indices")
        print("  starsearch-cli ilm <policy> set delete-after <days>     - Set delete phase for a policy")
        print("  starsearch-cli ilm <policy> set warm-after <days>       - Set warm phase for a policy")
        print("  starsearch-cli ilm <policy> set cold-after <days>       - Set cold phase for a policy")
        print("  starsearch-cli ilm <policy> set rollover <size> <docs>  - Set rollover thresholds")
        print("  starsearch-cli index delete <index-name>                - Delete an index")
        print("  starsearch-cli index-pattern list                       - List all index patterns")
        print("  starsearch-cli index-pattern delete <pattern-id>        - Delete an index pattern")
        sys.exit(0 if len(sys.argv) > 1 else 1)

    target = None
    args = sys.argv[1:]

    if args[0] in ["-t", "--target"]:
        if len(args) < 3:
            print("Error: -t/--target requires a server name")
            sys.exit(1)
        target = args[1]
        args = args[2:]

    cfg = load_config()

    # Target commands
    if len(args) >= 2 and args[0] == "target" and args[1] == "list":
        servers = cfg.get("servers", [])
        if not servers:
            print("No targets configured in ~/.starsearch/config.json")
            return

        print("\nConfigured targets:")
        print("="*80)
        for i, srv in enumerate(servers):
            is_default = " (default)" if i == 0 else ""
            print(f"\n{srv['name']}{is_default}")
            print(f"  URL: {srv['protocol']}://{srv['host']}")
            if srv.get('username'):
                print(f"  Auth: {srv['username']}")
            if srv.get('cluster_path'):
                print(f"  Cluster Path: {srv['cluster_path']}")
            if srv.get('base_path'):
                print(f"  Base Path: {srv['base_path']}")
            print(f"  SSL Verify: {srv.get('verify_ssl', True)}")
        print("\n" + "="*80)
        print(f"\nTotal: {len(servers)} target(s)")
        return

    # Saved-object commands (type-agnostic)
    if len(args) >= 2 and args[0] == "saved-object":
        if handle_saved_object_command(args, cfg, target, obj_type=None):
            return

    # Dashboard commands
    if len(args) >= 2 and args[0] == "dashboard":
        if args[1] == "validate":
            verbose = "--verbose" in args or "-v" in args
            use_json_flag = "--json" in args
            # Collect dashboard IDs (everything that's not a flag)
            d_ids = [a for a in args[2:] if not a.startswith("-")]
            result = functions.validate_dashboards(cfg, target, d_ids or None, verbose=verbose)
            if use_json_flag:
                print(json.dumps(result, indent=2))
            else:
                exit_code = print_validation_results(result, verbose=verbose)
                if exit_code:
                    sys.exit(exit_code)
            return
        if handle_saved_object_command(args, cfg, target, obj_type="dashboard"):
            return

    # Visualization commands
    if len(args) >= 2 and args[0] == "visualization":
        if handle_saved_object_command(args, cfg, target, obj_type="visualization"):
            return

    # Search commands
    if len(args) >= 2 and args[0] == "search":
        if handle_saved_object_command(args, cfg, target, obj_type="search"):
            return

    # Detector commands
    if len(args) >= 2 and args[0] == "detector":
        subcommand = args[1]

        if subcommand == "list":
            results = functions.list_detectors(cfg, target)

            if isinstance(results, dict) and "error" in results:
                print(json.dumps(results, indent=2))
            else:
                functions.print_saved_objects(results)
            return

        elif subcommand == "export":
            use_json = "--json" in args

            # Extract --to-file and its optional path
            to_file = False
            output_dir = "."
            filtered_args = []
            i = 2
            while i < len(args):
                if args[i] == "--to-file":
                    to_file = True
                    # Check if next arg is a path
                    if i + 1 < len(args) and not args[i + 1].startswith("--"):
                        next_arg = args[i + 1]
                        if '/' in next_arg or next_arg == '.':
                            output_dir = next_arg
                            i += 2
                            continue
                    i += 1
                elif args[i] == "--json":
                    i += 1
                else:
                    filtered_args.append(args[i])
                    i += 1

            detector_ids = filtered_args if filtered_args else None
            result = functions.export_detectors(cfg, target, detector_ids)
            handle_export_output(result, use_json, to_file, output_dir)
            return

    # Jobs commands
    if len(args) >= 2 and args[0] == "jobs":
        sub = args[1]
        use_json = "--json" in args

        if sub == "list":
            show_all = "--all" in args
            action_filter = None
            if "--filter" in args:
                idx = args.index("--filter")
                if idx + 1 >= len(args):
                    print("Error: --filter requires a value")
                    sys.exit(1)
                action_filter = args[idx + 1]
            results = functions.list_running_tasks(cfg, target, show_all=show_all, action_filter=action_filter)
            if isinstance(results, dict) and "error" in results:
                print(json.dumps(results, indent=2))
                sys.exit(1)
            if use_json:
                print(json.dumps(results, indent=2))
            else:
                functions.print_running_tasks(results)
            return

        if sub == "pending":
            results = functions.list_pending_cluster_tasks(cfg, target)
            if isinstance(results, dict) and "error" in results:
                print(json.dumps(results, indent=2))
                sys.exit(1)
            if use_json:
                print(json.dumps(results, indent=2))
            else:
                functions.print_pending_tasks(results)
            return

        if sub == "policy":
            results = functions.list_policy_jobs(cfg, target)
            if isinstance(results, dict) and "error" in results:
                print(json.dumps(results, indent=2))
                sys.exit(1)
            if use_json:
                print(json.dumps(results, indent=2))
            else:
                functions.print_policy_status(results)
            return

        print(f"Unknown jobs subcommand: {sub}")
        print("Usage: starsearch-cli jobs <list|pending|policy> [--json] [--all] [--filter <action>]")
        sys.exit(1)

    # ILM cluster settings (`plugins.index_state_management.*`) — facts about
    # the tick / sweep / job-interval knobs in effect on this cluster.
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "settings":
        use_json = "--json" in args
        result = functions.get_ism_settings(cfg, target)
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            functions.print_ism_settings(result)
        if isinstance(result, dict) and "error" in result:
            sys.exit(1)
        return

    # Per-managed-index baked-in tick schedule from .opendistro-ism-config.
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "schedule":
        use_json = "--json" in args
        index_filter = None
        for a in args[2:]:
            if not a.startswith("-"):
                index_filter = a
                break
        result = functions.get_ism_schedules(cfg, target, index_filter=index_filter)
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            functions.print_ism_schedules(result)
        if isinstance(result, dict) and "error" in result:
            sys.exit(1)
        return

    # ILM policy inspection / mutation (must be before generic `ilm list` / `ilm status`)
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "policy":
        if len(args) < 3:
            print("Usage:")
            print("  starsearch-cli ilm policy show <name>")
            print("  starsearch-cli ilm policy version [<index-or-pattern>]")
            print("  starsearch-cli ilm policy set-rollover <name> [--age <d>] [--size <s>] [--docs <n>] [--primary-shard-size <s>] [--state <state>]")
            print("  starsearch-cli ilm policy set-transition <name> <from-state> <to-state> [--min-size <s>] [--min-rollover-age <d>] [--min-index-age <d>] [--min-doc-count <n>] [--position first|last]")
            print("  starsearch-cli ilm policy edit-ism-template <name> [--replace-pattern <old> <new>]* [--add-pattern <p>]* [--remove-pattern <p>]* [--entry-index <n>] [--priority <n>]")
            sys.exit(1)
        sub = args[2]

        if sub == "show":
            if len(args) < 4:
                print("Usage: starsearch-cli ilm policy show <name>")
                sys.exit(1)
            result = functions.get_policy(cfg, args[3], target)
            print(json.dumps(result, indent=2))
            return

        if sub == "set-rollover":
            if len(args) < 4:
                print("Usage: starsearch-cli ilm policy set-rollover <name> [--age <d>] [--size <s>] [--docs <n>] [--primary-shard-size <s>] [--state <state>]")
                print("  Each --flag is optional; pass `none` as the value to REMOVE that condition.")
                sys.exit(1)
            policy_name = args[3]
            kwargs = {"state_name": "hot"}
            flag_map = {
                "--age": "min_index_age",
                "--size": "min_size",
                "--docs": "min_doc_count",
                "--primary-shard-size": "min_primary_shard_size",
                "--state": "state_name",
            }
            i = 4
            while i < len(args):
                if args[i] in flag_map:
                    if i + 1 >= len(args):
                        print(f"Error: {args[i]} requires a value")
                        sys.exit(1)
                    kwargs[flag_map[args[i]]] = args[i + 1]
                    i += 2
                else:
                    print(f"Error: unknown flag '{args[i]}'")
                    sys.exit(1)
            result = functions.set_ism_rollover(cfg, target, policy_name=policy_name, **kwargs)
            functions.print_set_rollover_result(result)
            if not (isinstance(result, dict) and result.get("ok")):
                sys.exit(1)
            return

        if sub == "set-transition":
            if len(args) < 6:
                print("Usage: starsearch-cli ilm policy set-transition <name> <from-state> <to-state> "
                      "[--min-size <s>] [--min-rollover-age <d>] [--min-index-age <d>] "
                      "[--min-doc-count <n>] [--position first|last]")
                print("  At least one --min-* flag is required. Pass `none` as value to drop that condition;")
                print("  if all conditions of the matched transition end up dropped, the transition is removed.")
                sys.exit(1)
            policy_name = args[3]
            from_state = args[4]
            to_state = args[5]
            conditions = {}
            position = "first"
            cond_flag_map = {
                "--min-size": "min_size",
                "--min-rollover-age": "min_rollover_age",
                "--min-index-age": "min_index_age",
                "--min-doc-count": "min_doc_count",
            }
            i = 6
            while i < len(args):
                if args[i] in cond_flag_map:
                    if i + 1 >= len(args):
                        print(f"Error: {args[i]} requires a value")
                        sys.exit(1)
                    val = args[i + 1]
                    if args[i] == "--min-doc-count" and val.lower() != "none":
                        try:
                            val = int(val)
                        except ValueError:
                            print(f"Error: --min-doc-count must be an integer or 'none'")
                            sys.exit(1)
                    conditions[cond_flag_map[args[i]]] = val
                    i += 2
                elif args[i] == "--position":
                    if i + 1 >= len(args):
                        print("Error: --position requires a value")
                        sys.exit(1)
                    position = args[i + 1]
                    if position not in ("first", "last"):
                        print("Error: --position must be 'first' or 'last'")
                        sys.exit(1)
                    i += 2
                else:
                    print(f"Error: unknown flag '{args[i]}'")
                    sys.exit(1)
            if not conditions:
                print("Error: at least one --min-* condition flag is required")
                sys.exit(1)
            result = functions.set_ism_transition(
                cfg, target,
                policy_name=policy_name,
                from_state=from_state,
                to_state=to_state,
                conditions=conditions,
                position=position,
            )
            functions.print_set_transition_result(result)
            if not (isinstance(result, dict) and result.get("ok")):
                sys.exit(1)
            return

        if sub == "edit-ism-template":
            if len(args) < 4:
                print("Usage: starsearch-cli ilm policy edit-ism-template <name> "
                      "[--replace-pattern <old> <new>]* [--add-pattern <p>]* "
                      "[--remove-pattern <p>]* [--entry-index <n>] [--priority <n>]")
                print("  Flags may repeat (except --entry-index and --priority). At least one of")
                print("  --replace-pattern / --add-pattern / --remove-pattern / --priority is required.")
                sys.exit(1)
            policy_name = args[3]
            replace_patterns = []
            add_patterns = []
            remove_patterns = []
            entry_index = 0
            priority = None
            i = 4
            while i < len(args):
                flag = args[i]
                if flag == "--replace-pattern":
                    if i + 2 >= len(args):
                        print("Error: --replace-pattern requires two values: <old> <new>")
                        sys.exit(1)
                    replace_patterns.append((args[i + 1], args[i + 2]))
                    i += 3
                elif flag == "--add-pattern":
                    if i + 1 >= len(args):
                        print("Error: --add-pattern requires a value")
                        sys.exit(1)
                    add_patterns.append(args[i + 1])
                    i += 2
                elif flag == "--remove-pattern":
                    if i + 1 >= len(args):
                        print("Error: --remove-pattern requires a value")
                        sys.exit(1)
                    remove_patterns.append(args[i + 1])
                    i += 2
                elif flag == "--entry-index":
                    if i + 1 >= len(args):
                        print("Error: --entry-index requires a value")
                        sys.exit(1)
                    try:
                        entry_index = int(args[i + 1])
                    except ValueError:
                        print("Error: --entry-index must be an integer")
                        sys.exit(1)
                    i += 2
                elif flag == "--priority":
                    if i + 1 >= len(args):
                        print("Error: --priority requires a value")
                        sys.exit(1)
                    try:
                        priority = int(args[i + 1])
                    except ValueError:
                        print("Error: --priority must be an integer")
                        sys.exit(1)
                    i += 2
                else:
                    print(f"Error: unknown flag '{flag}'")
                    sys.exit(1)
            if not (replace_patterns or add_patterns or remove_patterns or priority is not None):
                print("Error: at least one of --replace-pattern / --add-pattern / --remove-pattern / --priority is required")
                sys.exit(1)
            result = functions.edit_ism_template(
                cfg, target,
                policy_name=policy_name,
                replace_patterns=replace_patterns,
                add_patterns=add_patterns,
                remove_patterns=remove_patterns,
                entry_index=entry_index,
                priority=priority,
            )
            functions.print_edit_ism_template_result(result)
            if not (isinstance(result, dict) and result.get("ok")):
                sys.exit(1)
            return

        if sub == "version":
            use_json = "--json" in args
            include_orphans = "--include-orphans" in args
            index_filter = None
            for a in args[3:]:
                if not a.startswith("-"):
                    index_filter = a
                    break
            result = functions.get_policy_version_drift(
                cfg, target,
                index_filter=index_filter,
                include_orphans=include_orphans,
            )
            if use_json:
                print(json.dumps(result, indent=2))
            else:
                functions.print_policy_version_drift(result)
            if isinstance(result, list) and any(
                r.get("orphan") or (not r["enrolled"]) or r["drift"] for r in result
            ):
                sys.exit(2)  # signal drift/orphan to scripts (skills)
            return

        print(f"Unknown ilm policy subcommand: {sub}")
        sys.exit(1)

    # ILM change-policy (apply latest policy version, or enrol un-managed indices)
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "change-policy":
        if len(args) < 4:
            print("Usage: starsearch-cli ilm change-policy <index-or-pattern> <policy-id> [--state <state>]")
            sys.exit(1)
        pattern = args[2]
        policy_id = args[3]
        state = None
        if "--state" in args:
            idx = args.index("--state")
            if idx + 1 >= len(args):
                print("Error: --state requires a value")
                sys.exit(1)
            state = args[idx + 1]
        results = functions.change_policy_for_indices(
            cfg, target, index_patterns=[pattern], policy_id=policy_id, state=state
        )
        functions.print_change_policy_results(results)
        return

    # ILM retry (failed managed indices)
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "retry":
        if len(args) < 3:
            print("Usage: starsearch-cli ilm retry <index-or-pattern> [--state <state>]")
            sys.exit(1)
        pattern = args[2]
        state = None
        if "--state" in args:
            idx = args.index("--state")
            if idx + 1 >= len(args):
                print("Error: --state requires a value")
                sys.exit(1)
            state = args[idx + 1]
        results = functions.retry_ism_for_indices(
            cfg, target, index_patterns=[pattern], state=state
        )
        functions.print_change_policy_results(results)
        return

    # ILM rollover (manual rollover of a data stream / write alias)
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "rollover":
        if len(args) < 3:
            print("Usage: starsearch-cli ilm rollover <data-stream-or-alias>")
            sys.exit(1)
        name = args[2]
        result = functions.rollover_index(cfg, target, name=name)
        print(json.dumps(result, indent=2))
        if not result.get("ok"):
            sys.exit(1)
        return

    # Index template inspection / mutation
    if len(args) >= 2 and args[0] == "index-template":
        sub = args[1]
        if sub == "list":
            use_json = "--json" in args
            name_filter = None
            for a in args[2:]:
                if not a.startswith("-"):
                    name_filter = a
                    break
            result = functions.list_index_templates(cfg, target, name_filter=name_filter)
            if use_json:
                print(json.dumps(result, indent=2))
            else:
                functions.print_index_templates(result)
            return
        if sub == "set-policy":
            if len(args) < 4:
                print("Usage: starsearch-cli index-template set-policy <template-name> <policy-id|none>")
                print("  Use 'none' as policy-id to REMOVE the ISM policy setting.")
                sys.exit(1)
            template_name = args[2]
            policy_id = args[3]
            result = functions.set_index_template_policy(
                cfg, target, template_name=template_name, policy_id=policy_id
            )
            functions.print_set_index_template_result(result)
            if not (isinstance(result, dict) and result.get("ok")):
                sys.exit(1)
            return
        print(f"Unknown index-template subcommand: {sub}")
        sys.exit(1)

    # Component template inspection / mutation
    if len(args) >= 2 and args[0] == "component-template":
        sub = args[1]
        if sub == "list":
            use_json = "--json" in args
            name_filter = None
            for a in args[2:]:
                if not a.startswith("-"):
                    name_filter = a
                    break
            result = functions.list_component_templates(cfg, target, name_filter=name_filter)
            if use_json:
                print(json.dumps(result, indent=2))
            else:
                functions.print_component_templates(result)
            return
        if sub == "set-policy":
            if len(args) < 4:
                print("Usage: starsearch-cli component-template set-policy <template-name> <policy-id|none>")
                print("  Use 'none' as policy-id to REMOVE the ISM policy setting.")
                sys.exit(1)
            template_name = args[2]
            policy_id = args[3]
            result = functions.set_component_template_policy(
                cfg, target, template_name=template_name, policy_id=policy_id
            )
            functions.print_set_component_template_result(result)
            if not (isinstance(result, dict) and result.get("ok")):
                sys.exit(1)
            return
        print(f"Unknown component-template subcommand: {sub}")
        sys.exit(1)

    # Data stream commands
    if len(args) >= 2 and args[0] == "data-stream":
        sub = args[1]
        if sub == "list":
            use_json = "--json" in args
            name_filter = None
            for a in args[2:]:
                if not a.startswith("-"):
                    name_filter = a
                    break
            result = functions.list_data_streams(cfg, target, name_filter=name_filter)
            if use_json:
                print(json.dumps(result, indent=2))
            else:
                functions.print_data_streams(result)
            return
        print(f"Unknown data-stream subcommand: {sub}")
        sys.exit(1)

    # ILM commands
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "list":
        show_all = "--all" in args or "--all" in sys.argv
        results = functions.get_index_lifecycle_info(cfg, target, show_all)
        functions.print_table(results)
        return

    # ILM status (per-index policy execution explain)
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "status":
        use_json = "--json" in args
        failed_only = "--failed" in args
        # First non-flag positional after `status` is an optional index filter.
        index_filter = None
        for a in args[2:]:
            if not a.startswith("-"):
                index_filter = a
                break
        results = functions.get_policy_status(
            cfg, target, index_filter=index_filter, failed_only=failed_only
        )
        if isinstance(results, dict) and "error" in results:
            print(json.dumps(results, indent=2))
            sys.exit(1)
        if use_json:
            print(json.dumps(results, indent=2))
        else:
            functions.print_policy_status(results)
            if failed_only and any(r["step_status"] in ("failed", "retrying") for r in results):
                sys.exit(1)
        return

    if len(args) >= 4 and args[0] == "ilm" and args[2] == "set":
        phase_arg = args[3] if len(args) > 3 else None

        if phase_arg == "rollover":
            if len(args) < 6:
                print("Usage: starsearch-cli ilm <policy> set rollover <max_size> <max_docs>")
                print("  max_size: e.g., '50gb', '10gb'")
                print("  max_docs: e.g., '150000000' or 'none'")
                sys.exit(1)
            policy_name = args[1]
            max_size = args[4] if args[4].lower() != "none" else None
            max_docs = args[5] if args[5].lower() != "none" else None
            result = functions.set_policy_rollover(cfg, policy_name, max_size, max_docs, target)
            print(json.dumps(result, indent=2))
            return

        if phase_arg not in ["delete-after", "warm-after", "cold-after"]:
            print("Error: phase must be delete-after, warm-after, cold-after, or rollover")
            sys.exit(1)
        if len(args) < 5:
            print(f"Usage: starsearch-cli ilm <policy> set {phase_arg} <days>")
            sys.exit(1)
        policy_name = args[1]
        try:
            days = int(args[4])
        except ValueError:
            print("Error: days must be an integer")
            sys.exit(1)

        if phase_arg == "delete-after":
            result = functions.set_policy_delete_phase(cfg, policy_name, days, target)
        elif phase_arg == "warm-after":
            result = functions.set_policy_warm_phase(cfg, policy_name, days, target)
        elif phase_arg == "cold-after":
            result = functions.set_policy_cold_phase(cfg, policy_name, days, target)

        print(json.dumps(result, indent=2))
        return

    # Index commands
    if len(args) >= 3 and args[0] == "index" and args[1] == "delete":
        index_name = args[2]
        result = functions.delete_index(cfg, index_name, target)
        print(json.dumps(result, indent=2))
        return

    # Index pattern commands
    if len(args) >= 2 and args[0] == "index-pattern":
        if args[1] == "list":
            results = functions.list_index_patterns(cfg, target)
            if isinstance(results, dict) and "error" in results:
                print(json.dumps(results, indent=2))
            else:
                functions.print_saved_objects(results)
            return
        elif args[1] == "delete":
            if len(args) < 3:
                print("Usage: starsearch-cli index-pattern delete <pattern-id>")
                sys.exit(1)
            pattern_id = args[2]
            result = functions.delete_index_pattern(cfg, pattern_id, target)
            print(json.dumps(result, indent=2))
            return

    # Fallback to endpoint query
    endpoint = resolve_endpoint(args)
    query(endpoint, target)

if __name__ == "__main__":
    main()
