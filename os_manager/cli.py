"""osm - command line access to OpenSearch and OpenSearch Dashboards."""

import argparse
import glob
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import detectors, indices, ism, objects
from .client import GLOBAL_SCOPE, ApiError, connect, load_targets
from .output import show_json

try:
    VERSION = version("os-manager")
except PackageNotFoundError:  # running from a source tree, not installed
    VERSION = "unknown"

# Shorthands for the REST API, so `osm cat indices` reaches /_cat/indices. Any
# other unrecognised first word is passed through as a path unchanged.
RAW_ALIASES = {"cluster": "_cluster", "cat": "_cat", "nodes": "_nodes"}


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

def emit(args, data, printer):
    """Print `data` as JSON when --json was given, otherwise via `printer`."""
    if getattr(args, "json", False):
        show_json(data)
    else:
        printer(data)


def write_export(ndjson, as_json, directory):
    """Send exported objects to stdout, or to one file per object."""
    records = [json.loads(line) for line in ndjson.splitlines() if line.strip()]
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        for record in records:
            if "_index_pattern_map" in record:
                continue
            target = path / f"{record['id']}{'.json' if as_json else '.ndjson'}"
            target.write_text(json.dumps(record, indent=2 if as_json else None))
            print(f"Exported: {target}")
    elif as_json:
        show_json(records)
    else:
        print(ndjson)


def expand_files(patterns):
    """Every argument globbed, so quoted wildcards work unexpanded by the shell.

    A pattern matching nothing is kept as given, so a genuinely missing file is
    still reported as such rather than silently dropped.
    """
    paths = []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            if path not in paths:
                paths.append(path)
    return paths


# --------------------------------------------------------------------------
# Saved objects
# --------------------------------------------------------------------------

def do_object_list(client, args):
    objects.print_objects(objects.list_objects(client, args.obj_type))


def do_object_export(client, args):
    obj_type = getattr(args, "type", None) or args.obj_type
    ndjson = objects.export_objects(client, args.ids or None, obj_type)
    write_export(ndjson, args.json, args.to_file)


def do_object_import(client, args):
    paths = expand_files(args.files)
    failed = 0
    for path in paths:
        if len(paths) > 1:
            print(f"\n{path}")
        try:
            content = Path(path).read_text()
        except OSError as error:
            print(f"Error: {error}", file=sys.stderr)
            failed += 1
            continue
        failed += objects.print_import(
            objects.import_objects(client, content, args.obj_type))
    return 1 if failed else 0


def do_object_delete(client, args):
    print(objects.delete_object(client, args.id, args.obj_type))


def do_index_pattern_list(client, args):
    emit(args, objects.list_index_patterns(client), objects.print_index_patterns)


def do_workspace_list(client, args):
    emit(args, objects.list_workspaces(client), objects.print_workspaces)


def do_detector_list(client, args):
    objects.print_objects(detectors.list_detectors(client))


def do_detector_export(client, args):
    write_export(detectors.export_detectors(client, args.ids or None),
                 args.json, args.to_file)


def do_validate(client, args):
    result = objects.validate_dashboards(client, args.ids or None)
    if not args.json:
        return objects.print_validation(result)
    show_json(result)
    summary = result["summary"]
    return 1 if summary["errors"] or summary["global_issues"] else 0


# --------------------------------------------------------------------------
# ISM
# --------------------------------------------------------------------------

def do_ism_list(client, args):
    ism.print_indices(ism.list_indices(client, args.all))


def do_ism_status(client, args):
    rows = ism.policy_status(client, args.index, args.failed)
    emit(args, rows, ism.print_policy_status)
    return 1 if args.failed and rows else 0


def do_ism_settings(client, args):
    emit(args, ism.settings(client), ism.print_settings)


def do_ism_schedule(client, args):
    emit(args, ism.schedules(client, args.index), ism.print_schedules)


def do_policy_show(client, args):
    show_json(ism.get_policy(client, args.name))


def do_policy_create(client, args):
    ism.print_policy_created(ism.create_policy(
        client, args.name, args.description, args.state, args.pattern,
        args.priority))


def do_policy_version(client, args):
    rows = ism.policy_version(client, args.index, args.include_orphans)
    emit(args, rows, ism.print_policy_version)
    # Exit 2 signals "something needs re-enrolling" to scripts and skills.
    return 2 if ism.needs_attention(rows) else 0


