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

        selected_files mixes `course:<id>` and `<activity_id>:<file_id>` keys.
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
        file_selections = [
            s for s in selected_files if ":" in s and not s.startswith("course:")
        ]
        logger.info(
            f"Processing {len(course_selections)} courses and "
            f"{len(file_selections)} individual files"
        )

        files_downloaded = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            for course_selection in course_selections:
                course_id = course_selection.split(":")[1]
                downloaded = self._download_entire_course(
                    client,
                    course_id,
                    temp_dir_path,
                    datasource_id,
                    owner_email,
                    moodle_domain,
                )
                files_downloaded += downloaded
                logger.info(f"Downloaded {downloaded} files from course {course_id}")

            for file_selection in file_selections:
                parts = file_selection.split(":")
                if len(parts) != 2:
                    logger.warning(f"Invalid selection format: {file_selection}")
                    continue
                activity_id, file_id = parts
                if self._download_specific_file(
                    client,
                    activity_id,
                    file_id,
                    temp_dir_path,
                    datasource_id,
                    owner_email,
                    moodle_domain,
                ):
                    files_downloaded += 1
                    logger.info(
                        f"Downloaded file {file_id} from activity {activity_id}"
                    )

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

    def _download_entire_course(
        self,
        client: MoodleExportClient,
        course_id: str,
        temp_dir: Path,
        datasource_id: str,
        owner_email: str,
        moodle_domain: str,
    ) -> int:
        """Download all files from a course and upload the manifest."""
        try:
            response = client.export_course(int(course_id))
            course = response.get("course")
            if not course:
                logger.error(f"Course {course_id} not found")
                return 0

            logger.info(f"Downloading course: {course['fullname']} (ID: {course_id})")
            course_name = course.get("fullname", "Unknown Course")
            files_downloaded = 0

            # manifest maps S3 filenames to metadata (source_url, display name)
            # for both attached files and extracted text content
            domain_clean = _clean_moodle_domain(moodle_domain)
            base_path = get_datasource_path(owner_email, datasource_id)
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

            return files_downloaded
        except (MoodleAuthenticationError, MoodleConnectionError):
            raise
        except Exception as e:
            logger.error(f"Error downloading course {course_id}: {e}")
            raise MoodleConnectionError(f"Error during course download: {e}")

    def _download_specific_file(
        self,
        client: MoodleExportClient,
        activity_id: str,
        file_id: str,
        temp_dir: Path,
        datasource_id: str,
        owner_email: str,
        moodle_domain: str,
    ) -> bool:
        """Download a single file by IDs."""
        try:
            file_info, course_info, section_info = self._find_file_by_ids(
                client, activity_id, file_id
            )
            if not file_info:
                logger.error(
                    f"File not found: activity_id={activity_id}, file_id={file_id}"
                )
                return False

            filename = file_info["filename"]
            local_file_path = temp_dir / f"{file_id}_{filename}"

            try:
                downloaded = client.download_file(
                    file_info["download_url"], local_file_path, show_progress=False
                )
            except MoodleAccessException as e:
                logger.warning(
                    "Access denied for file %s:%s — %s", activity_id, file_id, e
                )
                return False

            if downloaded:
                storage_path = self._course_file_storage_path(
                    owner_email,
                    datasource_id,
                    moodle_domain,
                    course_info["id"],
                    section_info.get("section_number", 0),
                    activity_id,
                    file_id,
                    filename,
                )
                self._upload_file_to_storage(local_file_path, storage_path)
                local_file_path.unlink()
                return True
            return False
        except (MoodleAuthenticationError, MoodleConnectionError):
            raise
        except Exception as e:
            logger.error(f"Error downloading file {activity_id}:{file_id}: {e}")
            raise MoodleConnectionError(f"Error during file download: {e}")

    def _find_file_by_ids(
        self, client: MoodleExportClient, activity_id: str, file_id: str
    ) -> tuple[dict | None, dict | None, dict | None]:
        """Search the full export for the given activity_id:file_id pair."""
        try:
            logger.info(
                f"Searching for file: activity_id={activity_id}, file_id={file_id}"
            )
            offset = 0
            limit = 50

            while True:
                response = client.export_all_courses(
                    include_hidden=True,
                    include_non_enrolled=True,
                    offset=offset,
                    limit=limit,
                )
                for course in response.get("courses", []):
                    for section in course.get("sections", []):
                        for activity in section.get("activities", []):
                            if str(activity["id"]) == str(activity_id):
                                for file_info in activity.get("files", []):
                                    if str(file_info["id"]) == str(file_id):
                                        return file_info, course, section

                pagination = response.get("pagination", {})
                if not pagination.get("has_more", False):
                    break
                offset = pagination.get("next_offset", offset + limit)

            return None, None, None
        except (MoodleAuthenticationError, MoodleConnectionError):
            raise
        except Exception as e:
            logger.error(f"Error finding file by IDs: {e}")
            raise MoodleConnectionError(f"Error during file search: {e}")

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
    ) -> int:
        """Download anything in selected_files that's not already in storage."""
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
        missing_files: list[str] = []

        for selection in selected_files:
            if selection.startswith("course:"):
                course_missing = self._get_missing_course_files_with_api(
                    client, datasource_id, owner_email, selection, moodle_domain, force
                )
                missing_files.extend(course_missing)
            elif ":" in selection:
                if self._is_file_missing(
                    datasource_id, owner_email, selection, moodle_domain, force
                ):
                    missing_files.append(selection)

        if not missing_files:
            logger.info("All selected content is already available")
            return 0

        logger.info(f"Found {len(missing_files)} missing files to download")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            course_selections = [f for f in missing_files if f.startswith("course:")]
            file_selections = [
                f for f in missing_files if ":" in f and not f.startswith("course:")
            ]

            for course_selection in course_selections:
                course_id = course_selection.split(":")[1]
                downloaded = self._download_entire_course(
                    client,
                    course_id,
                    temp_dir_path,
                    datasource_id,
                    owner_email,
                    moodle_domain,
                )
                files_downloaded += downloaded

            for file_selection in file_selections:
                parts = file_selection.split(":")
                if len(parts) != 2:
                    continue
                activity_id, file_id = parts
                if self._download_specific_file(
                    client,
                    activity_id,
                    file_id,
                    temp_dir_path,
                    datasource_id,
                    owner_email,
                    moodle_domain,
                ):
                    files_downloaded += 1

        return files_downloaded

    def _get_missing_course_files_with_api(
        self,
        client: MoodleExportClient,
        datasource_id: str,
        owner_email: str,
        course_selection: str,
        moodle_domain: str,
        force: bool,
    ) -> list[str]:
        """Return [course_selection] iff any file in the course is missing."""
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

            if not expected_file_ids:
                return []

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

            missing_count = len(expected_file_ids - actual_file_ids)
            if missing_count > 0:
                logger.info(
                    f"Course {course_id}: {missing_count}/"
                    f"{len(expected_file_ids)} files missing"
                )
                return [course_selection]
            return []
        except (MoodleAuthenticationError, MoodleConnectionError):
            raise
        except Exception as e:
            logger.warning(f"Error checking course {course_id}, will re-download: {e}")
            return [course_selection]

    def _is_file_missing(
        self,
        datasource_id: str,
        owner_email: str,
        file_selection: str,
        moodle_domain: str,
        force: bool,
    ) -> bool:
        """True iff activity_id:file_id has no matching object in storage."""
        if force:
            return True

        activity_id, file_id = file_selection.split(":")
        domain_clean = _clean_moodle_domain(moodle_domain)
        base_path = get_datasource_path(owner_email, datasource_id)
        search_path = f"{base_path}/moodle/{domain_clean}"

        try:
            for obj in self.storage.list_objects(self.config.bucket_name, search_path):
                obj_name = str(obj.object_name)
                if (
                    f"activity_{activity_id}" in obj_name
                    and f"file_{file_id}_" in obj_name
                ):
                    return False
            return True
        except Exception as e:
            logger.info(f"Error checking file {file_selection}, assuming missing: {e}")
            return True

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
            elif ":" in selection:
                objects.extend(
                    self._collect_specific_file(base_path, domain_clean, selection)
                )
        return objects

    def _collect_course_files(
        self, base_path: str, domain_clean: str, course_selection: str
    ) -> list[dict]:
        course_id = course_selection.split(":")[1]
        course_path = f"{base_path}/moodle/{domain_clean}/course_{course_id}"
        manifest = self._load_text_content_manifest(course_path)

        objects: list[dict] = []
        try:
            for obj in self.storage.list_objects(self.config.bucket_name, course_path):
                obj_name = str(obj.object_name)
                obj_basename = Path(obj_name).name

                if obj_basename == "text_content_manifest.json":
                    continue

                entry: dict = {
                    "path": Path(obj_name),
                    "filename": obj_basename,
                    "mime_type": None,
                }

                if obj_basename in manifest:
                    meta = manifest[obj_basename]
                    entry["filename"] = meta.get("filename", obj_basename)
                    entry["source_url"] = meta.get("source_url")
                    entry["file_id"] = meta.get("file_id")
                    if "/text_content/" in obj_name:
                        entry["mime_type"] = "text/html"

                objects.append(entry)
            logger.info(f"Found {len(objects)} files for course {course_id}")
        except Exception as e:
            logger.error(f"Error listing course {course_id} files: {e}")
        return objects

    def _collect_specific_file(
        self, base_path: str, domain_clean: str, selection: str
    ) -> list[dict]:
        # TODO: enrich from the course's text_content_manifest.json
        # (filename, source_url, file_id) once individual-file granularity
        # is wired up in the UI. Otherwise citations show the raw
        # file_<id>_<name> basename with no clickable source URL.
        activity_id, file_id = selection.split(":")
        search_path = f"{base_path}/moodle/{domain_clean}"
        try:
            for obj in self.storage.list_objects(self.config.bucket_name, search_path):
                obj_name = str(obj.object_name)
                if (
                    f"activity_{activity_id}" in obj_name
                    and f"file_{file_id}_" in obj_name
                ):
                    return [
                        {
                            "path": Path(obj_name),
                            "filename": Path(obj_name).name,
                            "mime_type": None,
                        }
                    ]
        except Exception as e:
            logger.error(f"Error finding file {selection}: {e}")
        return []

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
