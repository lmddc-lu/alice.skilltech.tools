#!/usr/bin/env python3
import base64
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup

    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from lxml import etree

    HAS_LXML = True
except ImportError:
    HAS_LXML = False


def _safe_extract(zip_ref: zipfile.ZipFile, dest: Path) -> None:
    """Extract an archive, rejecting members that would escape ``dest``.

    Guards against zip-slip: archive entries with ``..`` components, absolute
    paths, or symlinks pointing outside the extraction root.
    """
    dest = dest.resolve()
    for member in zip_ref.infolist():
        target = (dest / member.filename).resolve()
        if target != dest and dest not in target.parents:
            raise ScormParsingError(
                f"Unsafe path in archive (zip-slip): {member.filename!r}"
            )
        # reject symlinks (high 16 bits of external_attr hold the unix mode)
        mode = member.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            raise ScormParsingError(
                f"Refusing to extract symlink member: {member.filename!r}"
            )
    zip_ref.extractall(dest)


def _resolve_within(base_path: Path, rel: str) -> Path | None:
    """Resolve ``rel`` under ``base_path``, returning None if it escapes.

    Manifest-supplied hrefs are attacker-controlled; a value like
    ``../../../etc/passwd`` must not be allowed to read outside the package.
    """
    base = Path(base_path).resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        return None
    return target


