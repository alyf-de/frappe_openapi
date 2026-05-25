import ast
import inspect
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import frappe
from frappe.model.base_document import get_controller
from frappe.modules.utils import get_doctype_app_map
from frappe.utils.caching import site_cache

REGISTRY_CACHE_TTL = 300
DEFAULT_WHITELIST_HTTP_METHODS = ["POST"]
OPENAPI_HTTP_METHODS = {"GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"}
DOC_METHOD_HTTP_METHODS = {"GET", "POST"}


@site_cache(ttl=REGISTRY_CACHE_TTL)
def get_installed_apps() -> list[str]:
	return sorted(frappe.get_installed_apps())


@site_cache(ttl=REGISTRY_CACHE_TTL)
def get_doctype_records(
	app: str | None = None,
	module: str | None = None,
	include_child_tables: bool = True,
) -> list[dict]:
	filters = {}
	if module:
		filters["module"] = module
	if not include_child_tables:
		filters["istable"] = 0

	doctypes = frappe.get_all(
		"DocType",
		fields=["name", "module", "custom", "issingle", "istable", "modified"],
		filters=filters,
		order_by="name",
	)

	if not app:
		return doctypes

	app_map = get_doctype_app_map()
	return [doctype for doctype in doctypes if app_map.get(doctype.name) == app]


def get_doctype_names(
	app: str | None = None,
	module: str | None = None,
	include_child_tables: bool = True,
) -> list[str]:
	return [
		doctype.name
		for doctype in get_doctype_records(
			app=app,
			module=module,
			include_child_tables=include_child_tables,
		)
	]


def get_modules_by_app(app: str) -> dict[str, list[str]]:
	modules = defaultdict(list)
	for doctype in get_doctype_records(app=app):
		modules[doctype.module].append(doctype.name)

	return dict(sorted(modules.items()))


def get_app_for_doctype(doctype: str) -> str | None:
	return get_doctype_app_map().get(doctype)


@site_cache(ttl=REGISTRY_CACHE_TTL)
def get_static_whitelisted_methods(app: str | None = None) -> list[str]:
	return sorted(get_static_whitelisted_method_metadata(app=app))


@site_cache(ttl=REGISTRY_CACHE_TTL)
def get_static_whitelisted_method_metadata(app: str | None = None) -> dict[str, dict]:
	apps = [app] if app else get_installed_apps()
	methods = {}

	for app_name in apps:
		app_path = Path(frappe.get_app_path(app_name))
		classification_map = get_method_classification_map(app_name)
		for file_path in app_path.rglob("*.py"):
			if should_skip_python_file(file_path):
				continue

			module = get_module_path(app_name, app_path, file_path)
			classification = classify_method_file(app_name, app_path, file_path, classification_map)
			for method in get_module_level_whitelisted_functions(file_path):
				methods[f"{module}.{method['name']}"] = {
					"http_methods": method["http_methods"],
					"allow_guest": method["allow_guest"],
					**classification,
				}

	return dict(sorted(methods.items()))


def get_whitelisted_method_records(
	app: str | None = None,
	module: str | None = None,
	doctype: str | None = None,
	kind: str | None = None,
) -> list[dict]:
	records = []
	for method, metadata in get_static_whitelisted_method_metadata(app=app).items():
		if module is not None and metadata.get("module") != module:
			continue
		if doctype is not None and metadata.get("doctype") != doctype:
			continue
		if kind is not None and metadata.get("kind") != kind:
			continue
		records.append({"name": method, **metadata})

	return sorted(records, key=lambda method: method["name"])


def get_whitelisted_methods(
	app: str | None = None,
	module: str | None = None,
	doctype: str | None = None,
	kind: str | None = None,
) -> list[str]:
	return [
		method["name"]
		for method in get_whitelisted_method_records(
			app=app,
			module=module,
			doctype=doctype,
			kind=kind,
		)
	]


def get_whitelisted_method_metadata(method: str) -> dict:
	metadata = get_static_whitelisted_method_metadata().get(method)
	if not metadata:
		return {
			"http_methods": DEFAULT_WHITELIST_HTTP_METHODS,
			"allow_guest": False,
		}

	return {
		"http_methods": metadata["http_methods"],
		"allow_guest": metadata.get("allow_guest", False),
	}


def get_whitelisted_method_http_methods(method: str) -> list[str]:
	return get_whitelisted_method_metadata(method)["http_methods"]


def get_whitelisted_method_allow_guest(method: str) -> bool:
	return get_whitelisted_method_metadata(method)["allow_guest"]


@site_cache(ttl=REGISTRY_CACHE_TTL)
def get_doctype_whitelisted_methods(doctype: str) -> list[dict]:
	try:
		controller = get_controller(doctype)
	except Exception:
		return []
	if controller.__module__ == "frappe.model.document":
		return []

	methods = []
	source_file = inspect.getsourcefile(controller)
	if not source_file:
		return []

	for method in get_controller_whitelisted_functions(Path(source_file), controller.__name__):
		allowed_methods = get_allowed_doc_method_http_methods(method["http_methods"])
		if not allowed_methods:
			continue

		method_obj = getattr(controller, method["name"])
		method_obj = getattr(method_obj, "__func__", method_obj)

		methods.append({
			"name": method["name"],
			"dotted_path": f"{controller.__module__}.{controller.__qualname__}.{method['name']}",
			"http_methods": allowed_methods,
			"allow_guest": method["allow_guest"],
			"method_obj": method_obj,
		})

	return sorted(methods, key=lambda method: method["name"])