def do_set_rollover(client, args):
    result = ism.set_rollover(
        client, args.name, args.state,
        min_index_age=args.min_index_age, min_size=args.min_size,
        min_doc_count=args.min_doc_count,
        min_primary_shard_size=args.min_primary_shard_size,
    )
    ism.print_policy_change(result, f"policy={args.name} state={args.state} rollover")


def do_set_transition(client, args):
    conditions = {
        key: getattr(args, key) for key in
        ("min_size", "min_rollover_age", "min_index_age", "min_doc_count")
        if getattr(args, key) is not None
    }
    if not conditions:
        raise ApiError("At least one --min-* condition is required")
    result = ism.set_transition(client, args.name, args.from_state, args.to_state,
                                conditions, args.position)
    ism.print_policy_change(
        result, f"policy={args.name} {args.from_state} -> {args.to_state}")


def do_edit_ism_template(client, args):
    if not (args.replace_pattern or args.add_pattern
            or args.remove_pattern or args.priority is not None):
        raise ApiError("At least one of --replace-pattern / --add-pattern / "
                       "--remove-pattern / --priority is required")
    result = ism.edit_ism_template(
        client, args.name,
        replace=args.replace_pattern or (), add=args.add_pattern or (),
        remove=args.remove_pattern or (), entry_index=args.entry_index,
        priority=args.priority,
    )
    ism.print_policy_change(result, f"policy={args.name} ism_template")


def do_change_policy(client, args):
    result = ism.change_policy(client, args.pattern, args.policy_id, args.state)
    ism.print_index_operation(result, args.pattern)


def do_retry(client, args):
    ism.print_index_operation(ism.retry(client, args.pattern, args.state), args.pattern)


def do_rollover(client, args):
    show_json(ism.rollover(client, args.name))


def do_jobs_list(client, args):
    emit(args, ism.running_tasks(client, args.all, args.filter), ism.print_running_tasks)


def do_jobs_pending(client, args):
    emit(args, ism.pending_tasks(client), ism.print_pending_tasks)


def do_jobs_policy(client, args):
    emit(args, ism.policy_jobs(client), ism.print_policy_status)


# --------------------------------------------------------------------------
# Templates, data streams, indices
# --------------------------------------------------------------------------

def do_index_template_list(client, args):
    emit(args, ism.list_index_templates(client, args.pattern), ism.print_index_templates)


def do_component_template_list(client, args):
    emit(args, ism.list_component_templates(client, args.pattern),
         ism.print_component_templates)


def do_set_template_policy(client, args):
    ism.set_template_policy(client, args.kind, args.name, args.policy_id)


def do_data_stream_list(client, args):
    emit(args, ism.list_data_streams(client, args.pattern), ism.print_data_streams)


def do_index_delete(client, args):
    print(indices.delete_index(client, args.name))


def do_field_caps(client, args):
    result = indices.field_caps(client, args.pattern, args.non_keyword,
                                args.conflicts, args.unknown)
    emit(args, result, indices.print_field_caps)


def do_pattern_refresh(client, args):
    result = indices.refresh_index_pattern(client, args.id, apply=not args.dry_run)
    emit(args, result, indices.print_refresh)


def do_target_list(client, args):
    for i, target in enumerate(load_targets()):
        default = "  (default)" if i == 0 else ""
        print(f"\n{target['name']}{default}")
        print(f"  cluster: {endpoint_url(target.get('cluster'))}")
        print(f"  dashboards: {endpoint_url(target.get('dashboards'))}")
        workspace = (target.get("dashboards") or {}).get("workspace")
        if workspace:
            print(f"  workspace: {workspace}")
        if target.get("username"):
            print(f"  username: {target['username']}")
        print(f"  verify_ssl: {target.get('verify_ssl', True)}")


def endpoint_url(endpoint):
    if not isinstance(endpoint, dict):
        return "(not configured)"
    return (f"{endpoint.get('protocol', '?')}://{endpoint.get('host', '?')}"
            f"{endpoint.get('path', '')}")


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def doc_count(value):
    """A document count, or the literal "none" to drop the condition."""
    return value if value.lower() == "none" else int(value)


def add_json(parser):
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def add_export_flags(parser, noun):
    parser.add_argument("ids", nargs="*", help=f"{noun} ids; omit for all")
    parser.add_argument("--to-file", nargs="?", const=".", metavar="DIR",
                        help="write one file per object into DIR (default .)")
    return add_json(parser)


