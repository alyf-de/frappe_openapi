import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import frappe

from frappe_openapi.openapi import (
	build_doctype_spec,
	build_method_spec,
	build_security_schemes,
	default_security_requirements,
	with_base_openapi_fields,
)
from frappe_openapi.refs import (
	generated_app_document_path,
	generated_manifest_path,
	generated_site_document_path,
	unquote_segment,
)
from frappe_openapi.registry import get_doctype_names, get_installed_apps, get_whitelisted_method_records
from frappe_openapi.schema import build_schema_document
from frappe_openapi.storage import write_app_bundle, write_manifest

SCHEMA_PATH_PREFIX = "/openapi/schemas/"
SCHEMA_PATH_SUFFIX = ".schema.json"


def generate_app_bundles(apps: list[str] | None = None, output: str | Path | None = None) -> dict:
	generated_at = now_utc()
	selected_apps = validate_apps(apps or get_installed_apps())
	app_artifacts = []

	for app in selected_apps:
		bundle = build_app_bundle(app, generated_at=generated_at)
		path = write_app_bundle(app, bundle, output)
		app_artifacts.append({
			"app": app,
			"url": generated_app_document_path(app),
			"size_bytes": path.stat().st_size,
		})

	manifest = build_manifest(app_artifacts, generated_at=generated_at)
	manifest_path = write_manifest(manifest, output)

	return {
		"apps": app_artifacts,
		"manifest": manifest,
		"manifest_path": str(manifest_path),
		"output": str(manifest_path.parent),
	}


def build_app_bundle(app: str, generated_at: str | None = None) -> dict:
	validate_apps([app])
	generated_at = generated_at or now_utc()
	doctypes = get_doctype_names(app=app)
	methods = get_whitelisted_method_records(app=app)
	standalone_methods = [
		method["name"]
		for method in methods
		if method.get("kind") != "doctype"
	]
	paths = {}
	tags = set()
	schema_queue = list(doctypes)

	for doctype in doctypes:
		doctype_spec = build_doctype_spec(doctype)
		collect_schema_doctypes(doctype_spec.get("paths", {}), schema_queue)
		paths.update(rewrite_schema_refs(doctype_spec.get("paths", {})))
		collect_tags(doctype_spec.get("paths", {}), tags)

	for method in standalone_methods:
		method_spec = build_method_spec(method)
		collect_schema_doctypes(method_spec.get("paths", {}), schema_queue)
		paths.update(rewrite_schema_refs(method_spec.get("paths", {})))
		collect_tags(method_spec.get("paths", {}), tags)

	schemas = build_component_schemas(schema_queue)

	return with_base_openapi_fields(
		generated_app_document_path(app),
		f"{app} Generated API",
		{
			"summary": "Generated SDK-ready OpenAPI bundle for this Frappe app.",
			"paths": dict(sorted(paths.items())),
			"components": {
				"securitySchemes": build_security_schemes(),
				"schemas": dict(sorted(schemas.items())),
			},
			"security": default_security_requirements(),
			"tags": [{"name": tag} for tag in sorted(tags)],
			"x-frappe-app": app,
			"x-frappe-generated-at": generated_at,
			"x-frappe-generated-source": "frappe_openapi.generator.build_app_bundle",
			"x-frappe-doctypes": doctypes,
			"x-frappe-methods": [method["name"] for method in methods],
			"x-frappe-standalone-methods": standalone_methods,
		},
	)


def build_site_bundle(generated_at: str | None = None) -> dict:
	generated_at = generated_at or now_utc()
	apps = get_installed_apps()
	paths = {}
	tags = set()
	schemas = {}

	for app in apps:
		bundle = build_app_bundle(app, generated_at=generated_at)
		paths.update(bundle.get("paths", {}))
		schemas.update(bundle.get("components", {}).get("schemas", {}))
		for tag in bundle.get("tags", []):
			tags.add(tag["name"])

	return with_base_openapi_fields(
		generated_site_document_path(),
		"Generated Frappe Site API",
		{
			"summary": "Generated SDK-ready OpenAPI bundle for all installed Frappe apps on this site.",
			"paths": dict(sorted(paths.items())),
			"components": {
				"securitySchemes": build_security_schemes(),
				"schemas": dict(sorted(schemas.items())),
			},
			"security": default_security_requirements(),
			"tags": [{"name": tag} for tag in sorted(tags)],
			"x-frappe-apps": apps,
			"x-frappe-generated-at": generated_at,
			"x-frappe-generated-source": "frappe_openapi.generator.build_site_bundle",
		},
	)


