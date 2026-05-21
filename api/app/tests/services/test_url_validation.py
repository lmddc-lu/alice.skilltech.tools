"""Tests for SSRF URL validation and pinned-session behaviour."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from app.services.url_validation import (
    UrlValidationError,
    _parse_allowlists,
    make_pinned_session,
    validate_moodle_url,
)


def _gai(*addrs: str) -> list:
    """Build a getaddrinfo-shaped list with the given IPv4 addresses."""
    return [(None, None, None, None, (addr, 0)) for addr in addrs]


def _ok_response(request: requests.PreparedRequest) -> requests.Response:
    """Real Response so requests.Session can iterate it (no redirects)."""
    r = requests.Response()
    r.status_code = 200
    r.url = request.url
    r.request = request
    r._content = b""
    return r


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MOODLE_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("MOODLE_ALLOWED_NETWORKS", raising=False)


class TestParseAllowlists:
    def test_empty(self):
        domains, networks = _parse_allowlists()
        assert domains == set()
        assert networks == []

    def test_domains_lowercased_and_split(self, monkeypatch):
        monkeypatch.setenv("MOODLE_ALLOWED_DOMAINS", "Foo.Example , Bar.Test ")
        domains, _ = _parse_allowlists()
        assert domains == {"foo.example", "bar.test"}

    def test_networks_parse_cidrs(self, monkeypatch):
        monkeypatch.setenv("MOODLE_ALLOWED_NETWORKS", "10.0.0.0/8, 192.168.1.0/24")
        _, networks = _parse_allowlists()
        assert [str(n) for n in networks] == ["10.0.0.0/8", "192.168.1.0/24"]

    def test_invalid_network_dropped(self, monkeypatch, caplog):
        monkeypatch.setenv("MOODLE_ALLOWED_NETWORKS", "10.0.0.0/8, not-a-cidr")
        _, networks = _parse_allowlists()
        assert [str(n) for n in networks] == ["10.0.0.0/8"]


class TestValidateMoodleUrl:
    def test_rejects_invalid_scheme(self):
        with pytest.raises(UrlValidationError, match="scheme"):
            validate_moodle_url("ftp://example.com")

    def test_rejects_missing_hostname(self):
        with pytest.raises(UrlValidationError, match="hostname"):
            validate_moodle_url("http:///path")

    def test_public_hostname_passes(self):
        # 93.184.216.34 is example.com (public, never blocked)
        with patch("socket.getaddrinfo", return_value=_gai("93.184.216.34")):
            v = validate_moodle_url("https://example.com")
        assert v.hostname == "example.com"
        assert v.resolved_ip == "93.184.216.34"
        assert v.scheme == "https"
        assert v.port == 443
        assert v.is_literal_ip is False

    def test_private_resolution_fails_by_default(self):
        with patch("socket.getaddrinfo", return_value=_gai("10.0.0.5")):
            with pytest.raises(UrlValidationError, match="private/reserved"):
                validate_moodle_url("http://internal.test")

    def test_private_resolution_passes_when_hostname_allowed(self, monkeypatch):
        monkeypatch.setenv("MOODLE_ALLOWED_DOMAINS", "internal.test")
        with patch("socket.getaddrinfo", return_value=_gai("10.0.0.5")):
            v = validate_moodle_url("http://internal.test", allow_private_networks=True)
        assert v.resolved_ip == "10.0.0.5"

    def test_private_resolution_passes_when_network_allowed(self, monkeypatch):
        monkeypatch.setenv("MOODLE_ALLOWED_NETWORKS", "10.0.0.0/8")
        with patch("socket.getaddrinfo", return_value=_gai("10.0.0.5")):
            v = validate_moodle_url(
                "http://moodle.example", allow_private_networks=True
            )
        assert v.resolved_ip == "10.0.0.5"

    def test_private_resolution_ignores_allowlist_for_non_admin(self, monkeypatch):
        """Non-admin caller can't reach private IPs even with env allowlist;
        the role gate overrides the network-level opt-in."""
        monkeypatch.setenv("MOODLE_ALLOWED_NETWORKS", "10.0.0.0/8")
        monkeypatch.setenv("MOODLE_ALLOWED_DOMAINS", "moodle.example")
        with patch("socket.getaddrinfo", return_value=_gai("10.0.0.5")):
            with pytest.raises(UrlValidationError, match="admin privileges"):
                validate_moodle_url("http://moodle.example")

    def test_mixed_resolution_fails_without_allowlist(self):
        # DNS rebind or round-robin: one public + one private answer
        with patch(
            "socket.getaddrinfo", return_value=_gai("93.184.216.34", "10.0.0.5")
        ):
            with pytest.raises(UrlValidationError, match="private/reserved"):
                validate_moodle_url("http://example.com")

    def test_loopback_blocked(self):
        with patch("socket.getaddrinfo", return_value=_gai("127.0.0.1")):
            with pytest.raises(UrlValidationError, match="private/reserved"):
                validate_moodle_url("http://localhost-alias.test")

    def test_link_local_blocked(self):
        with patch("socket.getaddrinfo", return_value=_gai("169.254.169.254")):
            with pytest.raises(UrlValidationError, match="private/reserved"):
                validate_moodle_url("http://aws-metadata.test")

    def test_literal_ip_rejected_without_networks(self):
        with pytest.raises(UrlValidationError, match="literal IP"):
            validate_moodle_url("http://10.42.0.42")

    def test_literal_ip_passes_when_in_networks(self, monkeypatch):
        monkeypatch.setenv("MOODLE_ALLOWED_NETWORKS", "10.42.0.0/24")
        v = validate_moodle_url("http://10.42.0.42", allow_private_networks=True)
        assert v.is_literal_ip is True
        assert v.resolved_ip == "10.42.0.42"
        assert v.hostname == "10.42.0.42"

    def test_literal_ip_blocked_for_non_admin_even_with_network(self, monkeypatch):
        """Env-var match, but caller lacks the role capability."""
        monkeypatch.setenv("MOODLE_ALLOWED_NETWORKS", "10.42.0.0/24")
        with pytest.raises(UrlValidationError, match="admin privileges"):
            validate_moodle_url("http://10.42.0.42")

    def test_literal_public_ip_still_requires_networks(self):
        # public IPs now require explicit MOODLE_ALLOWED_NETWORKS opt-in
        with pytest.raises(UrlValidationError, match="literal IP"):
            validate_moodle_url("http://93.184.216.34", allow_private_networks=True)

    def test_literal_ip_outside_networks_rejected(self, monkeypatch):
        monkeypatch.setenv("MOODLE_ALLOWED_NETWORKS", "10.42.0.0/24")
        with pytest.raises(UrlValidationError, match="literal IP"):
            validate_moodle_url("http://10.99.0.1", allow_private_networks=True)

    def test_resolution_failure_propagates(self):
        import socket

        with patch("socket.getaddrinfo", side_effect=socket.gaierror(-2, "no")):
            with pytest.raises(UrlValidationError, match="resolve"):
                validate_moodle_url("http://nope.test")

    def test_explicit_port_preserved(self):
        with patch("socket.getaddrinfo", return_value=_gai("93.184.216.34")):
            v = validate_moodle_url("http://example.com:8080/path")
        assert v.port == 8080


class TestMakePinnedSession:
    """Session rewrites HTTP URLs and re-resolves HTTPS ones.

    No real TCP; we mount a fake transport adapter and inspect the
    prepared request.
    """

    def _validated(self, hostname="example.com", ip="93.184.216.34", scheme="http"):
        from app.services.url_validation import ValidatedUrl

        return ValidatedUrl(
            original_url=f"{scheme}://{hostname}",
            scheme=scheme,
            hostname=hostname,
            port=80 if scheme == "http" else 443,
            resolved_ip=ip,
            is_literal_ip=False,
        )

    def test_http_request_rewrites_host_to_ip(self):
        validated = self._validated()
        sent = {}

        def capture(_self, request, **_kw):
            sent["url"] = request.url
            sent["host"] = request.headers.get("Host")
            return _ok_response(request)

        with patch.object(requests.adapters.HTTPAdapter, "send", capture):
            session = make_pinned_session(validated)
            session.get("http://example.com/foo")

        # URL has IP in netloc; Host header preserves the original
        assert "93.184.216.34" in sent["url"]
        assert "example.com" not in sent["url"].split("://", 1)[1].split("/", 1)[0]
        assert sent["host"] == "example.com"

    def test_https_request_revalidates_dns(self):
        """HTTPS doesn't rewrite (SNI/cert) but rejects DNS drift."""
        validated = self._validated(scheme="https")

        # DNS now returns a different IP, must raise UrlValidationError
        with patch.object(
            requests.adapters.HTTPAdapter,
            "send",
            lambda self, r, **kw: _ok_response(r),
        ):
            with patch("socket.getaddrinfo", return_value=_gai("1.2.3.4")):
                session = make_pinned_session(validated)
                with pytest.raises(UrlValidationError, match="DNS"):
                    session.get("https://example.com/foo")

    def test_https_request_passes_when_dns_stable(self):
        validated = self._validated(scheme="https")

        with patch.object(
            requests.adapters.HTTPAdapter,
            "send",
            lambda self, r, **kw: _ok_response(r),
        ):
            with patch("socket.getaddrinfo", return_value=_gai("93.184.216.34")):
                session = make_pinned_session(validated)
                resp = session.get("https://example.com/foo")
        assert resp.status_code == 200

    def test_off_host_request_passes_through(self):
        """Cross-host redirects skip the pinned-IP rewrite and flow through
        normal DNS so the caller can re-validate them."""
        validated = self._validated()
        sent = {}

        def capture(_self, request, **_kw):
            sent["url"] = request.url
            return _ok_response(request)

        with patch.object(requests.adapters.HTTPAdapter, "send", capture):
            session = make_pinned_session(validated)
            session.get("http://other.example/foo")

        # URL not rewritten, no Host header forced
        assert "other.example" in sent["url"]