def add_object_commands(subparsers, name, obj_type, noun, deletable=True):
    """The list/export/import/delete family shared by every saved-object type."""
    plural = noun + ("es" if noun.endswith(("ch", "s", "x")) else "s")
    group = subparsers.add_parser(name, help=f"manage {plural}").add_subparsers(
        dest="subcommand", required=True)
    group.add_parser("list", help=f"list {plural}").set_defaults(run=do_object_list)

    export = add_export_flags(group.add_parser(
        "export", help=f"export {plural} as ndjson"), noun)
    export.set_defaults(run=do_object_export)
    if obj_type is None:
        export.add_argument("--type", choices=objects.SAVED_TYPES,
                            help="export only this type")

    imports = group.add_parser("import", help=f"import {plural} from ndjson")
    imports.add_argument("files", nargs="+", metavar="FILE",
                         help="ndjson files; wildcards are expanded")
    imports.set_defaults(run=do_object_import)

    if deletable:
        delete = group.add_parser("delete", help=f"delete a {noun}")
        delete.add_argument("id")
        delete.set_defaults(run=do_object_delete)

    for parser in group.choices.values():
        parser.set_defaults(obj_type=obj_type)
    return group


def build_parser():
    parser = argparse.ArgumentParser(
        prog="osm",
        description="Manage OpenSearch clusters and OpenSearch Dashboards. "
                    "An unrecognised command is sent to the cluster as a REST "
                    "path, so `osm _cluster/health` and `osm cat indices` work.",
    )
    parser.add_argument("-t", "--target", metavar="NAME",
                        help="target from ~/.os-manager/config.json (default: the first)")
    parser.add_argument("-w", "--workspace", metavar="ID",
                        help="scope saved objects to this Dashboards workspace, "
                             "overriding the target's own")
    parser.add_argument("--global", dest="workspace", action="store_const",
                        const=GLOBAL_SCOPE,
                        help="scope saved objects globally, ignoring the "
                             "target's workspace")
    parser.add_argument("-v", "--version", action="version", version=f"osm {VERSION}")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("target", help="show configured targets").add_subparsers(
        dest="subcommand", required=True).add_parser(
        "list", help="list configured targets").set_defaults(run=do_target_list)

    workspaces = commands.add_parser(
        "workspace", help="Dashboards workspaces").add_subparsers(
        dest="subcommand", required=True)
    add_json(workspaces.add_parser(
        "list", help="list workspaces and their ids")).set_defaults(
        run=do_workspace_list)

    add_object_commands(commands, "saved-object", None, "saved object", deletable=False)
    dashboards = add_object_commands(commands, "dashboard", "dashboard", "dashboard")
    add_object_commands(commands, "visualization", "visualization", "visualization")
    add_object_commands(commands, "search", "search", "saved search")

    validate = dashboards.add_parser(
        "validate", help="check dashboards for broken references and fields")
    validate.add_argument("ids", nargs="*", help="dashboard ids; omit for all")
    add_json(validate).set_defaults(run=do_validate, obj_type="dashboard")

    detector = commands.add_parser("detector", help="anomaly detection detectors")
    detector_cmds = detector.add_subparsers(dest="subcommand", required=True)
    detector_cmds.add_parser("list", help="list detectors").set_defaults(
        run=do_detector_list)
    add_export_flags(detector_cmds.add_parser(
        "export", help="export detectors as ndjson"), "detector").set_defaults(
        run=do_detector_export)

    _add_ism_commands(commands)
    _add_index_commands(commands)

    jobs = commands.add_parser("jobs", help="what the cluster is busy with")
    jobs_cmds = jobs.add_subparsers(dest="subcommand", required=True)
    jobs_list = jobs_cmds.add_parser("list", help="running cluster tasks")
    jobs_list.add_argument("--all", action="store_true",
                           help="include monitoring and internal tasks")
    jobs_list.add_argument("--filter", metavar="ACTION",
                           help="only tasks whose action contains this text")
    add_json(jobs_list).set_defaults(run=do_jobs_list)
    add_json(jobs_cmds.add_parser(
        "pending", help="queued master-level tasks")).set_defaults(run=do_jobs_pending)
    add_json(jobs_cmds.add_parser(
        "policy", help="ISM work in flight")).set_defaults(run=do_jobs_policy)

    for kind in ("index", "component"):
        templates = commands.add_parser(f"{kind}-template", help=f"{kind} templates")
        template_cmds = templates.add_subparsers(dest="subcommand", required=True)
        listing = template_cmds.add_parser("list", help="list templates and their policy")
        listing.add_argument("pattern", nargs="?", help="name or wildcard")
        add_json(listing).set_defaults(
            run=do_index_template_list if kind == "index" else do_component_template_list)
        set_policy = template_cmds.add_parser(
            "set-policy", help="bake an ISM policy_id into the template")
        set_policy.add_argument("name")
        set_policy.add_argument("policy_id", metavar="policy-id",
                                help="policy to apply, or 'none' to remove")
        set_policy.set_defaults(run=do_set_template_policy, kind=kind)

    streams = commands.add_parser("data-stream", help="data streams")
    stream_list = streams.add_subparsers(dest="subcommand", required=True).add_parser(
        "list", help="list data streams with their write index")
    stream_list.add_argument("pattern", nargs="?", help="name or wildcard")
    add_json(stream_list).set_defaults(run=do_data_stream_list)

    # Anything not named here is treated as a REST path, not a parse error.
    parser.command_names = set(commands.choices)
    return parser