def build_manifest(app_artifacts: list[dict] | None = None, generated_at: str | None = None) -> dict:
	generated_at = generated_at or now_utc()
	app_artifacts = app_artifacts or []

	return {
		"generated_at": generated_at,
		"site": frappe.local.site,
		"manifest_url": generated_manifest_path(),
		"apps": {
			artifact["app"]: {
				"url": artifact["url"],
				"size_bytes": artifact.get("size_bytes"),
				"generated_at": generated_at,
			}
			for artifact in app_artifacts
		},
		"installed_apps": {
			app: {
				"version": get_app_version(app),
			}
			for app in get_installed_apps()
		},
	}


def build_component_schemas(doctypes: list[str]) -> dict:
	components = {}
	seen = set()
	index = 0

	while index < len(doctypes):
		doctype = doctypes[index]
		index += 1
		if doctype in seen:
			continue
		seen.add(doctype)

		schema_document = build_schema_document(doctype)
		definitions = schema_document.get("$defs", {})
		collect_schema_doctypes(definitions, doctypes)
		for schema_name, schema in definitions.items():
			components[schema_component_name(doctype, schema_name)] = rewrite_schema_refs(schema)

	return components


def rewrite_schema_refs(value: Any) -> Any:
	if isinstance(value, dict):
		rewritten = {}
		for key, item in value.items():
			if key == "$ref" and isinstance(item, str) and (schema_ref := parse_schema_ref(item)):
				doctype, schema_name = schema_ref
				rewritten[key] = f"#/components/schemas/{schema_component_name(doctype, schema_name)}"
			else:
				rewritten[key] = rewrite_schema_refs(item)
		return rewritten

	if isinstance(value, list):
		return [rewrite_schema_refs(item) for item in value]

	return value


def collect_schema_doctypes(value: Any, doctypes: list[str]) -> None:
	if isinstance(value, dict):
		ref = value.get("$ref")
		if isinstance(ref, str) and (schema_ref := parse_schema_ref(ref)):
			doctype = schema_ref[0]
			if doctype not in doctypes:
				doctypes.append(doctype)
		for item in value.values():
			collect_schema_doctypes(item, doctypes)
	elif isinstance(value, list):
		for item in value:
			collect_schema_doctypes(item, doctypes)


def collect_tags(paths: dict, tags: set[str]) -> None:
	for path_item in paths.values():
		for operation in path_item.values():
			if isinstance(operation, dict):
				tags.update(operation.get("tags", []))


def parse_schema_ref(ref: str) -> tuple[str, str] | None:
	document_path, separator, schema_name = ref.partition("#/$defs/")
	if not separator:
		return None

	path = urlparse(document_path).path
	if not path.startswith(SCHEMA_PATH_PREFIX) or not path.endswith(SCHEMA_PATH_SUFFIX):
		return None

	doctype = path.removeprefix(SCHEMA_PATH_PREFIX).removesuffix(SCHEMA_PATH_SUFFIX)
	return unquote_segment(doctype), schema_name


def schema_component_name(doctype: str, schema_name: str) -> str:
	return f"{normalize_component_name(doctype)}_{normalize_component_name(schema_name)}"


def normalize_component_name(value: str) -> str:
	normalized = re.sub(r"[^A-Za-z0-9.-]+", "_", value).strip("_")
	return normalized or "Schema"


def validate_apps(apps: list[str]) -> list[str]:
	installed_apps = set(get_installed_apps())
	missing_apps = [app for app in apps if app not in installed_apps]
	if missing_apps:
		raise ValueError(f"App not installed on this site: {', '.join(missing_apps)}")
	return apps


def get_app_version(app: str) -> str | None:
	try:
		return frappe.get_attr(f"{app}.__version__")
	except Exception:
		return None


def now_utc() -> str:
	return datetime.now(UTC).isoformat().replace("+00:00", "Z")