def get_allowed_doc_method_http_methods(http_methods: Iterable[str]) -> list[str]:
	return [
		method
		for method in normalize_http_methods(http_methods)
		if method in DOC_METHOD_HTTP_METHODS
	]


def get_method_classification_map(app: str) -> dict:
	module_by_folder = {frappe.scrub(module): module for module in get_modules_by_app(app)}
	doctype_by_folder = {
		(frappe.scrub(doctype.module), frappe.scrub(doctype.name)): doctype.name
		for doctype in get_doctype_records(app=app)
	}
	return {
		"module_by_folder": module_by_folder,
		"doctype_by_folder": doctype_by_folder,
	}


def classify_method_file(app: str, app_path: Path, file_path: Path, classification_map: dict) -> dict:
	relative_path = file_path.relative_to(app_path).with_suffix("")
	parts = relative_path.parts[:-1] if relative_path.name == "__init__" else relative_path.parts
	module_folder = parts[0] if parts else ""
	module = classification_map["module_by_folder"].get(module_folder)

	if len(parts) >= 3 and parts[1] == "doctype":
		doctype = classification_map["doctype_by_folder"].get((module_folder, parts[2]))
		if doctype:
			return {
				"app": app,
				"module": module,
				"doctype": doctype,
				"kind": "doctype",
			}

	if module:
		return {
			"app": app,
			"module": module,
			"doctype": None,
			"kind": "module",
		}

	return {
		"app": app,
		"module": None,
		"doctype": None,
		"kind": "app",
	}


def should_skip_python_file(file_path: Path) -> bool:
	return file_path.name.startswith("test_") or "tests" in file_path.parts


def get_module_path(app: str, app_path: Path, file_path: Path) -> str:
	relative_path = file_path.relative_to(app_path).with_suffix("")
	if relative_path.name == "__init__":
		parts = relative_path.parts[:-1]
	else:
		parts = relative_path.parts

	return ".".join((app, *parts))


def get_module_level_whitelisted_functions(file_path: Path) -> list[dict]:
	try:
		tree = ast.parse(file_path.read_text(), filename=str(file_path))
	except SyntaxError:
		return []

	methods = []
	for node in tree.body:
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			metadata = get_whitelist_decorator_metadata(node)
			if metadata:
				methods.append({
					"name": node.name,
					**metadata,
				})

	return methods


def get_controller_whitelisted_functions(file_path: Path, class_name: str) -> list[dict]:
	try:
		tree = ast.parse(file_path.read_text(), filename=str(file_path))
	except SyntaxError:
		return []

	for node in tree.body:
		if isinstance(node, ast.ClassDef) and node.name == class_name:
			methods = []
			for item in node.body:
				if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue
				metadata = get_whitelist_decorator_metadata(item)
				if metadata:
					methods.append({
						"name": item.name,
						**metadata,
					})
			return methods

	return []


def get_whitelist_decorator_metadata(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
	for decorator in node.decorator_list:
		decorator_func = decorator.func if isinstance(decorator, ast.Call) else decorator
		if is_whitelist_decorator(decorator_func):
			return get_decorator_metadata(decorator)

	return {}


def get_decorator_metadata(decorator) -> dict:
	if not isinstance(decorator, ast.Call):
		return {
			"http_methods": DEFAULT_WHITELIST_HTTP_METHODS,
			"allow_guest": False,
		}

	http_methods = DEFAULT_WHITELIST_HTTP_METHODS
	allow_guest = False
	for keyword in decorator.keywords:
		if keyword.arg == "methods":
			http_methods = extract_http_methods(keyword.value) or DEFAULT_WHITELIST_HTTP_METHODS
		if keyword.arg == "allow_guest":
			allow_guest = extract_allow_guest(keyword.value)

	return {
		"http_methods": http_methods,
		"allow_guest": allow_guest,
	}


def extract_allow_guest(node) -> bool:
	if not isinstance(node, ast.Constant):
		return False

	value = node.value
	return value is True or (type(value) is int and value == 1)


def extract_http_methods(node) -> list[str]:
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return normalize_http_methods([node.value])

	if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
		methods = []
		for item in node.elts:
			if isinstance(item, ast.Constant) and isinstance(item.value, str):
				methods.append(item.value)
		return normalize_http_methods(methods)

	return []


def normalize_http_methods(methods: Iterable[str]) -> list[str]:
	normalized = []
	for method in methods:
		http_method = method.upper()
		if http_method in OPENAPI_HTTP_METHODS and http_method not in normalized:
			normalized.append(http_method)

	return normalized


def is_whitelist_decorator(decorator) -> bool:
	if isinstance(decorator, ast.Attribute):
		return decorator.attr == "whitelist" and isinstance(decorator.value, ast.Name) and decorator.value.id == "frappe"

	return isinstance(decorator, ast.Name) and decorator.id == "whitelist"
