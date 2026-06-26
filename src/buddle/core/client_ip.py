"""Spoof-resistant client-IP resolution from ``X-Forwarded-For``.

Why this module exists
----------------------
The rate limiter keys on the client IP. ``X-Forwarded-For`` (XFF) is appended
to by each proxy *and* freely settable by the original client, so the leftmost
entry is attacker-controlled. Trusting it lets anyone rotate a fake IP per
request and defeat IP-based limits. Two robust strategies are offered; the
deployment picks one via config, and neither requires hard-coding a brittle
"this is the Nth entry" index.

Strategy A — trusted CIDRs (recommended)
    Walk the XFF chain from the RIGHT (the address the socket actually came
    from), discarding entries that fall inside ``trusted_proxy_cidrs`` (the
    private/infra ranges we control). The first address that is *not* trusted
    is the real client. This auto-adapts to 1, 2 or N proxies with no count to
    maintain — the same approach nginx ``set_real_ip_from`` / Express
    ``trust proxy`` / Rails ``config.action_dispatch.trusted_proxies`` use.
    A malicious client can spoof IPs *inside* the chain, but everything it
    injects sits to the LEFT of the genuine proxy hops, so it can never be
    mistaken for the trusted segment.

Strategy B — fixed hop count (fallback, now validated)
    If you can't enumerate proxy ranges, declare how many proxies sit in front
    of the app. We trust the rightmost ``hops`` entries and take the one to
    their left. The count is **range-checked** against the actual chain length
    so a misconfiguration degrades safely (and is logged) instead of silently
    trusting attacker input.

Selection
    ``trusted_proxy_mode`` ∈ {"socket", "cidr", "hops"}:
      * "socket" — ignore XFF entirely, use the socket peer (app directly
        exposed; the safe default).
      * "cidr"   — Strategy A using ``trusted_proxy_cidrs``.
      * "hops"   — Strategy B using ``trusted_proxy_hops``.
    ``"auto"`` resolves to "cidr" when CIDRs are configured, else "hops" when
    a positive hop count is set, else "socket".
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from functools import lru_cache

from buddle.core.logging import get_logger

log = get_logger(__name__)

_UNKNOWN = "unknown"


@lru_cache(maxsize=8)
def _parse_networks(
    cidrs: tuple[str, ...],
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse CIDR strings to network objects once (cached). Invalid entries are
    skipped with a warning so one typo can't crash request handling."""
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in cidrs:
        raw = raw.strip()
        if not raw:
            continue
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            log.warning("trusted_proxy.bad_cidr", value=raw)
    return tuple(nets)