def _clean_html(html: str) -> str:
    """Strip tags and normalise whitespace from a Rise HTML snippet."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class ScormParsingError(Exception):
    pass


class ManifestNotFoundError(ScormParsingError):
    """Raised when imsmanifest.xml is missing."""

    pass


class InvalidScormVersionError(ScormParsingError):
    """Raised when SCORM version is unsupported."""

    pass


def lzw_decompress(compressed):
    """Decompress a list of LZW codes to a string."""
    if not compressed or not isinstance(compressed, list):
        return compressed

    dict_size = 256
    dictionary = {i: chr(i) for i in range(dict_size)}

    result = []
    w = chr(compressed[0])
    result.append(w)

    for k in compressed[1:]:
        if k in dictionary:
            entry = dictionary[k]
        elif k == dict_size:
            entry = w + w[0]
        else:
            raise ValueError(f"Bad compressed code: {k}")

        result.append(entry)

        dictionary[dict_size] = w + entry[0]
        dict_size += 1

        w = entry

    return "".join(result)


def key_optimize_unpack(obj):
    if not isinstance(obj, dict) or "__k" not in obj:
        return obj

    keys = obj["__k"]
    data = obj["__v"]

    def decode_obj(o):
        if not isinstance(o, dict):
            return o

        decoded = {}
        for prop, value in o.items():
            if prop.isdigit():
                key_index = int(prop)
                if key_index < len(keys):
                    decoded[keys[key_index]] = decode_obj(value)
            else:
                decoded[prop] = decode_obj(value)

        return decoded

    return decode_obj(data)


@dataclass
class Resource:
    identifier: str
    type: str
    scorm_type: str | None
    href: str | None
    files: list[str]
    metadata: dict[str, Any]
    dependencies: list[str] = field(default_factory=list)


@dataclass
class SequencingRule:
    """SCORM 2004 sequencing rule."""

    condition_combination: str = "all"
    conditions: list[dict] = field(default_factory=list)
    action: str = ""


@dataclass
class Item:
    identifier: str
    title: str
    identifierref: str | None
    parameters: str | None
    children: list["Item"]
    prerequisites: str | None = None
    max_time_allowed: str | None = None
    time_limit_action: str | None = None
    data_from_lms: str | None = None
    completion_threshold: float | None = None
    objectives: list[dict] = field(default_factory=list)
    sequencing_rules: list[SequencingRule] = field(default_factory=list)


@dataclass
class Organization:
    identifier: str
    title: str
    items: list[Item]
    structure: str = "hierarchical"
    objectives_global_to_system: bool = False


@dataclass
class ScormPackage:
    identifier: str
    version: str
    title: str
    description: str | None
    metadata: dict[str, Any]
    organizations: list[Organization]
    resources: list[Resource]
    manifest_path: str
    extracted_path: str
    default_organization: str | None = None
    sequencing_collection: list[dict] = field(default_factory=list)
    version_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiseLesson:
    id: str
    title: str
    type: str
    icon: str
    items: list[dict] = field(default_factory=list)
    course_id: str | None = None


@dataclass
class RiseCourse:
    id: str
    title: str
    author: str
    color: str
    lessons: list[RiseLesson] = field(default_factory=list)
    media: dict = field(default_factory=dict)
    fonts: list | None = None


class HTMLExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_content = []
        self.in_script = False
        self.in_style = False
        self.scripts = []
        self.current_script = ""
        self.images = []
        self.links = []
        self.forms = []
        self.in_form = False
        self.current_form = {}

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "script":
            self.in_script = True
            if "src" in attrs_dict:
                self.scripts.append(attrs_dict["src"])
        elif tag == "style":
            self.in_style = True
        elif tag == "img" and "src" in attrs_dict:
            self.images.append(attrs_dict["src"])
        elif tag == "a" and "href" in attrs_dict:
            self.links.append(attrs_dict["href"])
        elif tag == "form":
            self.in_form = True
            self.current_form = {
                "action": attrs_dict.get("action", ""),
                "method": attrs_dict.get("method", "get"),
                "inputs": [],
            }
        elif tag == "input" and self.in_form:
            self.current_form["inputs"].append(
                {
                    "type": attrs_dict.get("type", "text"),
                    "name": attrs_dict.get("name", ""),
                    "value": attrs_dict.get("value", ""),
                }
            )

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
            if self.current_script.strip():
                self.scripts.append({"inline": True, "content": self.current_script})
                self.current_script = ""
        elif tag == "style":
            self.in_style = False
        elif tag == "form" and self.in_form:
            self.in_form = False
            if self.current_form:
                self.forms.append(self.current_form)
                self.current_form = {}

    def handle_data(self, data):
        if self.in_script:
            self.current_script += data
        elif not self.in_style:
            text = data.strip()
            if text:
                self.text_content.append(text)

    def get_text(self):
        return " ".join(self.text_content)

    def get_all_content(self):
        return {
            "text": self.get_text(),
            "scripts": self.scripts,
            "images": self.images,
            "links": self.links,
            "forms": self.forms,
        }


class ScormManifestParser:
    """SCORM manifest parser. Supports SCORM 1.2 and 2004."""

    # Default (SCORM 2004) namespaces; imscp/adlcp are re-detected per manifest.
    NAMESPACES = {
        "imscp": "http://www.imsglobal.org/xsd/imscp_v1p1",
        "adlcp": "http://www.adlnet.org/xsd/adlcp_v1p3",
        "imsss": "http://www.imsglobal.org/xsd/imsss",
        "adlseq": "http://www.adlnet.org/xsd/adlseq_v1p3",
        "adlnav": "http://www.adlnet.org/xsd/adlnav_v1p3",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    # SCORM 1.2 pairs the rootv1p1p2 content-packaging schema with the
    # rootv1p2 ADL extension schema instead of the 2004 v1p3 URIs.
    SCORM12_ADLCP = "http://www.adlnet.org/xsd/adlcp_rootv1p2"

    def __init__(self, manifest_path: str):
        self.manifest_path = Path(manifest_path)
        if not self.manifest_path.exists():
            raise ManifestNotFoundError(f"Manifest not found: {manifest_path}")

        # lxml handles namespaces better when available
        if HAS_LXML:
            self.tree = etree.parse(str(self.manifest_path))
        else:
            self.tree = ET.parse(self.manifest_path)
        self.root = self.tree.getroot()

        # SCORM 1.2 and 2004 use different core namespace URIs; detect the
        # manifest's actual namespaces so imscp/adlcp lookups match both.
        self.NAMESPACES = self._detect_namespaces()

        if not HAS_LXML:
            for prefix, uri in self.NAMESPACES.items():
                ET.register_namespace(prefix, uri)

    def _detect_namespaces(self) -> dict[str, str]:
        namespaces = dict(self.NAMESPACES)

        root_tag = str(self.root.tag)
        match = re.match(r"\{([^}]+)\}", root_tag)
        if match:
            imscp_uri = match.group(1)
            namespaces["imscp"] = imscp_uri
            if "imscp_rootv1p1p2" in imscp_uri:
                namespaces["adlcp"] = self.SCORM12_ADLCP

        return namespaces

    def parse_metadata(self) -> dict[str, Any]:
        metadata = {}

        metadata_elem = self._find_element(".//imscp:metadata", ".//metadata")

        if metadata_elem is not None:
            schema = self._find_text(".//imscp:schema", ".//schema", metadata_elem)
            version = self._find_text(
                ".//imscp:schemaversion", ".//schemaversion", metadata_elem
            )

            metadata["schema"] = schema or "ADL SCORM"
            metadata["schema_version"] = version or "1.2"

            if version:
                if "2004" in version:
                    if "4th" in version or "1.0" in version:
                        metadata["scorm_edition"] = "2004 4th Edition"
                    elif "3rd" in version:
                        metadata["scorm_edition"] = "2004 3rd Edition"
                    elif "2nd" in version:
                        metadata["scorm_edition"] = "2004 2nd Edition"
                    else:
                        metadata["scorm_edition"] = "2004"
                else:
                    metadata["scorm_edition"] = version

        title = self._find_text(".//imscp:title", ".//title")
        metadata["title"] = title or "Untitled Course"

        description = self._find_text(".//imscp:description", ".//description")
        if description:
            metadata["description"] = description

        return metadata

    def get_organizations(self) -> tuple[list[Organization], str | None]:
        organizations = []
        default_org = None

        orgs_elem = self._find_element(".//imscp:organizations", ".//organizations")

        if orgs_elem is not None:
            default_org = orgs_elem.get("default")

            org_elems = self._find_all_elements(
                ".//imscp:organization", ".//organization", orgs_elem
            )

            for org_elem in org_elems:
                org = self._parse_organization(org_elem)
                if org:
                    organizations.append(org)

        return organizations, default_org

    def _parse_organization(self, org_elem) -> Organization | None:
        identifier = org_elem.get("identifier", "")
        structure = org_elem.get("structure", "hierarchical")

        title = self._find_text(".//imscp:title", ".//title", org_elem) or identifier

        items = []
        item_elems = self._find_child_elements("imscp:item", "item", org_elem)

        for item_elem in item_elems:
            item = self._parse_item(item_elem)
            if item:
                items.append(item)

        objectives_global = (
            org_elem.get("objectivesGlobalToSystem", "false").lower() == "true"
        )

        return Organization(
            identifier=identifier,
            title=title,
            items=items,
            structure=structure,
            objectives_global_to_system=objectives_global,
        )

    def _parse_item(self, item_elem) -> Item | None:
        identifier = item_elem.get("identifier", "")
        identifierref = item_elem.get("identifierref")
        parameters = item_elem.get("parameters")

        title = self._find_text(".//imscp:title", ".//title", item_elem) or identifier

        prerequisites = item_elem.get("prerequisites")
        max_time_allowed = self._find_text(
            ".//adlcp:maxtimeallowed", ".//maxtimeallowed", item_elem
        )
        time_limit_action = self._find_text(
            ".//adlcp:timelimitaction", ".//timelimitaction", item_elem
        )
        data_from_lms = self._find_text(
            ".//adlcp:datafromlms", ".//datafromlms", item_elem
        )
        completion_threshold = self._find_text(
            ".//adlcp:completionThreshold", ".//completionThreshold", item_elem
        )

        objectives = self._parse_objectives(item_elem)
        sequencing_rules = self._parse_sequencing_rules(item_elem)

        children = []
        child_elems = self._find_child_elements("imscp:item", "item", item_elem)

        for child_elem in child_elems:
            child = self._parse_item(child_elem)
            if child:
                children.append(child)

        return Item(
            identifier=identifier,
            title=title,
            identifierref=identifierref,
            parameters=parameters,
            children=children,
            prerequisites=prerequisites,
            max_time_allowed=max_time_allowed,
            time_limit_action=time_limit_action,
            data_from_lms=data_from_lms,
            completion_threshold=float(completion_threshold)
            if completion_threshold
            else None,
            objectives=objectives,
            sequencing_rules=sequencing_rules,
        )

    def _parse_objectives(self, item_elem) -> list[dict]:
        objectives = []

        objectives_elem = self._find_element(
            ".//imsss:objectives", ".//objectives", item_elem
        )
        if objectives_elem is not None:
            primary_obj = self._find_element(
                ".//imsss:primaryObjective", ".//primaryObjective", objectives_elem
            )
            if primary_obj is not None:
                obj = {
                    "type": "primary",
                    "objectiveID": primary_obj.get("objectiveID", ""),
                    "satisfiedByMeasure": primary_obj.get(
                        "satisfiedByMeasure", "false"
                    ).lower()
                    == "true",
                    "minNormalizedMeasure": primary_obj.get("minNormalizedMeasure"),
                }
                objectives.append(obj)

        return objectives

    def _parse_sequencing_rules(self, item_elem) -> list[SequencingRule]:
        rules = []

        sequencing_elem = self._find_element(
            ".//imsss:sequencing", ".//sequencing", item_elem
        )
        if sequencing_elem is not None:
            rules_elem = self._find_element(
                ".//imsss:sequencingRules", ".//sequencingRules", sequencing_elem
            )
            if rules_elem is not None:
                rule_elems = self._find_all_elements(
                    ".//imsss:sequencingRule", ".//sequencingRule", rules_elem
                )

                for rule_elem in rule_elems:
                    conditions_elem = self._find_element(
                        ".//imsss:ruleConditions", ".//ruleConditions", rule_elem
                    )
                    action_elem = self._find_element(
                        ".//imsss:ruleAction", ".//ruleAction", rule_elem
                    )

                    if conditions_elem is not None and action_elem is not None:
                        rule = SequencingRule(
                            condition_combination=conditions_elem.get(
                                "conditionCombination", "all"
                            ),
                            action=action_elem.get("action", ""),
                        )

                        condition_elems = self._find_all_elements(
                            ".//imsss:ruleCondition",
                            ".//ruleCondition",
                            conditions_elem,
                        )
                        for cond_elem in condition_elems:
                            condition = {
                                "condition": cond_elem.get("condition", ""),
                                "referencedObjective": cond_elem.get(
                                    "referencedObjective", ""
                                ),
                                "measureThreshold": cond_elem.get(
                                    "measureThreshold", ""
                                ),
                                "operator": cond_elem.get("operator", "noOp"),
                            }
                            rule.conditions.append(condition)

                        rules.append(rule)

        return rules

    def get_resources(self) -> list[Resource]:
        resources = []

        resources_elem = self._find_element(".//imscp:resources", ".//resources")

        if resources_elem is not None:
            res_elems = self._find_all_elements(
                ".//imscp:resource", ".//resource", resources_elem
            )

            for res_elem in res_elems:
                resource = self._parse_resource(res_elem)
                if resource:
                    resources.append(resource)

        return resources

    def _parse_resource(self, res_elem) -> Resource | None:
        identifier = res_elem.get("identifier", "")
        res_type = res_elem.get("type", "webcontent")

        # scormType lives in the ADL namespace; casing differs by edition
        # (scormType in 2004, scormtype in 1.2).
        adlcp_uri = self.NAMESPACES.get("adlcp", "")
        scorm_type = (
            res_elem.get(f"{{{adlcp_uri}}}scormType")
            or res_elem.get(f"{{{adlcp_uri}}}scormtype")
            or res_elem.get("scormType")
            or res_elem.get("scormtype")
        )

        href = res_elem.get("href")

        files = []
        file_elems = self._find_all_elements(".//imscp:file", ".//file", res_elem)
        for file_elem in file_elems:
            file_href = file_elem.get("href")
            if file_href:
                files.append(file_href)

        dependencies = []
        dependency_elems = self._find_all_elements(
            ".//imscp:dependency", ".//dependency", res_elem
        )
        for dep_elem in dependency_elems:
            identifierref = dep_elem.get("identifierref")
            if identifierref:
                dependencies.append(identifierref)

        xml_base = None
        for base_attr in [
            "{http://www.w3.org/XML/1998/namespace}base",
            "xml:base",
            "base",
        ]:
            xml_base = res_elem.get(base_attr)
            if xml_base:
                break

        metadata = {"type": res_type, "scorm_type": scorm_type, "xml:base": xml_base}

        return Resource(
            identifier=identifier,
            type=res_type,
            scorm_type=scorm_type,
            href=href,
            files=files,
            metadata=metadata,
            dependencies=dependencies,
        )

    def _find_element(self, ns_path: str, fallback_path: str, parent=None):
        if parent is None:
            parent = self.root

        if HAS_LXML:
            elem = parent.find(ns_path, self.NAMESPACES)
            if elem is None:
                elem = parent.find(fallback_path)
        else:
            elem = parent.find(ns_path, self.NAMESPACES)
            if elem is None:
                elem = parent.find(fallback_path)

        return elem

    def _find_all_elements(self, ns_path: str, fallback_path: str, parent=None):
        if parent is None:
            parent = self.root

        if HAS_LXML:
            elems = parent.findall(ns_path, self.NAMESPACES)
            if not elems:
                elems = parent.findall(fallback_path)
        else:
            elems = parent.findall(ns_path, self.NAMESPACES)
            if not elems:
                elems = parent.findall(fallback_path)

        return elems

    def _find_child_elements(self, ns_tag: str, fallback_tag: str, parent):
        children = []

        for child in parent:
            # lxml's Cython tags need str() coercion
            tag = str(child.tag) if callable(child.tag) else child.tag

            if isinstance(tag, str):
                if (
                    tag.endswith(fallback_tag)
                    or tag == f"{{{self.NAMESPACES.get('imscp', '')}}}{fallback_tag}"
                ):
                    children.append(child)

        return children

    def _find_text(self, ns_path: str, fallback_path: str, parent=None):
        elem = self._find_element(ns_path, fallback_path, parent)
        return elem.text if elem is not None else None


class RiseArticulateParser:
    def __init__(self, base_path: Path):
        self.base_path = base_path
        # l10nId -> HTML string, for localized Rise exports (empty otherwise).
        self.l10n_map: dict[str, str] = {}

    def is_rise_package(self, package) -> bool:
        rise_indicators = [
            "scormcontent/lib/rise/",
            "scormcontent/lib/mondrian/",
            "scormcontent/locales/und.js",
            "scormcontent/lib/lzwcompress.js",
        ]

        for resource in package.resources:
            for file_path in resource.files:
                if any(indicator in file_path for indicator in rise_indicators):
                    return True

        return False

    def extract_rise_content(self, package) -> RiseCourse | None:
        encoded_data = self._find_encoded_course_data(package)
        if not encoded_data:
            return None

        try:
            course_data = self._decompress_rise_data(encoded_data)
            self.l10n_map = self._build_l10n_map(course_data)
            return self._parse_rise_course(course_data)
        except Exception as e:
            print(f"Error decompressing Rise content: {e}")
            return None

    def _build_l10n_map(self, data: dict) -> dict[str, str]:
        """Build the l10nId -> string map for localized Rise exports.

        Localized exports keep block text out of the course tree, storing it
        under ``l10n.translations[<locale>]`` keyed by l10nId; blocks then hold
        ``{"l10nId": ...}`` references instead of inline HTML.
        """
        l10n = data.get("l10n")
        if not isinstance(l10n, dict):
            return {}

        translations = l10n.get("translations")
        if not isinstance(translations, dict):
            return {}

        locale_map = translations.get(l10n.get("defaultLocale"))
        if not isinstance(locale_map, dict):
            # default locale absent or unnamed; use the first available locale
            locale_map = next(
                (v for v in translations.values() if isinstance(v, dict)), {}
            )

        return locale_map

    def _resolve_text(self, value) -> str:
        """Resolve a Rise text value to a raw string.

        Inline text is a string; localized text is a ``{"l10nId": ...}``
        reference into the translation map.
        """
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            l10n_id = value.get("l10nId")
            if l10n_id:
                return self.l10n_map.get(l10n_id, "")
        return ""

    def _find_encoded_course_data(self, package) -> str | None:
        """Locate the base64-encoded course payload.

        Older Rise exports store it in a locales/*.js file; newer exports
        embed it directly in scormcontent/index.html via ``deserialize("...")``.
        """
        locale_file = self._find_locale_file(package)
        if locale_file:
            data = self._extract_compressed_data(locale_file)
            if data:
                return data

        return self._extract_embedded_data(package)

    def _find_locale_file(self, package) -> str | None:
        for resource in package.resources:
            for file_path in resource.files:
                if "locales/" in file_path and file_path.endswith(".js"):
                    return file_path
        return None

    def _find_index_html(self, package) -> str | None:
        for resource in package.resources:
            for file_path in resource.files:
                if file_path.endswith("scormcontent/index.html"):
                    return file_path
        return None

    def _extract_embedded_data(self, package) -> str | None:
        index_file = self._find_index_html(package)
        if not index_file:
            return None

        full_path = _resolve_within(self.base_path, index_file)
        if full_path is None or not full_path.exists():
            return None

        try:
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError as e:
            print(f"Error reading index file: {e}")
            return None

        match = re.search(r'deserialize\(\s*"([^"]+)"\s*\)', content)
        if match:
            return match.group(1)

        return None

    def _extract_compressed_data(self, locale_file: str) -> str | None:
        full_path = _resolve_within(self.base_path, locale_file)
        if full_path is None or not full_path.exists():
            return None

        try:
            with open(full_path, encoding="utf-8") as f:
                content = f.read()

            match = re.search(r'__resolveJsonp\([^,]+,\s*"([^"]+)"\)', content)
            if match:
                return match.group(1)

            return None

        except Exception as e:
            print(f"Error reading locale file: {e}")
            return None

    def _decompress_rise_data(self, base64_data: str) -> dict:
        try:
            decoded_bytes = base64.b64decode(base64_data)
            decoded_str = decoded_bytes.decode("utf-8")

            compressed_json = json.loads(decoded_str)

            # already-decompressed dict
            if isinstance(compressed_json, dict):
                return compressed_json

            # array form is LZW compressed
            if isinstance(compressed_json, list):
                decompressed_str = lzw_decompress(compressed_json)
                decompressed_json = json.loads(decompressed_str)

                if isinstance(decompressed_json, dict) and "__k" in decompressed_json:
                    return key_optimize_unpack(decompressed_json)

                return decompressed_json

            return {}

        except Exception as e:
            print(f"Error in decompression: {e}")
            return {}

    def _parse_rise_course(self, course_data: dict) -> RiseCourse:
        course_info = course_data.get("course", {})

        course = RiseCourse(
            id=course_info.get("id", ""),
            title=_clean_html(self._resolve_text(course_info.get("title")))
            or "Untitled Course",
            author=course_info.get("author", ""),
            color=course_info.get("color", ""),
            media=course_info.get("media", {}),
            fonts=course_info.get("fonts"),
        )

        lessons_data = course_info.get("lessons", [])
        for lesson_data in lessons_data:
            lesson = RiseLesson(
                id=lesson_data.get("id", ""),
                title=_clean_html(self._resolve_text(lesson_data.get("title")))
                or "Untitled Lesson",
                type=lesson_data.get("type", ""),
                icon=lesson_data.get("icon", ""),
                course_id=lesson_data.get("courseId"),
                items=lesson_data.get("items", []),
            )
            course.lessons.append(lesson)

        return course

    def extract_text_content(self, course: RiseCourse) -> str:
        text_parts = []

        text_parts.append(f"Course: {course.title}")

        for lesson in course.lessons:
            text_parts.append(f"\nLesson: {lesson.title}")

            lesson_text = self._extract_items_text(lesson.items)
            if lesson_text:
                text_parts.append(lesson_text)

        return "\n".join(text_parts)

    # Keys that hold human-readable prose across Rise block variants. Media
    # references (image/audio keys) live under other keys and are skipped.
    _TEXT_KEYS = ("heading", "paragraph", "title", "caption", "description", "name")

    def _extract_items_text(self, items: list[dict]) -> str:
        text_parts: list[str] = []
        self._collect_text(items, text_parts)
        return "\n".join(text_parts)

    def _collect_text(self, node, parts: list[str]) -> None:
        """Walk a block tree, collecting resolved prose from text-bearing keys.

        Rise blocks nest inconsistently (hotspots, flashcard front/back, quote
        author/body, columns), so recursion is more robust than per-type rules.
        Knowledge checks and charts keep dedicated handling to preserve their
        question/answer and label/value structure.
        """
        if isinstance(node, list):
            for element in node:
                self._collect_text(element, parts)
            return

        if not isinstance(node, dict):
            return

        if isinstance(node.get("answers"), list):
            self._collect_knowledge_check(node, parts)
            self._collect_text(node.get("items", []), parts)
            return

        if node.get("type") == "chart":
            self._collect_chart(node, parts)
            return

        for key in self._TEXT_KEYS:
            if key in node:
                cleaned = _clean_html(self._resolve_text(node[key]))
                if cleaned:
                    parts.append(cleaned)

        for key, value in node.items():
            if key not in self._TEXT_KEYS and isinstance(value, (dict, list)):
                self._collect_text(value, parts)

    def _collect_knowledge_check(self, node: dict, parts: list[str]) -> None:
        question = _clean_html(self._resolve_text(node.get("title")))
        if question:
            parts.append(f"Q: {question}")
        for answer in node.get("answers", []):
            answer_text = _clean_html(self._resolve_text(answer.get("title")))
            if answer_text:
                marker = " (correct)" if answer.get("correct") else ""
                parts.append(f"- {answer_text}{marker}")
        feedback = _clean_html(self._resolve_text(node.get("feedback")))
        if feedback:
            parts.append(f"Feedback: {feedback}")

    def _collect_chart(self, node: dict, parts: list[str]) -> None:
        title = _clean_html(self._resolve_text(node.get("title")))
        if title:
            parts.append(title)
        for entry in node.get("items", []):
            label = _clean_html(self._resolve_text(entry.get("type")))
            if label:
                parts.append(f"- {label}: {entry.get('value', '')}")


class ContentExtractor:
    def __init__(self, base_path: Path):
        self.base_path = base_path

    def extract_html_content_(self, html_path: str) -> dict[str, Any]:
        full_path = _resolve_within(self.base_path, html_path)
        if full_path is None or not full_path.exists():
            return {"text": "", "error": f"File not found: {html_path}"}

        try:
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                html_content = f.read()

            if HAS_BS4:
                soup = BeautifulSoup(html_content, "html.parser")

                for script in soup(["script", "style"]):
                    script.decompose()

                text = soup.get_text(separator=" ", strip=True)

                content = {
                    "text": text,
                    "title": soup.title.string if soup.title else "",
                    "headings": [
                        h.get_text(strip=True)
                        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
                    ],
                    "images": [img.get("src", "") for img in soup.find_all("img")],
                    "links": [a.get("href", "") for a in soup.find_all("a")],
                    "scripts": [
                        script.get("src", "")
                        for script in soup.find_all("script")
                        if script.get("src")
                    ],
                    "forms": self._extract_forms_bs4(soup),
                }
            else:
                parser = HTMLExtractor()
                parser.feed(html_content)
                content = parser.get_all_content()

            return content

        except Exception as e:
            return {"text": "", "error": f"Error parsing {html_path}: {str(e)}"}

    def _extract_forms_bs4(self, soup) -> list[dict]:
        forms = []

        for form in soup.find_all("form"):
            form_data = {
                "action": form.get("action", ""),
                "method": form.get("method", "get"),
                "inputs": [],
            }

            for input_elem in form.find_all(["input", "select", "textarea"]):
                input_data = {
                    "type": input_elem.get("type", input_elem.name),
                    "name": input_elem.get("name", ""),
                    "value": input_elem.get("value", ""),
                    "options": [],
                }

                if input_elem.name == "select":
                    input_data["options"] = [
                        opt.get_text(strip=True)
                        for opt in input_elem.find_all("option")
                    ]

                form_data["inputs"].append(input_data)

            forms.append(form_data)

        return forms

    def extract_javascript_content(self, js_path: str) -> dict[str, Any]:
        full_path = _resolve_within(self.base_path, js_path)
        if full_path is None or not full_path.exists():
            return {"error": f"File not found: {js_path}"}

        try:
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                js_content = f.read()

            content = {"has_scorm_api": "getAPI" in js_content or "SCORM" in js_content}

            return content

        except Exception as e:
            return {"error": f"Error parsing {js_path}: {str(e)}"}

    def extract_resource_content(
        self, resource: Resource, package: ScormPackage
    ) -> dict[str, Any]:
        content = {
            "identifier": resource.identifier,
            "type": resource.scorm_type or "unknown",
            "launch_url": resource.href,
            "content_files": [],
            "total_text": "",
            "media_files": [],
        }

        for file_path in resource.files:
            if file_path.endswith(".html") or file_path.endswith(".htm"):
                file_content = self.extract_html_content_(file_path)
                content["content_files"].append(
                    {"path": file_path, "type": "html", "content": file_content}
                )
                if file_content.get("text"):
                    content["total_text"] += (
                        f"\n\n[From {file_path}]\n{file_content['text']}"
                    )

            elif file_path.endswith(".js"):
                js_content = self.extract_javascript_content(file_path)
                content["content_files"].append(
                    {"path": file_path, "type": "javascript", "content": js_content}
                )

            elif any(
                file_path.endswith(ext)
                for ext in [".jpg", ".jpeg", ".png", ".gif", ".svg"]
            ):
                content["media_files"].append({"path": file_path, "type": "image"})

            elif any(
                file_path.endswith(ext) for ext in [".mp3", ".mp4", ".wav", ".ogg"]
            ):
                content["media_files"].append(
                    {"path": file_path, "type": "audio/video"}
                )

        # launch URL may not be in files
        if resource.href and resource.href not in resource.files:
            if resource.href.endswith(".html") or resource.href.endswith(".htm"):
                launch_content = self.extract_html_content_(resource.href)
                content["content_files"].insert(
                    0,
                    {"path": resource.href, "type": "html", "content": launch_content},
                )
                if launch_content.get("text"):
                    content["total_text"] = (
                        f"[From {resource.href}]\n{launch_content['text']}"
                        + content["total_text"]
                    )

        return content


class ScormParser:
    """SCORM parser with content extraction and Rise Articulate support."""

    def __init__(self):
        self.temp_dir = None
        self.rise_parser = None

    def parse_package(self, package_path: str) -> ScormPackage:
        package_path = Path(package_path)

        if not package_path.exists():
            raise FileNotFoundError(f"Package not found: {package_path}")

        self.temp_dir = tempfile.mkdtemp(prefix="scorm_")
        extracted_path = Path(self.temp_dir)

        try:
            with zipfile.ZipFile(package_path, "r") as zip_ref:
                _safe_extract(zip_ref, extracted_path)

            self.rise_parser = RiseArticulateParser(extracted_path)

            manifest_path = extracted_path / "imsmanifest.xml"
            if not manifest_path.exists():
                raise ManifestNotFoundError("imsmanifest.xml not found in package")

            parser = ScormManifestParser(str(manifest_path))
            metadata = parser.parse_metadata()

            version = metadata.get("schema_version", "1.2")
            edition = metadata.get("scorm_edition", version)

            organizations, default_org = parser.get_organizations()
            resources = parser.get_resources()

            package = ScormPackage(
                identifier=package_path.stem,
                version=version,
                title=metadata.get("title", "Untitled"),
                description=metadata.get("description"),
                metadata=metadata,
                organizations=organizations,
                resources=resources,
                manifest_path=str(manifest_path),
                extracted_path=str(extracted_path),
                default_organization=default_org,
                version_info={"edition": edition, "base_version": version},
            )

            return package

        except Exception as e:
            self.cleanup()
            raise ScormParsingError(f"Failed to parse package: {e}")

    def extract_all_content(self, package: ScormPackage) -> list[dict[str, Any]]:
        extractor = ContentExtractor(Path(package.extracted_path))
        content_list = []

        rise_content = self._extract_rise_content_if_available(package)

        if rise_content.get("is_rise_package"):
            # prioritize structured Rise content for Rise packages
            content_list.append(
                {
                    "identifier": "rise_course",
                    "type": "rise_articulate",
                    "title": rise_content.get("course_structure", {}).get(
                        "title", "Rise Course"
                    ),
                    "content": rise_content,
                    "total_text": rise_content.get("text_content", ""),
                    "rise_lessons": rise_content.get("course_structure", {}).get(
                        "lessons", []
                    ),
                }
            )

        item_map = {}
        for org in package.organizations:
            self._build_item_map(org.items, item_map)

        for resource in package.resources:
            if resource.scorm_type in ["sco", "asset"] or (
                not resource.scorm_type and resource.href
            ):
                content = extractor.extract_resource_content(resource, package)

                if resource.identifier in item_map:
                    content["title"] = item_map[resource.identifier]["title"]
                    content["item_data"] = item_map[resource.identifier]
                else:
                    content["title"] = resource.identifier

                content_list.append(content)

        return content_list

    def _extract_rise_content_if_available(self, package) -> dict[str, Any]:
        if not self.rise_parser or not self.rise_parser.is_rise_package(package):
            return {}

        rise_course = self.rise_parser.extract_rise_content(package)
        if not rise_course:
            return {}

        return {
            "is_rise_package": True,
            "rise_course": asdict(rise_course),
            "text_content": self.rise_parser.extract_text_content(rise_course),
            "course_structure": {
                "title": rise_course.title,
                "author": rise_course.author,
                "color": rise_course.color,
                "lessons_count": len(rise_course.lessons),
                "lessons": [
                    {
                        "id": lesson.id,
                        "title": lesson.title,
                        "type": lesson.type,
                        "icon": lesson.icon,
                        "items_count": len(lesson.items),
                    }
                    for lesson in rise_course.lessons
                ],
            },
        }

    def _build_item_map(self, items: list[Item], item_map: dict):
        for item in items:
            if item.identifierref:
                item_map[item.identifierref] = {
                    "title": item.title,
                    "identifier": item.identifier,
                    "prerequisites": item.prerequisites,
                    "max_time_allowed": item.max_time_allowed,
                    "objectives": item.objectives,
                    "sequencing_rules": [
                        asdict(rule) for rule in item.sequencing_rules
                    ],
                }

            self._build_item_map(item.children, item_map)

    def export_to_json(self, package: ScormPackage, output_path: str) -> None:
        content = self.extract_all_content(package)
        rise_content = self._extract_rise_content_if_available(package)

        output = {
            "package_info": {
                "identifier": package.identifier,
                "scorm_version": package.version,
                "scorm_edition": package.version_info.get("edition", package.version),
                "title": package.title,
                "description": package.description,
                "default_organization": package.default_organization,
                "metadata": package.metadata,
                "is_rise_package": rise_content.get("is_rise_package", False),
            },
            "content": content,
            "rise_content": rise_content,
            "structure": {
                "organizations": [
                    {
                        "identifier": org.identifier,
                        "title": org.title,
                        "structure": org.structure,
                        "objectives_global": org.objectives_global_to_system,
                        "items": self._items_to_dict(org.items),
                    }
                    for org in package.organizations
                ]
            },
            "resources": [
                {
                    "identifier": res.identifier,
                    "type": res.type,
                    "scorm_type": res.scorm_type,
                    "href": res.href,
                    "files": res.files,
                    "dependencies": res.dependencies,
                    "metadata": res.metadata,
                }
                for res in package.resources
            ],
            "statistics": {
                "total_scos": len(
                    [r for r in package.resources if r.scorm_type == "sco"]
                ),
                "total_assets": len(
                    [r for r in package.resources if r.scorm_type == "asset"]
                ),
                "total_organizations": len(package.organizations),
                "total_items": sum(
                    self._count_items(org.items) for org in package.organizations
                ),
                "has_sequencing": any(
                    item.sequencing_rules
                    for org in package.organizations
                    for item in self._flatten_items(org.items)
                ),
                "has_prerequisites": any(
                    item.prerequisites
                    for org in package.organizations
                    for item in self._flatten_items(org.items)
                ),
                "is_rise_articulate": rise_content.get("is_rise_package", False),
                "rise_lessons_count": len(
                    rise_content.get("course_structure", {}).get("lessons", [])
                ),
            },
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

    def _items_to_dict(self, items: list[Item]) -> list[dict]:
        return [
            {
                "identifier": item.identifier,
                "title": item.title,
                "identifierref": item.identifierref,
                "parameters": item.parameters,
                "prerequisites": item.prerequisites,
                "max_time_allowed": item.max_time_allowed,
                "time_limit_action": item.time_limit_action,
                "data_from_lms": item.data_from_lms,
                "completion_threshold": item.completion_threshold,
                "objectives": item.objectives,
                "sequencing_rules": [asdict(rule) for rule in item.sequencing_rules],
                "children": self._items_to_dict(item.children),
            }
            for item in items
        ]

    def _count_items(self, items: list[Item]) -> int:
        count = len(items)
        for item in items:
            count += self._count_items(item.children)
        return count

    def _flatten_items(self, items: list[Item]) -> list[Item]:
        flat = []
        for item in items:
            flat.append(item)
            flat.extend(self._flatten_items(item.children))
        return flat

    def cleanup(self):
        if self.temp_dir and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python _scorm_parser.py <scorm_package.zip>")
        sys.exit(1)

    with ScormParser() as parser:
        try:
            package = parser.parse_package(sys.argv[1])

            print(f"Package: {package.title}")
            print(
                f"SCORM Edition: {package.version_info.get('edition', package.version)}"
            )
            print(f"Default Organization: {package.default_organization}")

            rise_content = parser._extract_rise_content_if_available(package)
            if rise_content.get("is_rise_package"):
                print("✓ Rise Articulate package detected!")
                print(f"Course: {rise_content['course_structure']['title']}")
                print(f"Author: {rise_content['course_structure']['author']}")
                print(f"Lessons: {rise_content['course_structure']['lessons_count']}")

                for lesson in rise_content["course_structure"]["lessons"]:
                    print(f"  - {lesson['title']} ({lesson['items_count']} items)")

            output_file = f"{package.identifier}.json"
            parser.export_to_json(package, output_file)
            print(f"\nContent exported to: {output_file}")

            content = parser.extract_all_content(package)

            if rise_content.get("is_rise_package"):
                rise_text_length = len(rise_content.get("text_content", ""))
                print("\nRise Content Summary:")
                print(f"- Text extracted: {rise_text_length:,} characters")
                print("- First 200 characters:")
                print(f"  {rise_content.get('text_content', '')[:200]}...")

            total_text_length = sum(len(c.get("total_text", "")) for c in content)
            print("\nTotal Content Summary:")
            print(f"- Total resources: {len(content)}")
            print(f"- Total text extracted: {total_text_length:,} characters")

        except ScormParsingError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")
            import traceback

            traceback.print_exc()
