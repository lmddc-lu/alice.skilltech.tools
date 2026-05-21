"""SSRF-safe URL validation and connection pinning for Moodle outbound HTTP.

Vendored verbatim into the worker because the API and worker are
separate Python packages and can't import each other.
api/app/tests/services/test_url_validation_contract.py pins the two
copies and fails CI on drift.

Resolves the hostname, rejects private/loopback/reserved IPs unless
allowlisted, and returns a ValidatedUrl carrying the resolved IP so
callers can pin subsequent requests and close the TOCTOU window
against DNS rebind.

Allowlist env vars:

- MOODLE_ALLOWED_DOMAINS: comma-separated hostnames whose DNS may resolve
  to private IPs. Hostnames only.
- MOODLE_ALLOWED_NETWORKS: comma-separated CIDRs. Literal-IP URLs are
  only accepted when the IP falls in one of these networks. The same
  list also unblocks hostnames that resolve to those IPs.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)


class UrlValidationError(ValueError):
    """Raised when a URL fails SSRF validation."""


@dataclass(frozen=True)
class ValidatedUrl:
    """Pass to make_pinned_session to lock the TCP connect to the validated IP."""

    original_url: str
    scheme: str
    hostname: str
    port: int
    resolved_ip: str
    is_literal_ip: bool


def _parse_allowlists() -> tuple[set[str], list[ipaddress._BaseNetwork]]:
    """Parse the allowlist env vars. Invalid entries are logged and dropped."""
    domains_raw = os.environ.get("MOODLE_ALLOWED_DOMAINS", "")
    domains = {d.strip().lower() for d in domains_raw.split(",") if d.strip()}

    networks_raw = os.environ.get("MOODLE_ALLOWED_NETWORKS", "")
    networks: list[ipaddress._BaseNetwork] = []
    for entry in (n.strip() for n in networks_raw.split(",")):
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid MOODLE_ALLOWED_NETWORKS entry: %r", entry)
    return domains, networks


def get_effective_allowlists() -> dict[str, Any]:
    """Return the parsed allowlists for startup logging."""
    domains, networks = _parse_allowlists()
    return {
        "MOODLE_ALLOWED_DOMAINS": sorted(domains),
        "MOODLE_ALLOWED_NETWORKS": [str(n) for n in networks],
    }


def log_effective_allowlists() -> None:
    """Log the parsed allowlists. Safe to call at startup."""
    effective = get_effective_allowlists()
    logger.info(
        "Moodle SSRF allowlists: domains=%s networks=%s",
        effective["MOODLE_ALLOWED_DOMAINS"],
        effective["MOODLE_ALLOWED_NETWORKS"],
    )


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """IPs that must never be reachable without an explicit allowlist."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_reserved
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_moodle_url(
    url: str, *, allow_private_networks: bool = False
) -> ValidatedUrl:
    """Validate a Moodle URL and resolve it once for pinning.

    allow_private_networks is the per-caller capability gate. Env-var
    allowlists describe what internal destinations the deployment
    exposes; this flag controls who may reach them. Non-admin requests
    pass False and can only reach public IPs regardless of allowlists.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UrlValidationError(f"Invalid URL scheme: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise UrlValidationError("URL has no hostname")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if allow_private_networks:
        domains, networks = _parse_allowlists()
    else:
        domains, networks = set(), []

    # literal-IP URLs require explicit MOODLE_ALLOWED_NETWORKS; never silently accepted
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if any(literal_ip in net for net in networks):
            return ValidatedUrl(
                original_url=url,
                scheme=parsed.scheme,
                hostname=hostname,
                port=port,
                resolved_ip=str(literal_ip),
                is_literal_ip=True,
            )
        if not allow_private_networks:
            raise UrlValidationError(
                f"URL uses a literal IP ({literal_ip}). Reaching internal "
                "networks requires admin privileges."
            )
        raise UrlValidationError(
            f"URL uses a literal IP ({literal_ip}) which is not in any "
            "MOODLE_ALLOWED_NETWORKS entry. Set MOODLE_ALLOWED_NETWORKS "
            "to a comma-separated CIDR list to opt in."
        )

    try:
        resolved = socket.getaddrinfo(
            hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror as e:
        raise UrlValidationError(f"Cannot resolve hostname: {hostname} ({e})")

    if not resolved:
        raise UrlValidationError(f"Cannot resolve hostname: {hostname}")

    # validate every answer, not just the pinned one. mixed public/private
    # answers must be rejected unless the hostname is allowlisted.
    pinned_addr: str | None = None
    hostname_allowed = hostname.lower() in domains

    for _family, _, _, _, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        ip_in_networks = any(ip in net for net in networks)
        if _is_blocked_ip(ip) and not (hostname_allowed or ip_in_networks):
            if not allow_private_networks:
                raise UrlValidationError(
                    f"URL resolves to a private/reserved IP ({ip}). "
                    "Reaching internal networks requires admin privileges."
                )
            raise UrlValidationError(
                f"URL resolves to a private/reserved IP ({ip}). "
                "If this is intentional, add the hostname to "
                "MOODLE_ALLOWED_DOMAINS or the IP's network to "
                "MOODLE_ALLOWED_NETWORKS."
            )
        if pinned_addr is None:
            pinned_addr = sockaddr[0]

    assert pinned_addr is not None
    return ValidatedUrl(
        original_url=url,
        scheme=parsed.scheme,
        hostname=hostname,
        port=port,
        resolved_ip=pinned_addr,
        is_literal_ip=False,
    )


def make_pinned_session(
    validated: ValidatedUrl, *, verify: bool = True
) -> requests.Session:
    """Build a requests.Session that always connects to validated.resolved_ip.

    HTTP: rewrite the URL host to the validated IP and keep the original
    Host header. Eliminates the TOCTOU window entirely.

    HTTPS: re-resolve at send-time and reject if the result no longer
    matches the validated IP. Can't rewrite the URL without breaking
    SNI/cert checks, so this narrows the TOCTOU window to the
    microseconds between the send-time check and the connect() syscall.

    Only requests targeting validated.hostname get pinned. Cross-host
    redirects fall through and must be re-validated by the caller.
    """

    class _PinnedAdapter(requests.adapters.HTTPAdapter):
        def __init__(self, hostname: str, ip: str, scheme: str, **kw: Any) -> None:
            self._pinned_hostname = hostname.lower()
            self._pinned_ip = ip
            self._pinned_scheme = scheme
            super().__init__(**kw)

        def send(self, request: requests.PreparedRequest, **kwargs: Any) -> Any:  # type: ignore[override]
            assert request.url is not None
            parsed = urlparse(request.url)
            if not parsed.hostname or parsed.hostname.lower() != self._pinned_hostname:
                # cross-host redirect or unrelated URL; caller revalidates
                return super().send(request, **kwargs)

            scheme = parsed.scheme or self._pinned_scheme

            if scheme == "http":
                ip_for_url = (
                    f"[{self._pinned_ip}]"
                    if ":" in self._pinned_ip
                    else self._pinned_ip
                )
                netloc = f"{ip_for_url}:{parsed.port}" if parsed.port else ip_for_url
                request.url = urlunparse(parsed._replace(netloc=netloc))
                request.headers["Host"] = parsed.netloc
                return super().send(request, **kwargs)

            # HTTPS: keep the URL hostname for SNI/cert checks; re-resolve
            # and abort if DNS now points somewhere different
            try:
                resolved = socket.getaddrinfo(
                    self._pinned_hostname,
                    parsed.port or 443,
                    socket.AF_UNSPEC,
                    socket.SOCK_STREAM,
                )
            except socket.gaierror as e:
                raise UrlValidationError(
                    f"Resend resolution failed for {self._pinned_hostname}: {e}"
                )
            current_ips = {sa[0] for *_, sa in resolved}
            if self._pinned_ip not in current_ips:
                raise UrlValidationError(
                    f"DNS for {self._pinned_hostname} no longer includes the "
                    f"validated IP {self._pinned_ip} (now {sorted(current_ips)}); "
                    "refusing to send to avoid SSRF via DNS rebind."
                )
            return super().send(request, **kwargs)

    session = requests.Session()
    session.verify = verify
    adapter = _PinnedAdapter(
        validated.hostname, validated.resolved_ip, validated.scheme
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
