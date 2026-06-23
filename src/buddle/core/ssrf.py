"""SSRF guard for admin-supplied outbound URLs (persona/ethics/embedding
backends register endpoint URLs).

Threat: an admin account (or anything that compromises it) could register a
backend endpoint pointing at internal infrastructure or a cloud metadata
service, turning buddle's server into an SSRF pivot. Even though registration
is admin-only, defense-in-depth says we validate.

Approach (per OWASP SSRF guidance + pydantic-ai's _ssrf design):
  1. Scheme allowlist: only http/https (blocks file://, gopher://, dict://…).
  2. Resolve the hostname to its actual IPs and check EVERY resolved address
     against blocked ranges — validating the resolved IP, not the URL string,
     is the only reliable defense (prevents DNS-name tricks).
  3. Always block cloud metadata + loopback + link-local, regardless of config.
  4. Private ranges (RFC1918) are blocked by default but can be ALLOWLISTED
     via settings for legitimate same-cluster backends (e.g. http://vllm:8000)
     — opt-in, because most buddle deployments run the model server inside the
     same private network.

This validates at registration time. A fully hardened deployment should ALSO
use an egress proxy / network policy (the allowed-domains note in the network
config) so a bypass at the app layer is still contained.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Sequence
from urllib.parse import urlparse

from buddle.config import get_settings
from buddle.core.exceptions import ValidationError

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Always-blocked networks (never reachable via a registered backend), even if
# private ranges are allowlisted. Cloud metadata + loopback + link-local.
_ALWAYS_BLOCKED = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (AWS/GCP metadata 169.254.169.254)
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba metadata
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS IPv6 metadata
]

# Private/reserved ranges blocked by default; allowlistable via config.
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique-local
]


class SSRFValidationError(ValidationError):
    """Raised when a URL fails SSRF validation."""


def _is_in(networks: Sequence[_IPNetwork], ip: _IPAddress) -> bool:
    return any(ip in net for net in networks)


def _resolve_ips(host: str) -> list[_IPAddress]:
    """Resolve a hostname to all of its IP addresses. Raises on failure."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SSRFValidationError(f"Cannot resolve host: {host}") from e
    addrs: list[_IPAddress] = []
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            addrs.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue
    if not addrs:
        raise SSRFValidationError(f"No usable address for host: {host}")
    return addrs


def validate_outbound_url(url: str, *, allow_private: bool | None = None) -> None:
    """Validate that a URL is safe for the server to call.

    Raises SSRFValidationError on any disallowed scheme, unresolvable host, or
    a resolved IP that falls in a blocked range. `allow_private` overrides the
    configured default (settings.allow_private_backend_hosts).
    """
    settings = get_settings()
    if allow_private is None:
        allow_private = getattr(settings, "allow_private_backend_hosts", False)

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SSRFValidationError(f"URL scheme '{parsed.scheme}' is not allowed (http/https only).")
    host = parsed.hostname
    if not host:
        raise SSRFValidationError("URL has no host.")

    for ip in _resolve_ips(host):
        # Cloud metadata / loopback / link-local: ALWAYS blocked.
        if _is_in(_ALWAYS_BLOCKED, ip) or ip.is_loopback or ip.is_link_local:
            raise SSRFValidationError(f"URL resolves to a blocked address ({ip}); refused.")
        # Private ranges: blocked unless explicitly allowed.
        if not allow_private and (_is_in(_PRIVATE_NETS, ip) or ip.is_private):
            raise SSRFValidationError(
                f"URL resolves to a private address ({ip}). "
                "Set allow_private_backend_hosts=true to permit same-network backends."
            )