def _add_ism_commands(commands):
    ism_cmds = commands.add_parser(
        "ism", help="index state management").add_subparsers(
        dest="subcommand", required=True)

    listing = ism_cmds.add_parser("list", help="policy and state per index")
    listing.add_argument("--all", action="store_true", help="include unmanaged indices")
    listing.set_defaults(run=do_ism_list)

    status = ism_cmds.add_parser("status", help="how each policy is executing")
    status.add_argument("index", nargs="?", help="index name or wildcard")
    status.add_argument("--failed", action="store_true",
                        help="only failed or retrying steps; exits 1 if any")
    add_json(status).set_defaults(run=do_ism_status)

    add_json(ism_cmds.add_parser(
        "settings", help="effective plugins.index_state_management.* settings")
    ).set_defaults(run=do_ism_settings)

    schedule = ism_cmds.add_parser(
        "schedule", help="per-index tick interval baked in at enrolment")
    schedule.add_argument("index", nargs="?", help="index name or wildcard")
    add_json(schedule).set_defaults(run=do_ism_schedule)

    change = ism_cmds.add_parser(
        "change-policy", help="enrol indices on the current version of a policy")
    change.add_argument("pattern", help="index name or wildcard")
    change.add_argument("policy_id", metavar="policy-id")
    change.add_argument("--state", help="state to start in")
    change.set_defaults(run=do_change_policy)

    retry = ism_cmds.add_parser("retry", help="retry a failed ISM step")
    retry.add_argument("pattern", help="index name or wildcard")
    retry.add_argument("--state", help="state to retry from")
    retry.set_defaults(run=do_retry)

    rollover = ism_cmds.add_parser(
        "rollover", help="roll over a data stream or write alias")
    rollover.add_argument("name")
    rollover.set_defaults(run=do_rollover)

    policy = ism_cmds.add_parser("policy", help="inspect and edit policies")
    policy_cmds = policy.add_subparsers(dest="policy_command", required=True)

    show = policy_cmds.add_parser("show", help="print the full policy")
    show.add_argument("name")
    show.set_defaults(run=do_policy_show)

    create = policy_cmds.add_parser(
        "create", help="create a policy that manages indices without acting",
        epilog="The policy has one state with no actions and no transitions, "
               "so enrolled indices are managed but never modified or deleted.")
    create.add_argument("name")
    create.add_argument("--description")
    create.add_argument("--state", default="keep",
                        help="name of the single state (default: keep)")
    create.add_argument("--pattern", action="append", default=[], metavar="PATTERN",
                        help="index pattern the policy claims; repeatable")
    create.add_argument("--priority", type=int, default=100,
                        help="ism_template priority (default: 100)")
    create.set_defaults(run=do_policy_create)

    drift = policy_cmds.add_parser(
        "version", help="per-index policy version against the current one")
    drift.add_argument("index", nargs="?", help="index name or wildcard")
    drift.add_argument("--include-orphans", action="store_true",
                       help="also list indices with no policy at all")
    add_json(drift).set_defaults(run=do_policy_version)

    rollover_edit = policy_cmds.add_parser(
        "set-rollover", help="edit a state's rollover conditions",
        epilog="Conditions merge into the existing ones; pass none to drop one.")
    rollover_edit.add_argument("name")
    rollover_edit.add_argument("--age", dest="min_index_age", metavar="AGE")
    rollover_edit.add_argument("--size", dest="min_size", metavar="SIZE")
    rollover_edit.add_argument("--docs", dest="min_doc_count", type=doc_count, metavar="N")
    rollover_edit.add_argument("--primary-shard-size", dest="min_primary_shard_size",
                               metavar="SIZE")
    rollover_edit.add_argument("--state", default="hot", help="state to edit (default: hot)")
    rollover_edit.set_defaults(run=do_set_rollover)

    transition = policy_cmds.add_parser(
        "set-transition", help="upsert a transition between two states",
        epilog="At least one condition is required; pass none to drop one. "
               "Dropping every condition removes the transition.")
    transition.add_argument("name")
    transition.add_argument("from_state", metavar="from-state")
    transition.add_argument("to_state", metavar="to-state")
    transition.add_argument("--min-size", metavar="SIZE")
    transition.add_argument("--min-rollover-age", metavar="AGE")
    transition.add_argument("--min-index-age", metavar="AGE")
    transition.add_argument("--min-doc-count", type=doc_count, metavar="N")
    transition.add_argument("--position", choices=("first", "last"), default="first",
                            help="where to insert a new transition (default: first)")
    transition.set_defaults(run=do_set_transition)

    template = policy_cmds.add_parser(
        "edit-ism-template", help="edit which indices the policy claims")
    template.add_argument("name")
    template.add_argument("--replace-pattern", nargs=2, action="append",
                          metavar=("OLD", "NEW"))
    template.add_argument("--add-pattern", action="append", metavar="PATTERN")
    template.add_argument("--remove-pattern", action="append", metavar="PATTERN")
    template.add_argument("--entry-index", type=int, default=0,
                          help="which ism_template entry to add to (default: 0)")
    template.add_argument("--priority", type=int)
    template.set_defaults(run=do_edit_ism_template)


