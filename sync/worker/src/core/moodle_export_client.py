"""Moodle Content Export Python Client."""

import json
import logging
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

import requests

from core.url_validation import (
    ValidatedUrl,
    make_pinned_session,
    validate_moodle_url,
)

logger = logging.getLogger(__name__)


class MoodleAuthenticationError(Exception):
    """Raised when Moodle rejects the supplied token."""


class MoodleConnectionError(Exception):
    """Raised for any Moodle API error other than authentication.

    Covers HTTP failures, non-JSON responses, and webservice errors that
    aren't `invalidtoken`. Catch MoodleAuthenticationError first to split
    auth from everything else.
    """


class MoodleAccessException(Exception):
    """Raised when Moodle returns errorcode=accessexception for a file.

    A per-file permission error, not an auth failure: the token is valid
    but doesn't have access to that particular resource. Callers can
    catch this to skip the rest of an activity instead of retrying every
    sibling file. Deliberately not a MoodleConnectionError so existing
    `except (MoodleAuthenticationError, MoodleConnectionError)` re-raise
    paths leave it alone.
    """


class MoodleExportClient:
    """Moodle webservice/file client with SSRF-safe outbound HTTP.

    Hostname is validated and resolved once at construction; the resolved
    IP is pinned via make_pinned_session. File downloads that rewrite to
    the same host reuse the pin.
    """

    def __init__(
        self,
        moodle_url: str,
        token: str,
        timeout: int = 30,
        *,
        allow_private_networks: bool = False,
    ):
        self.moodle_url = moodle_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        # raises UrlValidationError on private/reserved IPs without an
        # allowlist match. allow_private_networks is the per-job capability
        # gate from the owner's role.
        self.validated: ValidatedUrl = validate_moodle_url(
            self.moodle_url, allow_private_networks=allow_private_networks
        )
        self.session = make_pinned_session(self.validated, verify=False)
        self.session.headers.update(
            {"User-Agent": "Moodle Content Export Python Client"}
        )

    def export_course(self, course_id: int) -> dict:
        return self._make_request(
            "local_contentexport_export_course", {"courseid": course_id}
        )

    def export_all_courses(
        self,
        include_hidden: bool = False,
        category_id: int = 0,
        offset: int = 0,
        limit: int = 50,
        include_non_enrolled: bool = False,
    ) -> dict:
        return self._make_request(
            "local_contentexport_export_all_courses",
            {
                "include_hidden": include_hidden,
                "category_id": category_id,
                "offset": offset,
                "limit": limit,
                "include_non_enrolled": include_non_enrolled,
            },
        )

    def download_file(
        self, file_url: str, destination: Path, show_progress: bool = False
    ) -> bool:
        try:
            # Moodle may return public URLs while connecting via an internal host;
            # rewrite pluginfile/webservice URLs to the configured moodle_url host.
            parsed = urlparse(file_url)
            if "/webservice/" in parsed.path or "/pluginfile.php" in parsed.path:
                moodle_parsed = urlparse(self.moodle_url)
                parsed = parsed._replace(
                    scheme=moodle_parsed.scheme, netloc=moodle_parsed.netloc
                )

            # reject any URL whose host wasn't validated/pinned at __init__.
            # The pinned session falls back to normal DNS for off-host URLs,
            # which would reopen the SSRF window.
            if (parsed.hostname or "").lower() != self.validated.hostname.lower():
                logger.error(
                    "Refusing to download from non-validated host %s (expected %s)",
                    parsed.hostname,
                    self.validated.hostname,
                )
                return False

            query = parse_qsl(parsed.query, keep_blank_values=True)
            query.append(("token", self.token))
            url_with_token = parsed._replace(query=urlencode(query)).geturl()

            destination.parent.mkdir(parents=True, exist_ok=True)

            # no redirects: a redirect would bypass the pinned host check
            # and could route to an unvalidated private IP. pluginfile.php
            # with a valid token returns bytes directly, so this is safe.
            response = self.session.get(
                url_with_token,
                timeout=self.timeout,
                stream=True,
                allow_redirects=False,
            )
            if response.is_redirect or response.is_permanent_redirect:
                logger.error(
                    "Refusing to follow redirect for %s -> %s",
                    file_url,
                    response.headers.get("Location"),
                )
                return False
            response.raise_for_status()

            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # small files might be JSON error responses instead of content
            with open(destination, "rb") as f:
                content = f.read()
                if len(content) < 5000:
                    logger.info(
                        "Downloaded file %s is small (%d bytes), checking for error message",
                        destination,
                        len(content),
                    )
                    try:
                        error_data = json.loads(content)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                    else:
                        if isinstance(error_data, dict) and "error" in error_data:
                            errorcode = error_data.get("errorcode", "N/A")
                            logger.error(
                                "Moodle API error downloading file: %s (code=%s)",
                                error_data.get("error", "Unknown error"),
                                errorcode,
                            )
                            try:
                                destination.unlink()
                                logger.info("Removed invalid file: %s", destination)
                            except Exception as e:
                                logger.warning(
                                    "Could not remove invalid file %s: %s",
                                    destination,
                                    e,
                                )
                            if errorcode == "accessexception":
                                raise MoodleAccessException(
                                    error_data.get("error", "Access denied")
                                )
                            return False

            logger.info("Successfully downloaded file to %s", destination)
            return True

        except requests.exceptions.RequestException as e:
            logger.error("Network error downloading %s: %s", file_url, e)
            if destination.exists():
                try:
                    destination.unlink()
                    logger.info("Removed partial download: %s", destination)
                except Exception:
                    pass
            return False

    def _make_request(self, function: str, params: dict) -> dict:
        url = f"{self.moodle_url}/webservice/rest/server.php"

        converted_params = {
            key: (1 if value is True else 0 if value is False else value)
            for key, value in params.items()
        }

        data = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **converted_params,
        }

        try:
            response = self.session.post(
                url, data=data, timeout=self.timeout, allow_redirects=False
            )
            if response.is_redirect or response.is_permanent_redirect:
                raise MoodleConnectionError(
                    f"Refusing to follow redirect for {url} -> "
                    f"{response.headers.get('Location')}"
                )
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            raise MoodleConnectionError(f"Moodle request failed: {e}") from e
        except ValueError as e:
            raise MoodleConnectionError(
                f"Moodle returned non-JSON response: {e}"
            ) from e

        # Moodle encodes application errors as JSON 200s with an `errorcode`
        # field. `invalidtoken` is the auth signal; everything else is a
        # generic connection error so callers can split credential vs
        # operational failures with one except clause.
        if isinstance(result, dict) and "errorcode" in result:
            if result["errorcode"] == "invalidtoken":
                raise MoodleAuthenticationError(
                    f"Invalid Moodle token for domain: {self.moodle_url}"
                )
            message = result.get("message") or result.get("errorcode")
            raise MoodleConnectionError(f"Moodle API error: {message}")

        if isinstance(result, dict) and "error" in result:
            raise MoodleConnectionError(f"Moodle error: {result['error']}")

        return result
