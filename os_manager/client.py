"""Connection to an OpenSearch cluster and its Dashboards instance."""

import json
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG_PATH = Path.home() / ".os-manager" / "config.json"


class ApiError(Exception):
    """A failure talking to the cluster or to Dashboards. Caught in main()."""


def load_servers():
    if not CONFIG_PATH.exists():
        raise ApiError(f"No configuration file at {CONFIG_PATH}")
    with open(CONFIG_PATH) as handle:
        servers = json.load(handle).get("servers") or []
    if not servers:
        raise ApiError(f"No servers configured in {CONFIG_PATH}")
    return servers


def connect(target=None):
    """Client for the named target, or for the first configured server."""
    servers = load_servers()
    if not target:
        return Client(servers[0])
    for server in servers:
        if server["name"] == target:
            return Client(server)
    known = ", ".join(server["name"] for server in servers)
    raise ApiError(f"Unknown target '{target}'. Configured targets: {known}")


def _url(protocol, host, path):
    path = (path or "").strip("/")
    return f"{protocol}://{host}/{path}" if path else f"{protocol}://{host}"


class Client:
    """HTTP access to one server.

    `cluster_url` reaches the OpenSearch REST API. Saved objects live either
    behind the Dashboards saved-objects API (when `base_path` is configured) or,
    when it is not, in the cluster's own `.kibana` index - `use_osd_api` picks
    between the two everywhere saved objects are read or written.
    """

    def __init__(self, server):
        protocol, host = server["protocol"], server["host"]
        self.name = server["name"]
        self.cluster_url = _url(protocol, host, server.get("cluster_path"))
        self.osd_url = _url(protocol, host, server.get("base_path"))
        self.use_osd_api = bool(server.get("base_path"))
        username, password = server.get("username"), server.get("password")
        self.auth = (username, password) if username and password else None
        self.verify = server.get("verify_ssl", True)

    def request(self, method, path, osd=False, **kwargs):
        """Raw response, for callers that care about the status code."""
        base = self.osd_url if osd else self.cluster_url
        if osd and method != "GET":
            kwargs.setdefault("headers", {})["osd-xsrf"] = "true"
        return requests.request(
            method, f"{base}/{path.lstrip('/')}",
            auth=self.auth, verify=self.verify, **kwargs,
        )

    def fetch(self, path, method="GET", osd=False, **kwargs):
        """Response body, parsed as JSON. Raises ApiError on any non-2xx."""
        resp = self.request(method, path, osd=osd, **kwargs)
        if not resp.ok:
            raise ApiError(
                f"{method} {path} -> HTTP {resp.status_code}: {resp.text.strip()}"
            )
        try:
            return resp.json()
        except ValueError:
            return resp.text
