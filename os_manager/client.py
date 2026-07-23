"""Connection to an OpenSearch cluster and its Dashboards instance."""

import json
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG_PATH = Path.home() / ".os-manager" / "config.json"

# Stands in for a workspace id to mean "the global scope", so `--global` can
# override a workspace the target configures by default.
GLOBAL_SCOPE = "__global__"


class ApiError(Exception):
    """A failure talking to the cluster or to Dashboards. Caught in main()."""


def load_targets():
    """Configured targets, newest schema only."""
    if not CONFIG_PATH.exists():
        raise ApiError(f"No configuration file at {CONFIG_PATH}")
    with open(CONFIG_PATH) as handle:
        config = json.load(handle)
    targets = config.get("targets") or []
    if not targets:
        if config.get("servers"):
            raise ApiError(
                f"{CONFIG_PATH} still uses the flat 'servers' format. A target "
                f"now bundles a 'cluster' and a 'dashboards' endpoint; see the "
                f"README.")
        raise ApiError(f"No targets configured in {CONFIG_PATH}")
    return targets


def connect(target=None, workspace=None):
    """Client for the named target, or for the first configured one."""
    targets = load_targets()
    if not target:
        return Client(targets[0], workspace)
    for candidate in targets:
        if candidate["name"] == target:
            return Client(candidate, workspace)
    known = ", ".join(candidate["name"] for candidate in targets)
    raise ApiError(f"Unknown target '{target}'. Configured targets: {known}")


def _url(endpoint):
    """`protocol://host` plus the optional reverse-proxy path prefix."""
    path = (endpoint.get("path") or "").strip("/")
    base = f"{endpoint['protocol']}://{endpoint['host']}"
    return f"{base}/{path}" if path else base


def _resolve_workspace(dashboards, workspace):
    """`-w` wins, `--global` forces the global scope, else the target's default."""
    if workspace == GLOBAL_SCOPE:
        return None
    if workspace:
        return workspace
    return dashboards.get("workspace") if isinstance(dashboards, dict) else None


class Client:
    """HTTP access to one target.

    A target names two endpoints, sharing its credentials between them: the
    OpenSearch REST API under `cluster`, and Dashboards under `dashboards`.
    Either may be left out, and a request to a missing one fails with a clear
    error. Saved objects live behind the Dashboards saved-objects API when that
    endpoint is configured and in the cluster's own `.kibana` index when it is
    not - `use_osd_api` picks between the two everywhere saved objects are read
    or written. Once a workspace is resolved, saved-object paths are prefixed
    with `/w/<id>` so they are scoped to it rather than to the global scope.
    """

    def __init__(self, target, workspace=None):
        cluster, dashboards = target.get("cluster"), target.get("dashboards")
        self.name = target["name"]
        self.cluster_url = _url(cluster) if isinstance(cluster, dict) else None
        self.osd_url = _url(dashboards) if isinstance(dashboards, dict) else None
        self.use_osd_api = self.osd_url is not None
        self.workspace = _resolve_workspace(dashboards, workspace)
        username, password = target.get("username"), target.get("password")
        self.auth = (username, password) if username and password else None
        self.verify = target.get("verify_ssl", True)

    def base_url(self, osd=False, scoped=True):
        """Base URL for one of the two endpoints, workspace-scoped when asked."""
        url = self.osd_url if osd else self.cluster_url
        if url is None:
            kind = "dashboards" if osd else "cluster"
            raise ApiError(f"Target '{self.name}' has no '{kind}' endpoint "
                           f"configured in {CONFIG_PATH}")
        if osd and scoped and self.workspace:
            return f"{url}/w/{self.workspace}"
        return url

    def request(self, method, path, osd=False, scoped=True, **kwargs):
        """Raw response, for callers that care about the status code."""
        base = self.base_url(osd, scoped)
        if osd and method != "GET":
            kwargs.setdefault("headers", {})["osd-xsrf"] = "true"
        return requests.request(
            method, f"{base}/{path.lstrip('/')}",
            auth=self.auth, verify=self.verify, **kwargs,
        )

    def fetch(self, path, method="GET", osd=False, scoped=True, **kwargs):
        """Response body, parsed as JSON. Raises ApiError on any non-2xx."""
        resp = self.request(method, path, osd=osd, scoped=scoped, **kwargs)
        if not resp.ok:
            raise ApiError(
                f"{method} {path} -> HTTP {resp.status_code}: {resp.text.strip()}"
            )
        try:
            return resp.json()
        except ValueError:
            return resp.text