def _is_ip(token: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a single XFF token to an address, tolerating ``ip:port`` and
    bracketed IPv6 (``[::1]:443``). Returns None if it isn't an address."""
    token = token.strip()
    if not token:
        return None
    # Bracketed IPv6 (optionally with :port)
    if token.startswith("["):
        host = token[1:].split("]", 1)[0]
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None
    # IPv4 with optional :port (a bare IPv6 has many colons → not this case)
    if token.count(":") == 1:
        host = token.rsplit(":", 1)[0]
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            pass  # fall through to try the whole token (e.g. odd inputs)
    try:
        return ipaddress.ip_address(token)
    except ValueError:
        return None


def _trusted(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
    nets: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    return any(addr in n for n in nets)


def resolve_client_ip(
    *,
    peer: str | None,
    xff: str | None,
    mode: str,
    trusted_cidrs: Sequence[str],
    hops: int,
) -> str:
    """Return the best-effort real client IP for rate limiting.

    Pure function (no Request/Settings dependency) so it is trivially testable.
    ``peer`` is the socket peer (``request.client.host``).
    """
    peer = peer or _UNKNOWN
    effective = _effective_mode(mode, trusted_cidrs, hops)

    if effective == "socket" or not xff:
        return peer

    parts = [p for p in (t.strip() for t in xff.split(",")) if p]
    if not parts:
        return peer

    if effective == "cidr":
        return _resolve_by_cidr(peer, parts, trusted_cidrs)

    # effective == "hops"
    return _resolve_by_hops(peer, parts, hops)


def _effective_mode(mode: str, trusted_cidrs: Sequence[str], hops: int) -> str:
    mode = (mode or "auto").lower()
    if mode in {"socket", "cidr", "hops"}:
        return mode
    # auto
    if trusted_cidrs:
        return "cidr"
    if hops > 0:
        return "hops"
    return "socket"


def _resolve_by_cidr(peer: str, parts: list[str], trusted_cidrs: Sequence[str]) -> str:
    """Strategy A: peel trusted hops from the right; first untrusted = client."""
    nets = _parse_networks(tuple(trusted_cidrs))
    if not nets:
        # Misconfigured (mode=cidr but no valid ranges): safest is the socket
        # peer, never an attacker-supplied XFF entry.
        log.warning("trusted_proxy.cidr_mode_without_ranges")
        return peer

    # Build the full chain right-to-left: socket peer is the true rightmost hop,
    # then XFF entries already run left(client)→right(nearest proxy).
    chain = [*parts]  # leftmost = original client claim … rightmost = last proxy
    # Start from the rightmost XFF entry and move left while entries are trusted.
    idx = len(chain) - 1
    # The socket peer is the address that connected to us; if it's trusted we
    # keep peeling into the XFF list, otherwise the peer itself is the client.
    peer_addr = _is_ip(peer)
    if peer_addr is not None and not _trusted(peer_addr, nets):
        # Direct connection from an untrusted peer → it IS the client; XFF is
        # unverifiable hearsay. Use the peer.
        return peer

    while idx >= 0:
        addr = _is_ip(chain[idx])
        if addr is None:
            # Unparseable hop — stop here; treat this token as the client.
            return chain[idx]
        if _trusted(addr, nets):
            idx -= 1
            continue
        return str(addr)  # first untrusted from the right = real client
    # Entire chain was trusted (client connected from inside infra) → leftmost.
    return str(_is_ip(chain[0]) or peer)


def _resolve_by_hops(peer: str, parts: list[str], hops: int) -> str:
    """Strategy B: trust the rightmost ``hops`` entries, take the one left of
    them. Range-checked against the actual chain length."""
    n = len(parts)
    # Clamp hops into [0, n]. If the chain is shorter than the declared hop
    # count, the header was forged or infra changed — fall back to the socket
    # peer rather than honoring a too-short, attacker-shaped chain.
    if hops >= n:
        log.warning("trusted_proxy.hops_exceed_chain", hops=hops, chain_len=n)
        return peer
    return parts[n - hops - 1]


def diagnose_proxy_chain(
    *,
    peer: str | None,
    xff: str | None,
    trusted_cidrs: Sequence[str],
) -> dict[str, object]:
    """Inspect one real request and report what the proxy chain looks like.

    Called once after startup (on the first request seen) so operators get a
    concrete, measured recommendation instead of guessing a hop count:

      * how many trusted hops sit to the right of the chain,
      * the IP that would be selected as the client under "cidr" mode,
      * the equivalent fixed-hop count, if they prefer "hops" mode.

    This turns "you must know your proxy count" into "boot the app, read one
    log line." Pure + side-effect free; the caller logs the result.
    """
    nets = _parse_networks(tuple(trusted_cidrs))
    parts = [p for p in (t.strip() for t in (xff or "").split(",")) if p]

    # Count trusted hops from the right (these are infra we control).
    trusted_from_right = 0
    for token in reversed(parts):
        addr = _is_ip(token)
        if addr is not None and _trusted(addr, nets):
            trusted_from_right += 1
        else:
            break

    selected = resolve_client_ip(
        peer=peer, xff=xff, mode="cidr", trusted_cidrs=trusted_cidrs, hops=0
    )
    peer_addr = _is_ip(peer or "")
    peer_trusted = peer_addr is not None and _trusted(peer_addr, nets)

    return {
        "socket_peer": peer or _UNKNOWN,
        "socket_peer_trusted": peer_trusted,
        "xff_present": bool(parts),
        "xff_chain_len": len(parts),
        "trusted_hops_from_right": trusted_from_right,
        "selected_client_ip_cidr_mode": selected,
        # If they switch to fixed-hop mode, this is the count that reproduces
        # the CIDR-mode selection for this observed chain.
        "equivalent_hops": trusted_from_right,
    }
