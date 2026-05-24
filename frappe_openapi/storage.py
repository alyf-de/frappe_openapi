import json
from pathlib import Path

import frappe
from werkzeug.exceptions import NotFound

GENERATED_OPENAPI_DIR = ("private", "openapi")
APP_BUNDLE_DIR = "apps"
MANIFEST_FILENAME = "manifest.json"


def get_storage_root(output: str | Path | None = None) -> Path:
	if output:
		return Path(output).expanduser().resolve()

	return Path(frappe.get_site_path(*GENERATED_OPENAPI_DIR))


def get_manifest_path(output: str | Path | None = None) -> Path:
	return get_storage_root(output) / MANIFEST_FILENAME


def get_app_bundle_dir(output: str | Path | None = None) -> Path:
	return get_storage_root(output) / APP_BUNDLE_DIR


def get_app_bundle_path(app: str, output: str | Path | None = None) -> Path:
	validate_app_name(app)
	return get_app_bundle_dir(output) / f"{app}.json"


def write_manifest(manifest: dict, output: str | Path | None = None) -> Path:
	return write_json_document(manifest, get_manifest_path(output))


def write_app_bundle(app: str, bundle: dict, output: str | Path | None = None) -> Path:
	return write_json_document(bundle, get_app_bundle_path(app, output))


def read_manifest() -> dict:
	return read_json_document(get_manifest_path())


def read_app_bundle(app: str) -> dict:
	return read_json_document(get_app_bundle_path(app))


def write_json_document(document: dict, path: Path) -> Path:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
	return path


def read_json_document(path: Path) -> dict:
	if not path.is_file():
		raise NotFound

	return json.loads(path.read_text())


def validate_app_name(app: str) -> None:
	if not app or not app.replace("_", "").isalnum():
		raise NotFound
