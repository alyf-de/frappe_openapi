import re
from urllib.parse import quote, unquote, urlparse

import frappe

OPENAPI_VERSION = "3.2.0"
OPENAPI_JSON_SCHEMA_DIALECT = "https://spec.openapis.org/oas/3.1/dialect/base"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_PATH_PREFIX = "/openapi/schemas/"
SCHEMA_PATH_SUFFIX = ".schema.json"


def absolute_url(path: str) -> str:
	return frappe.utils.get_url(path)


def quote_segment(value: str) -> str:
	return quote(value, safe="")


def unquote_segment(value: str) -> str:
	return unquote(value)


def json_pointer_token(value: str) -> str:
	return value.replace("~", "~0").replace("/", "~1")


def json_pointer_fragment(value: str) -> str:
	return quote(json_pointer_token(value), safe="~")


def doctype_document_path(doctype: str) -> str:
	return f"/openapi/doctypes/{quote_segment(doctype)}.json"


def schema_document_path(doctype: str) -> str:
	return f"/openapi/schemas/{quote_segment(doctype)}.schema.json"


def app_document_path(app: str) -> str:
	return f"/openapi/apps/{quote_segment(app)}.json"


def module_document_path(app: str, module: str) -> str:
	return f"/openapi/modules/{quote_segment(app)}/{quote_segment(module)}.json"


def method_document_path(method: str) -> str:
	return f"/openapi/methods/{quote_segment(method)}.json"


def generated_manifest_path() -> str:
	return "/openapi/generated/manifest.json"


def generated_app_document_path(app: str) -> str:
	return f"/openapi/generated/apps/{quote_segment(app)}.json"


def generated_site_document_path() -> str:
	return "/openapi/generated/site.json"


def auth_document_path() -> str:
	return "/openapi/auth.json"


def doctype_schema_ref(doctype: str, schema_name: str) -> str:
	return f"{schema_document_path(doctype)}#/$defs/{schema_name}"


def parse_doctype_schema_ref(ref: str) -> tuple[str, str] | None:
	document_path, separator, schema_name = ref.partition("#/$defs/")
	if not separator:
		return None

	path = urlparse(document_path).path
	if not path.startswith(SCHEMA_PATH_PREFIX) or not path.endswith(SCHEMA_PATH_SUFFIX):
		return None

	doctype = path.removeprefix(SCHEMA_PATH_PREFIX).removesuffix(SCHEMA_PATH_SUFFIX)
	return unquote_segment(doctype), schema_name


def component_schema_ref(doctype: str, schema_name: str) -> str:
	return f"#/components/schemas/{schema_component_name(doctype, schema_name)}"


def schema_component_name(doctype: str, schema_name: str) -> str:
	return f"{normalize_component_name(doctype)}_{normalize_component_name(schema_name)}"


def normalize_component_name(value: str) -> str:
	normalized = re.sub(r"[^A-Za-z0-9.-]+", "_", value).strip("_")
	return normalized or "Schema"


def doctype_path_item_ref(doctype: str, path: str) -> str:
	return f"{doctype_document_path(doctype)}#/paths/{json_pointer_fragment(path)}"


def api_doctype_path(doctype: str) -> str:
	return f"/api/v2/document/{doctype}"


def api_doctype_name_path(doctype: str) -> str:
	return f"{api_doctype_path(doctype)}/{{name}}"


def api_single_doctype_path(doctype: str) -> str:
	return f"{api_doctype_path(doctype)}/{doctype}"
