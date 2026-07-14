"""Moodle source adapter.

Metadata sync, content download, missing-file detection, HTML
sanitization, and storage-path layout for Moodle course files. Takes
config and storage so tests can drive it directly with stubs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup
from minio.error import S3Error

from core.moodle_export_client import (
    MoodleAccessException,
    MoodleAuthenticationError,
    MoodleConnectionError,
    MoodleExportClient,
)
from core.source_adapter import SourceAdapter
from core.source_types import SourceType
from core.storage_paths import get_datasource_path
from core.url_validation import UrlValidationError

logger = logging.getLogger(__name__)


class MoodleSourceAdapter(SourceAdapter):
    """Strategy for the MOODLE source type."""

    source_type = SourceType.MOODLE

    def __init__(self, config, storage):
        self.config = config
        self.storage = storage

    def build_client(
        self,
        moodle_domain: str,
        moodle_token: str,
        *,
        allow_private_networks: bool = False,
    ) -> MoodleExportClient:
        """Build a MoodleExportClient, mapping SSRF rejection to a typed error.

        validate_moodle_url raises UrlValidationError when the URL is
        rejected; surfaced as MoodleConnectionError so the job-error path
        doesn't reclassify it as an auth failure.
        """
        try:
            return MoodleExportClient(
                moodle_domain,
                moodle_token,
                timeout=self.config.moodle_request_timeout,
                allow_private_networks=allow_private_networks,
            )
        except UrlValidationError as e:
            raise MoodleConnectionError(f"Moodle URL rejected by SSRF allowlist: {e}")

    def test_connection(
        self,
        moodle_domain: str,
        moodle_token: str,
        *,
        allow_private_networks: bool = False,
    ) -> None:
        """Smoke-test the Moodle webservice.

        MoodleExportClient already raises typed errors for invalidtoken
        and generic webservice failures; this just guards against an
        unexpectedly empty response shape.
        """
        client = self.build_client(
            moodle_domain, moodle_token, allow_private_networks=allow_private_networks
        )
        response = client.export_all_courses(limit=1)
        if not response or not isinstance(response, dict):
            raise MoodleConnectionError(f"Invalid response from Moodle API: {response}")
        total_courses = response.get("pagination", {}).get("total_courses", 0)
        logger.info(
            f"Connected to Moodle successfully. Found {total_courses} total courses"
        )

    def sync_metadata(self, message: dict, force: bool) -> list[dict]:
        """Page through the Moodle export and return formatted course metadata."""
        moodle_domain = message.get("moodle_domain")
        moodle_token = message.get("moodle_token")
        allow_private = message.get("owner_role") == "admin"

        if not moodle_domain or not moodle_token:
            raise ValueError("Moodle domain and token are required")

        logger.info(f"Starting Moodle metadata sync for domain: {moodle_domain}")
        self.test_connection(
            moodle_domain, moodle_token, allow_private_networks=allow_private
        )
        client = self.build_client(
            moodle_domain, moodle_token, allow_private_networks=allow_private
        )

        all_courses: list[dict] = []
        offset = 0
        limit = 50

        while True:
            response = client.export_all_courses(
                include_hidden=True,
                include_non_enrolled=True,
                include_site=True,
                offset=offset,
                limit=limit,
            )
            courses = response.get("courses", [])
            all_courses.extend(courses)
            pagination = response.get("pagination", {})
            if not pagination.get("has_more", False):
                break
            offset = pagination.get("next_offset", offset + limit)
            logger.info(f"Fetched {len(all_courses)} courses so far...")

        logger.info(f"Successfully retrieved {len(all_courses)} courses from Moodle")

        formatted_courses: list[dict] = []
        for course in all_courses:
            try:
                formatted_courses.append(self._format_course_metadata(course))
            except Exception as e:
                logger.warning(
                    f"Error formatting course {course.get('id', 'unknown')}: {e}"
                )

        return formatted_courses

    def _format_course_metadata(self, course: dict) -> dict:
        course_id = str(course["id"])
        structure = self._extract_course_structure(course)
        total_sections = len(course.get("sections", []))
        total_activities = sum(
            len(section.get("activities", [])) for section in course.get("sections", [])
        )
        total_files = sum(
            len(activity.get("files", []))
            for section in course.get("sections", [])
            for activity in section.get("activities", [])
        )
        version_hash = self._create_course_version_hash(course)

        return {
            "id": course_id,
            "fullname": course["fullname"],
            "shortname": course.get("shortname", ""),
            "category": course.get("category", "Uncategorized"),
            "description": course.get("description", ""),
            "format": course.get("format", ""),
            "version_hash": version_hash,
            "structure": structure,
            "total_sections": total_sections,
            "total_activities": total_activities,
            "total_files": total_files,
            "selection_key": f"course:{course_id}",
        }

    def _extract_course_structure(self, course: dict) -> dict:
        course_id = str(course["id"])
        structure: dict = {
            "_course_selection_key": f"course:{course_id}",
            "_course_info": {"id": course_id, "total_files": 0, "total_activities": 0},
        }

        for section in course.get("sections", []):
            section_name = section.get(
                "name", f"Section {section.get('section_number', '')}"
            )
            section_info: dict = {
                "id": section.get("id"),
                "section_number": section.get("section_number", 0),
                "summary": section.get("summary", ""),
                "section_url": section.get("section_url", ""),
                "activities": {},
            }

            for activity in section.get("activities", []):
                activity_name = activity.get("name", "Unnamed Activity")
                activity_id = str(activity["id"])
                activity_info: dict = {
                    "type": activity.get("type", "unknown"),
                    "id": activity_id,
                    "description": activity.get("description", ""),
                    "files": [],
                }

                # expose glossary entries (id + concept) so the API can offer
                # per-entry browsing; definitions live in the indexed documents
                content_data = activity.get("content_data")
                if (
                    isinstance(content_data, dict)
                    and content_data.get("type") == "glossary"
                ):
                    activity_info["entries"] = [
                        {
                            "id": str(entry.get("id", "")),
                            "concept": entry.get("concept", ""),
                        }
                        for entry in content_data.get("entries") or []
                    ]

                for file_info in activity.get("files", []):
                    file_id = str(file_info.get("id"))
                    file_data = {
                        "id": file_id,
                        "filename": file_info.get("filename", ""),
                        "filepath": file_info.get("filepath", ""),
                        "filesize": file_info.get("filesize", 0),
                        "mimetype": file_info.get("mimetype", ""),
                        "download_url": file_info.get("download_url", ""),
                        "selection_key": f"{activity_id}:{file_id}",
                    }
                    activity_info["files"].append(file_data)
                    structure["_course_info"]["total_files"] += 1

                section_info["activities"][activity_name] = activity_info
                structure["_course_info"]["total_activities"] += 1

            structure[section_name] = section_info

        return structure

    def _create_course_version_hash(self, course: dict) -> str:
        structure_data = {
            "id": course["id"],
            "sections": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "section_number": s.get("section_number", 0),
                    "activities": [
                        {
                            "id": a["id"],
                            "name": a["name"],
                            "type": a.get("type", "unknown"),
                            "files": [
                                {
                                    "id": f.get("id"),
                                    "filename": f.get("filename"),
                                    "filesize": f.get("filesize"),
                                    "hash": f.get("hash", ""),
                                }
                                for f in a.get("files", [])
                            ],
                        }
                        for a in s.get("activities", [])
                    ],
                }
                for s in course.get("sections", [])
            ],
        }
        return hashlib.md5(
            json.dumps(structure_data, sort_keys=True).encode()
        ).hexdigest()

    def sync_content(self, message: dict, selected_files: list, force: bool) -> int:
        """Download selected Moodle files to S3.

        selected_files contains `course:<id>` keys.
        """
        moodle_domain = message.get("moodle_domain")
        moodle_token = message.get("moodle_token")
        datasource_id = message["datasource_id"]
        owner_email = message["owner_email"]
        allow_private = message.get("owner_role") == "admin"

        if not moodle_domain or not moodle_token:
            raise ValueError("Moodle domain and token are required")

        logger.info(f"Starting Moodle content sync for domain: {moodle_domain}")
        logger.info(
            f"Owner email: {owner_email}, Selections to process: {len(selected_files)}"
        )

        self.test_connection(
            moodle_domain, moodle_token, allow_private_networks=allow_private
        )
        client = self.build_client(
            moodle_domain, moodle_token, allow_private_networks=allow_private
        )

        course_selections = [s for s in selected_files if s.startswith("course:")]
        ignored = [s for s in selected_files if not s.startswith("course:")]
        if ignored:
            logger.warning(
                f"Ignoring {len(ignored)} non-course selection(s); "
                f"individual-file selection is not supported: {ignored}"
            )
        logger.info(f"Processing {len(course_selections)} courses")

        files_downloaded = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            for course_selection in course_selections:
                course_id = course_selection.split(":")[1]
                # index pruning is wired through ensure_content (which has the
                # vector-store client); sync_content only refreshes storage
                downloaded, _ = self._download_entire_course(
                    client,
                    course_id,
                    temp_dir_path,
                    datasource_id,
                    owner_email,
                    moodle_domain,
                )
                files_downloaded += downloaded
                logger.info(f"Downloaded {downloaded} files from course {course_id}")

        logger.info(
            f"Content sync completed. Total files downloaded: {files_downloaded}"
        )
        return files_downloaded

    def sanitize_html(self, html: str, files: list[dict] | None = None) -> str:
        """Clean Moodle HTML for RAG ingestion.

        When files (an activity's files[] array) is provided,
        `@@PLUGINFILE@@/<name>` references in <img>/<a> are rewritten to
        the matching file's download_url, and <div class="h5p-placeholder">
        elements are replaced with a marker pointing at the companion H5P
        document (ingested separately). Unresolved references are stripped.
        """
        if not html:
            return ""
        html = html.replace("\r\n", "\n")
        soup = BeautifulSoup(html, "html.parser")

        file_map: dict[str, str] = {}
        for f in files or []:
            name = f.get("filename")
            url = f.get("download_url")
            if name and url:
                file_map[unquote(name)] = url

        pluginfile_re = re.compile(r"@@PLUGINFILE@@/([^\s\"'<>]+)")

        def resolve(reference: str) -> str | None:
            match = pluginfile_re.search(reference)
            if not match:
                return None
            return file_map.get(unquote(match.group(1)))

        for tag in soup.find_all(["iframe", "script", "style"]):
            tag.decompose()

        # resolve H5P placeholders before the @@PLUGINFILE@@ strip below
        # erases the filename. The .h5p name lives in data-h5p-file or as
        # @@PLUGINFILE@@/<name> in the div text.
        for div in soup.find_all("div", class_="h5p-placeholder"):
            h5p_name = div.get("data-h5p-file")
            if not h5p_name:
                match = pluginfile_re.search(div.get_text())
                if match:
                    h5p_name = unquote(match.group(1))
            if h5p_name:
                marker = soup.new_tag("p")
                em = soup.new_tag("em")
                em.string = (
                    f"Embedded H5P content: {h5p_name} "
                    f"(indexed as a separate document)."
                )
                marker.append(em)
                div.replace_with(marker)
            else:
                div.decompose()

        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "@@PLUGINFILE@@" not in src:
                continue
            resolved = resolve(src)
            if resolved:
                img["src"] = resolved
            else:
                img.decompose()

        for anchor in soup.find_all("a"):
            href = anchor.get("href", "")
            if "@@PLUGINFILE@@" not in href:
                continue
            resolved = resolve(href)
            if resolved:
                anchor["href"] = resolved

        # strip remaining @@PLUGINFILE@@ text fragments (unresolved refs)
        for element in soup.find_all(string=re.compile(r"@@PLUGINFILE@@")):
            element.replace_with(re.sub(r"@@PLUGINFILE@@\S*", "", str(element)))

        # unwrap single-cell layout tables
        for table in soup.find_all("table"):
            cells = table.find_all("td")
            if len(cells) <= 2:
                table.replace_with(*[c for cell in cells for c in cell.children])

        return str(soup)

    def extract_text_content(
        self,
        course: dict,
        temp_dir: Path,
        datasource_id: str,
        owner_email: str,
        moodle_domain: str,
    ) -> list[dict]:
        """Extract section/activity text content as HTML files.

        Returns dicts with: local_path, storage_filename, filename,
        source_url, mime_type, file_id.
        """
        course_name = course.get("fullname", "Unknown Course")
        course_id = str(course["id"])
        results: list[dict] = []

        for section in course.get("sections", []):
            section_id = str(section.get("id", ""))
            section_name = section.get(
                "name", f"Section {section.get('section_number', '')}"
            )
            summary = section.get("summary", "")

            plain_text = BeautifulSoup(summary, "html.parser").get_text(strip=True)
            if len(plain_text) >= 50:
                sanitized = self.sanitize_html(summary)
                html_content = (
                    f"<h1>{course_name} &gt; {section_name}</h1>\n{sanitized}"
                )
                filename = f"moodle_section_{section_id}.html"
                file_path = temp_dir / filename

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

                results.append(
                    {
                        "local_path": file_path,
                        "storage_filename": filename,
                        "filename": f"{course_name} > {section_name}",
                        "source_url": section.get("section_url", ""),
                        "mime_type": "text/html",
                        "file_id": f"moodle_section_{course_id}_{section_id}",
                    }
                )

            for activity in section.get("activities", []):
                activity_id = str(activity.get("id", ""))
                activity_name = activity.get("name", "Unnamed Activity")
                content_data = activity.get("content_data", {})

                # glossaries carry term/definition pairs in content_data.entries
                # rather than a content body; emit one document per entry so each
                # concept embeds as its own vector instead of the whole glossary
                # collapsing into a single merged chunk.
                if (
                    isinstance(content_data, dict)
                    and content_data.get("type") == "glossary"
                ):
                    results.extend(
                        self._extract_glossary_entries(course, activity, temp_dir)
                    )
                    continue

                # merge content_data.content and description so the sanitizer
                # can resolve @@PLUGINFILE@@ refs from either side (mod_page
                # often splits body and embedded image across the two). Skip
                # description when it duplicates content verbatim.
                content_text = ""
                if isinstance(content_data, dict):
                    content_text = content_data.get("content", "") or ""
                description = activity.get("description", "") or ""
                parts: list[str] = []
                if content_text:
                    parts.append(content_text)
                if description and description.strip() != content_text.strip():
                    parts.append(description)
                content = "\n".join(parts)

                plain_text = BeautifulSoup(content, "html.parser").get_text(strip=True)
                if len(plain_text) < 50:
                    continue

                sanitized = self.sanitize_html(
                    content, files=activity.get("files") or []
                )
                html_content = (
                    f"<h1>{course_name} &gt; {activity_name}</h1>\n{sanitized}"
                )
                act_filename = f"moodle_activity_{activity_id}.html"
                act_path = temp_dir / act_filename

                with open(act_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

                results.append(
                    {
                        "local_path": act_path,
                        "storage_filename": act_filename,
                        "filename": f"{course_name} > {activity_name}",
                        "source_url": activity.get("activity_url", ""),
                        "mime_type": "text/html",
                        "file_id": f"moodle_activity_{course_id}_{activity_id}",
                    }
                )

        logger.info(
            f"Extracted {len(results)} text content items from course {course_name}"
        )
        return results

    def _extract_glossary_entries(
        self, course: dict, activity: dict, temp_dir: Path
    ) -> list[dict]:
        """Emit one HTML document per glossary entry.

        Each entry (concept + definition) becomes its own document so it
        embeds as a self-contained vector rather than the whole glossary
        collapsing into a single chunk. Entries are always emitted, with no
        minimum-length threshold, since a short term/definition pair is still
        a useful retrieval unit.
        """
        course_name = course.get("fullname", "Unknown Course")
        course_id = str(course["id"])
        activity_id = str(activity.get("id", ""))
        activity_name = activity.get("name", "Unnamed Activity")
        activity_url = activity.get("activity_url", "")
        content_data = activity.get("content_data") or {}
        entries = content_data.get("entries") or []

        results: list[dict] = []
        for entry in entries:
            concept = (entry.get("concept") or "").strip()
            definition = entry.get("definition") or ""
            if not concept and not definition.strip():
                continue
            entry_id = str(entry.get("id", ""))

            html_content = (
                f"<h1>{course_name} &gt; {activity_name} &gt; {concept}</h1>\n"
                f"<h2>{concept}</h2>\n{self.sanitize_html(definition)}"
            )
            filename = f"moodle_glossary_{activity_id}_{entry_id}.html"
            file_path = temp_dir / filename
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            results.append(
                {
                    "local_path": file_path,
                    "storage_filename": filename,
                    "filename": f"{course_name} > {activity_name} > {concept}",
                    "source_url": activity_url,
                    "mime_type": "text/html",
                    "file_id": (
                        f"moodle_glossary_{course_id}_{activity_id}_{entry_id}"
                    ),
                }
            )
        return results

    def _download_entire_course(
        self,
        client: MoodleExportClient,
        course_id: str,
        temp_dir: Path,
        datasource_id: str,
        owner_email: str,
        moodle_domain: str,
    ) -> tuple[int, list[dict]]:
        """Download all files from a course and upload the manifest.

        Returns (files_downloaded, pruned), where pruned is a list of
        {"file_id", "basename"} records for stale objects removed from
        storage, so the caller can delete the matching documents from the
        vector index by stable file_id where known, basename otherwise.
        """
        try:
            response = client.export_course(int(course_id))
            course = response.get("course")
            if not course:
                logger.error(f"Course {course_id} not found")
                return 0, []

            logger.info(f"Downloading course: {course['fullname']} (ID: {course_id})")
            course_name = course.get("fullname", "Unknown Course")
            files_downloaded = 0
            access_denied = 0

            # manifest maps S3 filenames to metadata (source_url, display name)
            # for both attached files and extracted text content
            domain_clean = _clean_moodle_domain(moodle_domain)
            base_path = get_datasource_path(owner_email, datasource_id)
            course_path = f"{base_path}/moodle/{domain_clean}/course_{course_id}"
            # snapshot the existing manifest before it's overwritten so we can
            # recover the stable file_id of any object we prune (used for
            # rename-proof index deletion)
            old_manifest = self._load_text_content_manifest(course_path)
            manifest: dict = {}

            for section in course.get("sections", []):
                section_num = section.get("section_number", 0)
                for activity in section.get("activities", []):
                    activity_id = str(activity["id"])
                    activity_name = activity.get("name", "Unnamed Activity")
                    activity_url = activity.get("activity_url", "")
                    activity_files = activity.get("files", [])
                    for idx, file_info in enumerate(activity_files):
                        try:
                            file_id = str(file_info["id"])
                            filename = file_info["filename"]
                            local_file_path = temp_dir / f"{file_id}_{filename}"

                            if client.download_file(
                                file_info["download_url"],
                                local_file_path,
                                show_progress=False,
                            ):
                                storage_path = self._course_file_storage_path(
                                    owner_email,
                                    datasource_id,
                                    moodle_domain,
                                    course_id,
                                    section_num,
                                    activity_id,
                                    file_id,
                                    filename,
                                )
                                self._upload_file_to_storage(
                                    local_file_path, storage_path
                                )
                                s3_basename = Path(storage_path).name
                                manifest[s3_basename] = {
                                    "source_url": activity_url,
                                    "filename": (
                                        f"{course_name} > {activity_name} > {filename}"
                                    ),
                                    "file_id": (
                                        f"moodle_file_{course_id}_"
                                        f"{activity_id}_{file_id}"
                                    ),
                                }
                                files_downloaded += 1
                                local_file_path.unlink()
                        except MoodleAccessException as e:
                            # token lacks permission on this activity's
                            # resource, every sibling file is the same
                            # resource in another language/format and will
                            # fail the same way. skip the rest of the
                            # activity instead of replaying the failure.
                            remaining = len(activity_files) - idx - 1
                            access_denied += remaining + 1
                            logger.warning(
                                "Access denied to activity %s (%s) in course %s: %s. "
                                "Skipping %d sibling file(s).",
                                activity_id,
                                activity_name,
                                course_id,
                                e,
                                remaining,
                            )
                            break
                        except Exception as e:
                            logger.error(
                                f"Error downloading file "
                                f"{file_info.get('filename', 'unknown')}: {e}"
                            )

            text_items = self.extract_text_content(
                course,
                temp_dir,
                datasource_id,
                owner_email,
                moodle_domain,
            )

            # every downloadable file was access-denied and no text content came
            # through: the token can read the course export but lacks the
            # file-download capability. Returning 0 here would let the job
            # complete "successfully" having ingested nothing (or serving only a
            # stale copy already in storage), so fail loudly with a permission
            # error the operator can act on. Raised before the prune below so a
            # usable stale object is not deleted on the way out.
            if files_downloaded == 0 and access_denied > 0 and not text_items:
                raise MoodleAccessException(
                    f"Token lacks download permission for course {course_id} "
                    f"('{course_name}'): all {access_denied} file(s) denied and "
                    f"no text content available"
                )

            if text_items:
                text_content_prefix = (
                    f"{base_path}/moodle/{domain_clean}/course_{course_id}/text_content"
                )
                for item in text_items:
                    storage_path = f"{text_content_prefix}/{item['storage_filename']}"
                    self._upload_file_to_storage(item["local_path"], storage_path)
                    manifest[item["storage_filename"]] = {
                        "source_url": item["source_url"],
                        "filename": item["filename"],
                        "file_id": item.get("file_id"),
                    }
                    item["local_path"].unlink(missing_ok=True)
                logger.info(
                    f"Uploaded {len(text_items)} text content files for "
                    f"course {course_id}"
                )

            if manifest:
                manifest_path = temp_dir / "text_content_manifest.json"
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f)
                manifest_storage = (
                    f"{base_path}/moodle/{domain_clean}/course_{course_id}/"
                    "text_content_manifest.json"
                )
                self._upload_file_to_storage(manifest_path, manifest_storage)
                logger.info(
                    f"Uploaded manifest with {len(manifest)} entries for "
                    f"course {course_id}"
                )

            # Reconcile storage against the live course export: objects that
            # are no longer part of the course (a file removed or replaced
            # upstream) are stale leftovers that would otherwise be re-ingested
            # with no manifest metadata. The expected set is built from the
            # export itself, not the download-gated manifest, so a file that
            # merely failed to download this run stays expected and is kept.
            expected_basenames = {item["storage_filename"] for item in text_items}
            for section in course.get("sections", []):
                for activity in section.get("activities", []):
                    for file_info in activity.get("files", []):
                        file_id = str(file_info["id"])
                        filename = file_info["filename"]
                        expected_basenames.add(f"file_{file_id}_{filename}")
            pruned_basenames = self._prune_stale_course_objects(
                course_path, expected_basenames
            )
            # carry each pruned object's stable file_id (recovered from the
            # pre-sync manifest) so the index delete can match on it instead of
            # the filename, which a converter may have changed
            pruned = [
                {
                    "file_id": old_manifest.get(basename, {}).get("file_id"),
                    "basename": basename,
                }
                for basename in pruned_basenames
            ]

            return files_downloaded, pruned
        except (
            MoodleAuthenticationError,
            MoodleConnectionError,
            MoodleAccessException,
        ):
            raise
        except Exception as e:
            logger.error(f"Error downloading course {course_id}: {e}")
            raise MoodleConnectionError(f"Error during course download: {e}")

    def _prune_stale_course_objects(
        self, course_path: str, expected_basenames: set[str]
    ) -> list[str]:
        """Delete storage objects under course_path no longer in the course.

        Returns the basenames that were pruned, so the caller can delete the
        matching documents from the vector index too. expected_basenames is
        derived from the live Moodle export, so only files genuinely
        removed/replaced upstream are pruned; the manifest is always kept. Only
        reached after a successful export, so an empty expected set means the
        course was genuinely emptied upstream, its stale objects are still
        pruned (logged at warning so a mass delete stays visible).
        """
        try:
            objects = list(
                self.storage.list_objects(self.config.bucket_name, course_path)
            )
        except Exception as e:
            logger.warning(f"Could not list {course_path} for pruning: {e}")
            return []

        if not expected_basenames and objects:
            logger.warning(
                f"Course at {course_path} has no current files in the export; "
                f"pruning all stale objects"
            )

        pruned: list[str] = []
        for obj in objects:
            obj_name = str(obj.object_name)
            basename = Path(obj_name).name
            if (
                basename == "text_content_manifest.json"
                or basename in expected_basenames
            ):
                continue
            try:
                self.storage.remove_object(self.config.bucket_name, obj_name)
                pruned.append(basename)
                logger.info(f"Pruned stale course object: {obj_name}")
            except Exception as e:
                logger.warning(f"Failed to prune {obj_name}: {e}")
        if pruned:
            logger.info(f"Pruned {len(pruned)} stale object(s) under {course_path}")
        return pruned

    def _course_file_storage_path(
        self,
        owner_email: str,
        datasource_id: str,
        moodle_domain: str,
        course_id: str,
        section_num: int,
        activity_id: str,
        file_id: str,
        filename: str,
    ) -> str:
        domain_clean = _clean_moodle_domain(moodle_domain)
        base_path = get_datasource_path(owner_email, datasource_id)
        return (
            f"{base_path}/moodle/{domain_clean}/course_{course_id}/"
            f"section_{section_num}/activity_{activity_id}/"
            f"file_{file_id}_{filename}"
        )

    def _upload_file_to_storage(self, local_file_path: Path, storage_path: str) -> None:
        try:
            with tempfile.TemporaryDirectory() as upload_temp_dir:
                upload_temp_path = Path(upload_temp_dir)
                storage_path_obj = Path(storage_path)
                storage_dir = upload_temp_path / storage_path_obj.parent
                storage_dir.mkdir(parents=True, exist_ok=True)
                intended_filename = storage_path_obj.name
                final_file_path = storage_dir / intended_filename
                shutil.copy2(local_file_path, final_file_path)
                self.storage.upload_directory(
                    upload_temp_path, self.config.bucket_name, ""
                )
        except Exception as e:
            logger.error(f"Error uploading to storage: {e}")
            raise

    def ensure_content(
        self,
        datasource: dict,
        owner_email: str,
        selected_files: list[str],
        force: bool,
    ) -> tuple[int, list[dict]]:
        """Download anything in selected_files that's not already in storage.

        Returns (files_downloaded, pruned). pruned is a list of
        {"file_id", "basename"} records for stale objects removed from
        storage during the course refresh; the caller deletes the matching
        documents from the vector index.
        """
        moodle_domain = datasource.get("moodle_domain")
        moodle_token = datasource.get("moodle_token")
        datasource_id = datasource["datasource_id"]
        allow_private = datasource.get("owner_role") == "admin"

        if not moodle_domain or not moodle_token:
            raise ValueError("Missing Moodle configuration")

        self.test_connection(
            moodle_domain, moodle_token, allow_private_networks=allow_private
        )
        client = self.build_client(
            moodle_domain, moodle_token, allow_private_networks=allow_private
        )

        files_downloaded = 0
        pruned_records: list[dict] = []
        missing_files: list[str] = []

        for selection in selected_files:
            if selection.startswith("course:"):
                course_missing = self._course_needs_reconcile(
                    client, datasource_id, owner_email, selection, moodle_domain, force
                )
                missing_files.extend(course_missing)
            else:
                logger.warning(
                    f"Ignoring unsupported non-course selection: {selection}"
                )

        if not missing_files:
            logger.info("All selected content is already available")
            return 0, []

        logger.info(f"Found {len(missing_files)} missing files to download")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            for course_selection in missing_files:
                course_id = course_selection.split(":")[1]
                downloaded, pruned = self._download_entire_course(
                    client,
                    course_id,
                    temp_dir_path,
                    datasource_id,
                    owner_email,
                    moodle_domain,
                )
                files_downloaded += downloaded
                pruned_records.extend(pruned)

        return files_downloaded, pruned_records

    def _course_needs_reconcile(
        self,
        client: MoodleExportClient,
        datasource_id: str,
        owner_email: str,
        course_selection: str,
        moodle_domain: str,
        force: bool,
    ) -> list[str]:
        """Return [course_selection] when storage diverges from the export.

        Triggers a re-download (which rebuilds the manifest and prunes stale
        objects) when files are missing from storage OR when storage still
        holds files that no longer exist in the course — i.e. deleted or
        replaced upstream. Without the stale check a deletion would never be
        reconciled, leaving the orphaned object and its citation behind.
        """
        if force:
            return [course_selection]

        course_id = course_selection.split(":")[1]
        try:
            response = client.export_course(int(course_id))
            course = response.get("course")
            if not course:
                return []

            expected_file_ids: set[str] = set()
            for section in course.get("sections", []):
                for activity in section.get("activities", []):
                    for file_info in activity.get("files", []):
                        expected_file_ids.add(str(file_info["id"]))

            domain_clean = _clean_moodle_domain(moodle_domain)
            base_path = get_datasource_path(owner_email, datasource_id)
            course_path = f"{base_path}/moodle/{domain_clean}/course_{course_id}"

            actual_file_ids: set[str] = set()
            try:
                for obj in self.storage.list_objects(
                    self.config.bucket_name, course_path
                ):
                    obj_name = obj.object_name
                    if "/file_" in obj_name:
                        file_part = obj_name.split("/file_")[1]
                        if "_" in file_part:
                            file_id = file_part.split("_")[0]
                            actual_file_ids.add(file_id)
            except Exception as e:
                logger.debug(f"Error listing storage for course {course_id}: {e}")

            missing = expected_file_ids - actual_file_ids
            stale = actual_file_ids - expected_file_ids
            if missing or stale:
                logger.info(
                    f"Course {course_id} needs reconcile: "
                    f"{len(missing)} missing, {len(stale)} stale file(s)"
                )
                return [course_selection]
            return []
        except (MoodleAuthenticationError, MoodleConnectionError):
            raise
        except Exception as e:
            logger.warning(f"Error checking course {course_id}, will re-download: {e}")
            return [course_selection]

    def collect_files(self, datasource: dict, owner_email: str) -> list[dict]:
        """Enumerate files for ingestion under this Moodle datasource.

        Always returns path/filename/mime_type; adds source_url/file_id
        when text_content_manifest.json enriches them.
        """
        selected_files = datasource.get("selected_files", [])
        datasource_id = datasource.get("datasource_id")
        ds_owner_email = datasource.get("owner_email", owner_email)

        if not selected_files:
            logger.warning(f"No selected files for datasource {datasource_id}")
            return []

        base_path = get_datasource_path(ds_owner_email, datasource_id)
        domain_clean = _clean_moodle_domain(datasource.get("moodle_domain", ""))

        objects: list[dict] = []
        for selection in selected_files:
            if selection.startswith("course:"):
                objects.extend(
                    self._collect_course_files(base_path, domain_clean, selection)
                )
            else:
                logger.warning(
                    f"Ignoring unsupported non-course selection: {selection}"
                )
        return objects

    def _collect_course_files(
        self, base_path: str, domain_clean: str, course_selection: str
    ) -> list[dict]:
        course_id = course_selection.split(":")[1]
        course_path = f"{base_path}/moodle/{domain_clean}/course_{course_id}"
        manifest = self._load_text_content_manifest(course_path)

        # The manifest is rebuilt from the course's *current* files on every
        # sync, so when present it is the authoritative set. Objects left in
        # storage but absent from it are stale leftovers from a prior sync
        # (a file replaced or removed upstream); re-ingesting them would
        # surface citations with no file_id/source_url. Only fall back to
        # ingesting everything unenriched when no manifest is available
        # (first sync, or a course with no text content).
        enforce_manifest = bool(manifest)

        objects: list[dict] = []
        skipped_stale = 0
        try:
            for obj in self.storage.list_objects(self.config.bucket_name, course_path):
                obj_name = str(obj.object_name)
                obj_basename = Path(obj_name).name

                if obj_basename == "text_content_manifest.json":
                    continue

                in_manifest = obj_basename in manifest
                if enforce_manifest and not in_manifest:
                    skipped_stale += 1
                    logger.info(
                        f"Skipping stale object absent from manifest: {obj_basename}"
                    )
                    continue

                entry: dict = {
                    "path": Path(obj_name),
                    "filename": obj_basename,
                    "mime_type": None,
                }

                if in_manifest:
                    meta = manifest[obj_basename]
                    entry["filename"] = meta.get("filename", obj_basename)
                    entry["source_url"] = meta.get("source_url")
                    entry["file_id"] = meta.get("file_id")
                    if "/text_content/" in obj_name:
                        entry["mime_type"] = "text/html"

                objects.append(entry)
            logger.info(
                f"Found {len(objects)} files for course {course_id} "
                f"({skipped_stale} stale object(s) skipped)"
            )
        except Exception as e:
            logger.error(f"Error listing course {course_id} files: {e}")
        return objects

    def _load_text_content_manifest(self, course_path: str) -> dict:
        """Load the per-course manifest mapping S3 basenames to metadata.

        Expected first-sync NoSuchKey logs at debug; corrupt JSON or S3
        errors log at warning so operators can see why RAG citations
        stopped showing source URLs.
        """
        manifest_path = f"{course_path}/text_content_manifest.json"
        try:
            response = self.storage.client.get_object(
                self.config.bucket_name, manifest_path
            )
            try:
                manifest = json.loads(response.read())
            finally:
                response.close()
                response.release_conn()
            logger.info(
                f"Loaded manifest with {len(manifest)} text content "
                f"entries from {manifest_path}"
            )
            return manifest
        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.debug(
                    f"No text_content_manifest.json at {manifest_path} "
                    f"(first sync or no text content)"
                )
            else:
                logger.warning(f"S3 error loading manifest {manifest_path}: {e}")
        except json.JSONDecodeError as e:
            logger.warning(
                f"Manifest at {manifest_path} is not valid JSON: {e}. "
                f"Proceeding without metadata enrichment."
            )
        except Exception as e:
            logger.warning(f"Unexpected error loading manifest {manifest_path}: {e}")
        return {}


def _clean_moodle_domain(moodle_domain: str) -> str:
    """Flatten a Moodle URL into something safe for an S3 path segment."""
    return moodle_domain.replace("://", "_").replace("/", "_").strip("_")