def _add_index_commands(commands):
    index_cmds = commands.add_parser("index", help="indices").add_subparsers(
        dest="subcommand", required=True)
    delete = index_cmds.add_parser("delete", help="delete an index")
    delete.add_argument("name")
    delete.set_defaults(run=do_index_delete)

    caps = index_cmds.add_parser(
        "field-caps", help="field types across a pattern, as Dashboards sees them")
    caps.add_argument("pattern")
    caps.add_argument("--non-keyword", action="store_true", help="hide string fields")
    caps.add_argument("--conflicts", action="store_true",
                      help="only fields mapped as more than one type")
    caps.add_argument("--unknown", action="store_true",
                      help="only fields Dashboards renders as '?'")
    add_json(caps).set_defaults(run=do_field_caps)

    pattern_cmds = commands.add_parser(
        "index-pattern", help="index patterns").add_subparsers(
        dest="subcommand", required=True)
    add_json(pattern_cmds.add_parser("list", help="list index patterns")).set_defaults(
        run=do_index_pattern_list, obj_type="index-pattern")
    delete_pattern = pattern_cmds.add_parser("delete", help="delete an index pattern")
    delete_pattern.add_argument("id")
    delete_pattern.set_defaults(run=do_object_delete, obj_type="index-pattern")
    refresh = pattern_cmds.add_parser(
        "refresh", help="rebuild the cached field list from the live mapping")
    refresh.add_argument("id")
    refresh.add_argument("--dry-run", action="store_true",
                         help="report the diff without writing")
    add_json(refresh).set_defaults(run=do_pattern_refresh)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def raw_query(client, tokens, announce):
    """Send an unrecognised command to the cluster as a REST path."""
    head, *rest = tokens
    path = "/".join([RAW_ALIASES.get(head, head), *rest])
    if announce:
        print(f"-> {client.name}")
    response = client.request("GET", path)
    try:
        show_json(response.json())
    except ValueError:
        print(response.text)
    return 0 if response.ok else 1


def split_global_flags(parser, argv):
    """Consume leading -t/-w/--global, which also apply to raw REST paths."""
    target, workspace = None, None
    while argv:
        if argv[0] in ("-t", "--target"):
            if len(argv) < 2:
                parser.error("-t/--target requires a target name")
            target, argv = argv[1], argv[2:]
        elif argv[0] in ("-w", "--workspace"):
            if len(argv) < 2:
                parser.error("-w/--workspace requires a workspace id")
            workspace, argv = argv[1], argv[2:]
        elif argv[0] == "--global":
            workspace, argv = GLOBAL_SCOPE, argv[1:]
        else:
            break
    return target, workspace, argv


def main():
    parser = build_parser()
    target, workspace, argv = split_global_flags(parser, sys.argv[1:])

    if not argv:
        parser.print_help()
        return 1

    try:
        if argv[0].startswith("-") or argv[0] in parser.command_names:
            args = parser.parse_args(argv)
            if not hasattr(args, "run"):
                parser.print_help()
                return 1
            client = connect(args.target or target, args.workspace or workspace)
            return args.run(client, args) or 0
        return raw_query(connect(target, workspace), argv, announce=target is None)
    except ApiError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
