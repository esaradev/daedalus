"""Protection #1: egress. Default-deny allowlist that mirrors NemoClaw.

NemoClaw blocks who the sandbox can talk to: every (host, port) must be on the
allowlist or the request is denied. In standalone mode daedalus enforces the
same shape, and can emit a NemoClaw-compatible policy.yaml so the real sandbox
enforces it for real.

This is a separate concern from money. It answers "is this host allowed to be
contacted at all", not "can we afford it".
"""

from . import config

# The only hosts daedalus legitimately reaches. A spend to any vendor whose
# endpoint is not here is blocked as an egress violation, before money math runs.
DEFAULT_ALLOW = {
    ("api.stripe.com", 443),
    ("openrouter.ai", 443),
}


class Egress:
    def __init__(self, allowed=None):
        self.allowed = set(allowed) if allowed is not None else set(DEFAULT_ALLOW)

    def allow(self, host, port=443):
        self.allowed.add((host, int(port)))

    def check(self, host, port=443):
        ok = (host, int(port)) in self.allowed
        if ok:
            return True, f"{host}:{port} on allowlist"
        return False, f"egress denied: {host}:{port} is not on the allowlist"

    def policy_yaml(self):
        """Emit a NemoClaw network policy allowlisting exactly these endpoints.

        Shape verified against NemoClaw network-policy docs: a named preset
        (lowercase RFC-1123 label) with a network section of host/port endpoint
        groups; default-deny is implicit, only listed endpoints are reachable.
        """
        lines = [
            f"# NemoClaw network policy for {config.PROJECT_NAME}",
            "# default-deny: only the endpoints listed below are reachable.",
            "preset:",
            f"  name: {config.PROJECT_NAME}",
            "  network:",
        ]
        for host, port in sorted(self.allowed):
            lines += [
                "    - endpoint:",
                f"        host: {host}",
                f"        port: {port}",
                "        protocol: https",
            ]
        return "\n".join(lines) + "\n"
