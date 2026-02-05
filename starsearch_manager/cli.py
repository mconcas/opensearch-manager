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
            elif args[i] == "--json":
                i += 1
            else:
                filtered_args.append(args[i])
                i += 1

        obj_ids = filtered_args if filtered_args else None
        result = functions.export_saved_objects(cfg, target, obj_ids, obj_type=obj_type)
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
        print("  starsearch-cli saved-object export [id1 id2 ...] [--json] - Export all saved objects")
        print("  starsearch-cli saved-object import <file.ndjson>        - Import saved objects from ndjson")
        print("")
        print("  starsearch-cli dashboard list                           - List all dashboards")
        print("  starsearch-cli dashboard export [id1 id2 ...] [--json]  - Export dashboards to ndjson")
        print("  starsearch-cli dashboard import <file.ndjson>           - Import dashboards from ndjson")
        print("  starsearch-cli dashboard delete <id>                    - Delete a dashboard")
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
        print("\nOther Commands:")
        print("  starsearch-cli ilm info [--all]                         - Show ILM policy info for indices")
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

    # ILM commands
    if len(args) >= 2 and args[0] == "ilm" and args[1] == "info":
        show_all = "--all" in args or "--all" in sys.argv
        results = functions.get_index_lifecycle_info(cfg, target, show_all)
        functions.print_table(results)
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
