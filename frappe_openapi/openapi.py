import inspect
from typing import get_type_hints

import frappe
from frappe.utils.caching import redis_cache
from werkzeug.exceptions import NotFound

from frappe_openapi.refs import (
	JSON_SCHEMA_DIALECT,
	OPENAPI_JSON_SCHEMA_DIALECT,
	OPENAPI_VERSION,
	absolute_url,
	api_doctype_name_path,
	api_doctype_path,
	app_document_path,
	auth_document_path,
	doctype_document_path,
	doctype_schema_ref,
	method_document_path,
	module_document_path,
	quote_segment,
	schema_document_path,
	unquote_segment,
)
from frappe_openapi.registry import (
	get_app_for_doctype,
	get_doctype_names,
	get_doctype_records,
	get_doctype_whitelisted_methods,
	get_installed_apps,
	get_modules_by_app,
	get_whitelisted_method_allow_guest,
	get_whitelisted_method_http_methods,
	get_whitelisted_method_records,
	get_whitelisted_methods,
)
from frappe_openapi.schema import (
	build_schema_document,
	frappe_datetime_schema,
	python_type_to_schema,
)
from frappe_openapi.settings import has_openapi_spec_access, require_openapi_spec_access
from frappe_openapi.storage import read_app_bundle, read_manifest

SPEC_CACHE_TTL = 300
DOCTYPE_OPERATION_GROUPS = {
	"crud": "CRUD",
	"standard": "Standard RPC",
	"controller": "Controller RPC",
	"file": "File-level RPC",
}
DOCTYPE_OPERATION_DESCRIPTIONS = {
	"crud": "List, create, read, update, and delete {doctype} documents.",
	"standard": "Read metadata, count documents, and prepare copied {doctype} documents.",
	"controller": "Run whitelisted {doctype} controller methods against an existing document.",
	"file": "Run whitelisted functions defined in the {doctype} DocType module.",
}


def get_document(path: str) -> dict:
	require_openapi_spec_access()

	path = path.strip("/")
	if path == "openapi.json":
		return build_root_spec()
	if path == "openapi/auth.json":
		return build_auth_spec()
	if path == "openapi/methods.json":
		return build_methods_index_spec()
	if path == "openapi/search-index.json":
		return build_search_index()
	if path == "openapi/generated/manifest.json":
		return read_manifest()

	if path.startswith("openapi/generated/apps/") and path.endswith(".json"):
		app = unquote_json_name(path.removeprefix("openapi/generated/apps/"))
		return read_app_bundle(app)

	if path.startswith("openapi/apps/") and path.endswith(".json"):
		app = unquote_json_name(path.removeprefix("openapi/apps/"))
		return build_app_spec(app)

	if path.startswith("openapi/modules/") and path.endswith(".json"):
		parts = path.removeprefix("openapi/modules/").removesuffix(".json").split("/", 1)
		if len(parts) != 2:
			raise NotFound
		app, module = [unquote_segment(part) for part in parts]
		return build_module_spec(app, module)

	if path.startswith("openapi/doctypes/") and path.endswith(".json"):
		doctype = unquote_json_name(path.removeprefix("openapi/doctypes/"))
		return build_doctype_spec(doctype)

	if path.startswith("openapi/schemas/") and path.endswith(".schema.json"):
		doctype = unquote_segment(path.removeprefix("openapi/schemas/").removesuffix(".schema.json"))
		return build_schema_document(doctype)

	if path.startswith("openapi/methods/") and path.endswith(".json"):
		method = unquote_json_name(path.removeprefix("openapi/methods/"))
		return build_method_spec(method)

	raise NotFound


def unquote_json_name(value: str) -> str:
	return unquote_segment(value.removesuffix(".json"))


def require_generated_openapi_access() -> None:
	require_openapi_spec_access()


def has_generated_openapi_access(user: str | None = None) -> bool:
	return has_openapi_spec_access(user)


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_root_spec() -> dict:
	apps = get_installed_apps()
	return with_base_openapi_fields(
		"/openapi.json",
		"Frappe OpenAPI",
		{
			"summary": "Generic OpenAPI description for Frappe API v2, plus links to installed app documents.",
			"paths": build_generic_crud_paths(),
			"components": {
				"schemas": build_generic_crud_schemas(),
				"securitySchemes": build_security_schemes(),
			},
			"security": default_security_requirements(),
			"tags": [
				{"name": "Documents", "description": "Generic Frappe document CRUD operations."},
				{"name": "DocTypes", "description": "Generic Frappe DocType metadata operations."},
			],
			"x-frappe-openapi-documents": {
				"auth": auth_document_path(),
				"generic_api_v2": "/openapi.json",
				"methods": "/openapi/methods.json",
				"apps": {app: app_document_path(app) for app in apps},
			},
		},
	)


def build_generic_crud_paths() -> dict:
	return {
		"/api/v2/document/{doctype}": build_generic_collection_path_item(),
		"/api/v2/document/{doctype}/{name}": build_generic_document_path_item(),
		"/api/v2/document/{doctype}/{name}/copy": build_generic_copy_path_item(),
		"/api/v2/document/{doctype}/{name}/method/{method}/": build_generic_doc_method_path_item(),
		"/api/v2/doctype/{doctype}/meta": build_generic_meta_path_item(),
		"/api/v2/doctype/{doctype}/count": build_generic_count_path_item(),
	}


def build_generic_crud_schemas() -> dict:
	return {
		"FrappeDocument": {
			"type": "object",
			"description": "Generic Frappe document. Use the linked per-DocType documents for precise schemas.",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string", "description": "Document name."},
				"owner": {"type": "string", "description": "User who created the document."},
				"creation": frappe_datetime_schema(),
				"modified": frappe_datetime_schema(),
				"modified_by": {"type": "string"},
				"docstatus": {"type": "integer", "enum": [0, 1, 2]},
				"idx": {"type": "integer"},
			},
			"additionalProperties": True,
		},
		"FrappeDocumentListItem": {
			"type": "object",
			"description": "Default generic list response item. Frappe returns only `name` unless the `fields` query parameter is provided.",
			"properties": {
				"name": {"type": "string", "description": "Document name."},
			},
			"additionalProperties": False,
			"required": ["name"],
		},
		"FrappeDocumentExpandedListItem": {
			"type": "object",
			"description": "Generic list response item when `fields` is provided. Returned properties follow the requested field list.",
			"properties": {
				"name": {"type": "string", "description": "Document name."},
			},
			"additionalProperties": True,
		},
		"FrappeDocumentInput": {
			"type": "object",
			"description": "Generic document payload. Accepted fields depend on the selected DocType.",
			"properties": {
				"name": {"type": "string", "description": "Optional document name for naming-series-free DocTypes."},
			},
			"additionalProperties": True,
		},
		"DocTypeMeta": {"$ref": doctype_schema_ref("DocType", "Read")},
	}


def build_generic_collection_path_item() -> dict:
	return {
		"parameters": [doctype_parameter()],
		"get": {
			"operationId": "listDocuments",
			"tags": ["Documents"],
			"summary": "List documents for a DocType.",
			"parameters": list_query_parameters(),
			"responses": standard_responses(
				{
					"type": "array",
					"items": generic_list_item_response_schema(),
				}
			),
		},
		"post": {
			"operationId": "createDocument",
			"tags": ["Documents"],
			"summary": "Create a document for a DocType.",
			"requestBody": json_request_body(
				{"$ref": "#/components/schemas/FrappeDocumentInput"},
				required=True,
			),
			"responses": standard_responses({"$ref": "#/components/schemas/FrappeDocument"}),
		},
	}


def generic_list_item_response_schema() -> dict:
	return {
		"description": "By default, each item contains only `name`. If `fields` is provided, returned properties follow the requested field list.",
		"anyOf": [
			{"$ref": "#/components/schemas/FrappeDocumentListItem"},
			{"$ref": "#/components/schemas/FrappeDocumentExpandedListItem"},
		],
	}


def build_generic_document_path_item() -> dict:
	return {
		"parameters": [doctype_parameter(), name_parameter()],
		"get": {
			"operationId": "readDocument",
			"tags": ["Documents"],
			"summary": "Read a document.",
			"responses": standard_responses({"$ref": "#/components/schemas/FrappeDocument"}),
		},
		"put": generic_update_operation("replaceDocument"),
		"patch": generic_update_operation("updateDocument"),
		"delete": {
			"operationId": "deleteDocument",
			"tags": ["Documents"],
			"summary": "Delete a document.",
			"responses": {
				"202": {
					"description": "Document deletion accepted.",
					"content": {"application/json": {"schema": frappe_data_schema({"type": "string"})}},
				},
				"default": error_response(),
			},
		},
	}


def build_generic_copy_path_item() -> dict:
	return {
		"parameters": [doctype_parameter(), name_parameter()],
		"get": {
			"operationId": "copyDocument",
			"tags": ["Documents"],
			"summary": "Return a copy of a document that can be used to create a new document.",
			"responses": standard_responses({"$ref": "#/components/schemas/FrappeDocumentInput"}),
		},
	}


def build_generic_doc_method_path_item() -> dict:
	return {
		"parameters": [doctype_parameter(), name_parameter(), method_parameter()],
		"get": generic_doc_method_operation("get", "runDocumentGetMethod"),
		"post": generic_doc_method_operation("post", "runDocumentPostMethod"),
	}


def build_generic_meta_path_item() -> dict:
	return {
		"parameters": [doctype_parameter()],
		"get": {
			"operationId": "readDocTypeMeta",
			"tags": ["DocTypes"],
			"summary": "Read DocType metadata.",
			"responses": standard_responses({"$ref": "#/components/schemas/DocTypeMeta"}),
		},
	}


def build_generic_count_path_item() -> dict:
	return {
		"parameters": [doctype_parameter()],
		"get": {
			"operationId": "countDocuments",
			"tags": ["DocTypes"],
			"summary": "Count documents for a DocType.",
			"parameters": list_query_parameters(),
			"responses": standard_responses({"type": "integer"}),
		},
	}


def generic_update_operation(operation_id: str) -> dict:
	return {
		"operationId": operation_id,
		"tags": ["Documents"],
		"summary": "Update a document.",
		"requestBody": json_request_body({"$ref": "#/components/schemas/FrappeDocumentInput"}, required=True),
		"responses": standard_responses({"$ref": "#/components/schemas/FrappeDocument"}),
	}


def generic_doc_method_operation(http_method: str, operation_id: str) -> dict:
	operation = {
		"operationId": operation_id,
		"tags": ["Documents"],
		"summary": "Run a whitelisted controller method on a document.",
		"responses": standard_responses({}),
		"x-frappe-doc-method": True,
	}
	if http_method == "post":
		operation["requestBody"] = json_request_body({"type": "object", "additionalProperties": True})

	return operation


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_app_spec(app: str) -> dict:
	modules = get_modules_by_app(app)
	methods = get_whitelisted_methods(app=app, kind="app")

	return with_base_openapi_fields(
		app_document_path(app),
		f"{app} API",
		{
			"summary": "Index document for this Frappe app. Select an individual DocType or method document for operations.",
			"paths": {},
			"components": {"securitySchemes": build_security_schemes()},
			"security": default_security_requirements(),
			"tags": [{"name": module} for module in modules],
			"x-frappe-app": app,
			"x-frappe-openapi-documents": {
				"modules": {
					module: module_document_path(app, module)
					for module in modules
				},
				"methods": method_document_map(methods),
			},
		},
	)


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_module_spec(app: str, module: str) -> dict:
	doctypes = get_doctype_names(app=app, module=module)
	methods = get_whitelisted_methods(app=app, module=module, kind="module")

	return with_base_openapi_fields(
		module_document_path(app, module),
		f"{module} API",
		{
			"summary": "Index document for this Frappe module. Select an individual DocType document for operations.",
			"paths": {},
			"components": {"securitySchemes": build_security_schemes()},
			"security": default_security_requirements(),
			"tags": [{"name": module}],
			"x-frappe-app": app,
			"x-frappe-module": module,
			"x-frappe-openapi-documents": {
				"methods": method_document_map(methods),
				"doctypes": {
					doctype: doctype_document_entry(app, module, doctype)
					for doctype in doctypes
				}
			},
		},
	)


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_doctype_spec(doctype: str) -> dict:
	meta = frappe.get_meta(doctype)
	app = get_app_for_doctype(doctype)
	collection_path = api_doctype_path(doctype)
	name_path = api_doctype_name_path(doctype)
	copy_path = f"{name_path}/copy"
	method_path = f"{name_path}/method/{{method}}/"
	meta_path = f"/api/v2/doctype/{doctype}/meta"
	count_path = f"/api/v2/doctype/{doctype}/count"
	doc_methods = get_doctype_whitelisted_methods(doctype)
	file_methods = get_whitelisted_method_records(app=app, module=meta.module, doctype=doctype, kind="doctype")
	paths = {
		collection_path: with_doctype_operation_group(build_collection_path_item(doctype), "crud"),
		name_path: with_doctype_operation_group(build_document_path_item(doctype), "crud"),
		copy_path: with_doctype_operation_group(build_copy_path_item(doctype), "standard"),
		method_path: with_doctype_operation_group(build_doc_method_path_item(doctype), "controller"),
		meta_path: with_doctype_operation_group(build_meta_path_item(doctype), "standard"),
		count_path: with_doctype_operation_group(build_count_path_item(doctype), "standard"),
	}
	paths.update(build_doc_controller_method_paths(doctype, doc_methods, name_path))
	paths.update(build_doctype_file_method_paths(doctype, file_methods))

	return with_base_openapi_fields(
		doctype_document_path(doctype),
		f"{doctype} API",
		{
			"paths": paths,
			"components": {"securitySchemes": build_security_schemes()},
			"security": default_security_requirements(),
			"tags": doctype_operation_tags(doctype),
			"x-frappe-app": app,
			"x-frappe-module": meta.module,
			"x-frappe-doctype": doctype,
			"x-frappe-schema": schema_document_path(doctype),
			"x-frappe-doc-methods": [serialize_doc_method(method) for method in doc_methods],
			"x-frappe-file-methods": [serialize_file_method(method, doctype) for method in file_methods],
			"x-frappe-openapi-documents": {
				"file_methods": included_method_document_map(file_methods, doctype_document_path(doctype)),
			},
		},
	)


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_auth_spec() -> dict:
	return with_base_openapi_fields(
		auth_document_path(),
		"Frappe Authentication API",
		{
			"paths": {
				"/api/v2/method/login": {
					"post": {
						"operationId": "frappeLogin",
						"summary": "Log in with username and password.",
						"requestBody": {
							"required": True,
							"content": {
								"application/json": {
									"schema": {
										"type": "object",
										"required": ["usr", "pwd"],
										"properties": {
											"usr": {"type": "string"},
											"pwd": {"type": "string", "writeOnly": True},
										},
									}
								}
							},
						},
						"responses": standard_responses({"type": "object", "additionalProperties": True}),
						"security": [{}],
					}
				},
				"/api/v2/method/logout": {
					"post": {
						"operationId": "frappeLogout",
						"summary": "Log out of the current session.",
						"responses": standard_responses({"type": "object", "additionalProperties": True}),
					}
				},
				"/api/method/frappe.integrations.oauth2.authorize": {
					"get": {
						"operationId": "frappeOauthAuthorize",
						"summary": "Start the OAuth2 authorization code flow.",
						"responses": {"302": {"description": "Redirect response."}},
						"security": [{}],
					}
				},
				"/api/method/frappe.integrations.oauth2.get_token": {
					"post": {
						"operationId": "frappeOauthToken",
						"summary": "Exchange an OAuth2 code or refresh token for a bearer token.",
						"responses": standard_responses({"type": "object", "additionalProperties": True}),
						"security": [{}],
					}
				},
			},
			"components": {"securitySchemes": build_security_schemes()},
			"security": default_security_requirements(),
			"x-frappe-auth-hooks": frappe.get_hooks("auth_hooks"),
		},
	)


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_methods_index_spec() -> dict:
	methods = get_whitelisted_methods()
	methods_by_app = {}
	for app in get_installed_apps():
		app_methods = get_whitelisted_methods(app=app)
		if app_methods:
			methods_by_app[app] = app_methods

	return with_base_openapi_fields(
		"/openapi/methods.json",
		"Frappe Whitelisted Methods API",
		{
			"summary": "Index document for whitelisted methods. Select an individual method document for operations.",
			"paths": {},
			"components": {"securitySchemes": build_security_schemes()},
			"security": default_security_requirements(),
			"x-frappe-openapi-documents": {
				"methods": {
					method: method_document_path(method)
					for method in methods
				},
				"methods_by_app": {
					app: {
						method: method_document_path(method)
						for method in app_methods
					}
					for app, app_methods in methods_by_app.items()
				},
			},
		},
	)


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_method_spec(method: str) -> dict:
	resolved_method = frappe.override_whitelisted_method(method)
	method_obj = frappe.get_attr(resolved_method)
	method_path = f"/api/v2/method/{method}"
	operations = {}
	allow_guest = get_whitelisted_method_allow_guest(resolved_method)

	for http_method in get_whitelisted_method_http_methods(resolved_method):
		operations[http_method.lower()] = build_method_operation(
			method,
			method_obj,
			http_method,
			allow_guest=allow_guest,
		)

	return with_base_openapi_fields(
		method_document_path(method),
		f"{method} API",
		{
			"paths": {method_path: operations},
			"components": {"securitySchemes": build_security_schemes()},
			"security": default_security_requirements(),
			"x-frappe-method": method,
		},
	)


def method_document_map(methods: list[str]) -> dict:
	return {
		method: method_document_path(method)
		for method in methods
	}


def included_method_document_map(methods: list[dict], document_path: str) -> dict:
	return {
		method["name"]: document_path
		for method in methods
	}


def doctype_document_entry(app: str, module: str, doctype: str) -> dict:
	doctype_url = doctype_document_path(doctype)
	file_methods = get_whitelisted_method_records(app=app, module=module, doctype=doctype, kind="doctype")
	return {
		"url": doctype_url,
		"file_methods": included_method_document_map(file_methods, doctype_url),
	}


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_search_index() -> dict:
	items = []
	apps = get_installed_apps()
	doctypes = get_doctype_records()

	for app in apps:
		items.append(search_index_item(app, "App", app_document_path(app), app=app, keywords="app modules doctypes methods"))
		for module in get_modules_by_app(app):
			items.append(
				search_index_item(
					module,
					"Module",
					module_document_path(app, module),
					app=app,
					module=module,
					keywords=f"{app} module doctypes methods",
				)
			)

	for doctype in doctypes:
		app = get_app_for_doctype(doctype.name)
		file_methods = get_whitelisted_method_records(
			app=app,
			module=doctype.module,
			doctype=doctype.name,
			kind="doctype",
		)
		controller_methods = get_doctype_whitelisted_methods(doctype.name)
		method_summary = f"{len(controller_methods)} controller methods {len(file_methods)} file methods"
		items.append(
			search_index_item(
				doctype.name,
				"DocType",
				doctype_document_path(doctype.name),
				app=app,
				module=doctype.module,
				doctype=doctype.name,
				keywords=f"{doctype.name} {doctype.module} crud create read update delete copy meta count {method_summary}",
			)
		)
		for method in controller_methods:
			items.append(
				search_index_item(
					method["name"],
					"Controller Method",
					doctype_document_path(doctype.name),
					app=app,
					module=doctype.module,
					doctype=doctype.name,
					method=method["name"],
					keywords=f"{doctype.name} {method['dotted_path']} controller document method",
				)
			)

	for method in get_whitelisted_method_records():
		method_type = {
			"app": "App Method",
			"module": "Module Method",
			"doctype": "File Method",
		}.get(method.get("kind"), "Whitelisted Method")
		method_url = (
			doctype_document_path(method["doctype"])
			if method.get("kind") == "doctype" and method.get("doctype")
			else method_document_path(method["name"])
		)
		items.append(
			search_index_item(
				method["name"],
				method_type,
				method_url,
				app=method.get("app"),
				module=method.get("module"),
				doctype=method.get("doctype"),
				method=method["name"],
				keywords=f"{method.get('kind') or ''} whitelisted method {' '.join(method['http_methods'])}",
			)
		)

	return {
		"items": items,
	}


def search_index_item(
	label: str,
	item_type: str,
	url: str,
	*,
	app: str | None = None,
	module: str | None = None,
	doctype: str | None = None,
	method: str | None = None,
	keywords: str = "",
) -> dict:
	item = {
		"label": label,
		"type": item_type,
		"url": url,
		"keywords": keywords,
	}
	for key, value in {
		"app": app,
		"module": module,
		"doctype": doctype,
		"method": method,
	}.items():
		if value:
			item[key] = value

	return item


def with_base_openapi_fields(self_path: str, title: str, values: dict) -> dict:
	document = {
		"openapi": OPENAPI_VERSION,
		"$self": absolute_url(self_path),
		"jsonSchemaDialect": OPENAPI_JSON_SCHEMA_DIALECT,
		"info": {
			"title": title,
			"version": get_spec_version(),
		},
		"servers": [{"url": "/", "description": "Current Frappe site"}],
	}
	document.update(values)
	return document


def get_spec_version() -> str:
	versions = []
	for app in get_installed_apps():
		try:
			version = frappe.get_attr(f"{app}.__version__")
		except Exception:
			version = None
		versions.append(f"{app}:{version or 'unknown'}")

	return "|".join(versions)


def build_collection_path_item(doctype: str) -> dict:
	return {
		"get": {
			"operationId": operation_id("list", doctype),
			"tags": [doctype],
			"summary": f"List {doctype} documents.",
			"parameters": [list_querystring_parameter()],
			"responses": standard_responses(
				{
					"type": "array",
					"items": doctype_list_item_response_schema(doctype),
				}
			),
		},
		"post": {
			"operationId": operation_id("create", doctype),
			"tags": [doctype],
			"summary": f"Create a {doctype} document.",
			"requestBody": json_request_body({"$ref": doctype_schema_ref(doctype, "Create")}, required=True),
			"responses": standard_responses({"$ref": doctype_schema_ref(doctype, "Read")}),
		},
	}


def doctype_list_item_response_schema(doctype: str) -> dict:
	return {
		"description": "By default, each item contains only `name`. If `fields` is provided, returned properties follow the requested field list.",
		"anyOf": [
			{"$ref": doctype_schema_ref(doctype, "ListItem")},
			{"$ref": doctype_schema_ref(doctype, "ExpandedListItem")},
		],
	}


def build_document_path_item(doctype: str) -> dict:
	return {
		"parameters": [name_parameter()],
		"get": {
			"operationId": operation_id("read", doctype),
			"tags": [doctype],
			"summary": f"Read a {doctype} document.",
			"responses": standard_responses({"$ref": doctype_schema_ref(doctype, "Read")}),
		},
		"put": update_operation(doctype, "put"),
		"patch": update_operation(doctype, "patch"),
		"delete": {
			"operationId": operation_id("delete", doctype),
			"tags": [doctype],
			"summary": f"Delete a {doctype} document.",
			"responses": {
				"202": {
					"description": "Document deletion accepted.",
					"content": {"application/json": {"schema": frappe_data_schema({"type": "string"})}},
				},
				"default": error_response(),
			},
		},
	}


def build_copy_path_item(doctype: str) -> dict:
	return {
		"parameters": [name_parameter()],
		"get": {
			"operationId": operation_id("copy", doctype),
			"tags": [doctype],
			"summary": f"Return a copy of a {doctype} document.",
			"responses": standard_responses({"$ref": doctype_schema_ref(doctype, "Create")}),
		},
	}


def build_doc_method_path_item(doctype: str) -> dict:
	return {
		"parameters": [name_parameter(), method_parameter()],
		"get": doc_method_operation(doctype, "get"),
		"post": doc_method_operation(doctype, "post"),
	}


def build_doc_controller_method_paths(doctype: str, doc_methods: list[dict], name_path: str) -> dict:
	return {
		f"{name_path}/method/{quote_segment(method['name'])}/": with_doctype_operation_group(
			build_doc_controller_method_path_item(doctype, method), "controller"
		)
		for method in doc_methods
	}


def build_doctype_file_method_paths(doctype: str, file_methods: list[dict]) -> dict:
	return {
		f"/api/v2/method/{method['name']}": build_doctype_file_method_path_item(doctype, method)
		for method in file_methods
	}


def build_doctype_file_method_path_item(doctype: str, method: dict) -> dict:
	resolved_method = frappe.override_whitelisted_method(method["name"])
	method_obj = frappe.get_attr(resolved_method)
	path_item = {}
	for http_method in method["http_methods"]:
		operation = build_method_operation(
			method["name"],
			method_obj,
			http_method,
			allow_guest=method.get("allow_guest", False),
		)
		operation.update({
			"tags": [doctype_operation_tag("file")],
			"x-frappe-operation-group": "file",
			"x-frappe-file-method": method["name"],
		})
		path_item[http_method.lower()] = operation

	return path_item


def build_doc_controller_method_path_item(doctype: str, method: dict) -> dict:
	path_item = {"parameters": [name_parameter()]}
	for http_method in method["http_methods"]:
		path_item[http_method.lower()] = doc_controller_method_operation(doctype, method, http_method)

	return path_item


def serialize_doc_method(method: dict) -> dict:
	return {
		"name": method["name"],
		"dotted_path": method["dotted_path"],
		"http_methods": method["http_methods"],
		"allow_guest": method.get("allow_guest", False),
	}


def serialize_file_method(method: dict, doctype: str) -> dict:
	return {
		"name": method["name"],
		"http_methods": method["http_methods"],
		"allow_guest": method.get("allow_guest", False),
		"included_in": doctype_document_path(doctype),
	}


def doctype_operation_tags(doctype: str) -> list[dict]:
	return [
		{
			"name": doctype_operation_tag(group),
			"description": DOCTYPE_OPERATION_DESCRIPTIONS[group].format(doctype=doctype),
			"x-frappe-operation-group": group,
		}
		for group in DOCTYPE_OPERATION_GROUPS
	]


def doctype_operation_tag(group: str) -> str:
	return DOCTYPE_OPERATION_GROUPS[group]


def with_doctype_operation_group(path_item: dict, group: str) -> dict:
	for operation in path_item.values():
		if isinstance(operation, dict):
			operation["tags"] = [doctype_operation_tag(group)]
			operation["x-frappe-operation-group"] = group
	return path_item


def build_meta_path_item(doctype: str) -> dict:
	return {
		"get": {
			"operationId": operation_id("meta", doctype),
			"tags": [doctype],
			"summary": f"Read {doctype} metadata.",
			"responses": standard_responses({"$ref": doctype_schema_ref("DocType", "Read")}),
		},
	}


def build_count_path_item(doctype: str) -> dict:
	return {
		"get": {
			"operationId": operation_id("count", doctype),
			"tags": [doctype],
			"summary": f"Count {doctype} documents.",
			"parameters": [list_querystring_parameter()],
			"responses": standard_responses({"type": "integer"}),
		},
	}


def update_operation(doctype: str, http_method: str) -> dict:
	return {
		"operationId": operation_id(http_method, doctype),
		"tags": [doctype],
		"summary": f"Update a {doctype} document.",
		"requestBody": json_request_body({"$ref": doctype_schema_ref(doctype, "Update")}, required=True),
		"responses": standard_responses({"$ref": doctype_schema_ref(doctype, "Read")}),
	}


def doc_method_operation(doctype: str, http_method: str) -> dict:
	operation = {
		"operationId": operation_id(f"run_{http_method}_method", doctype),
		"tags": [doctype],
		"summary": f"Run a whitelisted {doctype} controller method.",
		"responses": standard_responses({}),
		"x-frappe-doc-method": True,
	}
	if http_method == "post":
		operation["requestBody"] = json_request_body({"type": "object", "additionalProperties": True})

	return operation


def doc_controller_method_operation(doctype: str, method: dict, http_method: str) -> dict:
	operation = build_method_operation(
		f"{doctype}.{method['name']}",
		method["method_obj"],
		http_method,
		allow_guest=method.get("allow_guest", False),
	)
	operation.update({
		"operationId": operation_id(f"run_{http_method.lower()}_{method['name']}", doctype),
		"tags": [doctype],
		"summary": f"Run {doctype}.{method['name']}.",
		"x-frappe-doc-method": method["name"],
		"x-frappe-controller-method": method["dotted_path"],
	})
	return operation


def build_method_operation(method: str, method_obj, http_method: str, allow_guest: bool = False) -> dict:
	signature = inspect.signature(method_obj)
	try:
		type_hints = get_type_hints(method_obj)
	except Exception:
		type_hints = {}
	parameters = []
	body_properties = {}
	required_body_fields = []

	for name, parameter in signature.parameters.items():
		if name in {"self", "cls"} or parameter.kind in {
			inspect.Parameter.VAR_POSITIONAL,
			inspect.Parameter.VAR_KEYWORD,
		}:
			continue

		schema = python_type_to_schema(type_hints.get(name, str))
		if http_method == "GET":
			parameters.append({
				"name": name,
				"in": "query",
				"required": parameter.default is inspect.Parameter.empty,
				"schema": schema,
			})
		else:
			body_properties[name] = schema
			if parameter.default is inspect.Parameter.empty:
				required_body_fields.append(name)

	operation = {
		"operationId": method.replace(".", "_"),
		"summary": method,
		"parameters": parameters,
		"responses": standard_responses(python_type_to_schema(type_hints.get("return", dict))),
		"x-frappe-whitelisted-method": method,
	}
	if body_properties:
		body_schema = {
			"type": "object",
			"properties": body_properties,
			"additionalProperties": False,
		}
		if required_body_fields:
			body_schema["required"] = required_body_fields
		operation["requestBody"] = json_request_body(body_schema, required=True)
	if allow_guest or method_obj in frappe.guest_methods:
		operation["security"] = [{}]

	return operation


def operation_id(action: str, doctype: str) -> str:
	return f"{action}{''.join(part.title() for part in doctype.replace('-', ' ').split())}"


def doctype_parameter() -> dict:
	return {
		"name": "doctype",
		"in": "path",
		"required": True,
		"description": "DocType name.",
		"schema": {"type": "string"},
	}


def name_parameter() -> dict:
	return {
		"name": "name",
		"in": "path",
		"required": True,
		"description": "Document name. Frappe accepts path-like names, but OpenAPI clients should percent-encode slashes.",
		"schema": {"type": "string"},
		"x-frappe-path-converter": "path",
	}


def method_parameter() -> dict:
	return {
		"name": "method",
		"in": "path",
		"required": True,
		"description": "Whitelisted controller method name.",
		"schema": {"type": "string"},
	}


def list_query_parameters() -> list[dict]:
	return [
		{
			"name": "fields",
			"in": "query",
			"description": "JSON-encoded list of fields. When omitted, list items contain only `name`; when provided, the response includes the requested fields.",
			"schema": {"type": "string"},
		},
		{
			"name": "filters",
			"in": "query",
			"description": "JSON-encoded Frappe filters.",
			"schema": {"type": "string"},
		},
		{
			"name": "or_filters",
			"in": "query",
			"description": "JSON-encoded Frappe OR filters.",
			"schema": {"type": "string"},
		},
		{"name": "order_by", "in": "query", "schema": {"type": "string"}},
		{"name": "group_by", "in": "query", "schema": {"type": "string"}},
		{"name": "start", "in": "query", "schema": {"type": "integer"}},
		{"name": "limit", "in": "query", "schema": {"type": "integer"}},
		{"name": "debug", "in": "query", "schema": {"type": "boolean"}},
		{"name": "as_dict", "in": "query", "schema": {"type": "boolean"}},
	]


def list_querystring_parameter() -> dict:
	return {
		"name": "query",
		"in": "querystring",
		"content": {
			"application/x-www-form-urlencoded": {
				"schema": {
					"type": "object",
					"properties": {
						"fields": {
							"type": "string",
							"description": "JSON-encoded list of fields. When omitted, list items contain only `name`; when provided, the response includes the requested fields.",
						},
						"filters": {"type": "string", "description": "JSON-encoded Frappe filters."},
						"or_filters": {"type": "string", "description": "JSON-encoded Frappe OR filters."},
						"order_by": {"type": "string"},
						"group_by": {"type": "string"},
						"start": {"type": "integer"},
						"limit": {"type": "integer"},
						"debug": {"type": "boolean"},
						"as_dict": {"type": "boolean"},
					},
					"additionalProperties": True,
				}
			}
		},
	}


def json_request_body(schema: dict, required: bool = False) -> dict:
	return {
		"required": required,
		"content": {
			"application/json": {"schema": schema},
			"application/x-www-form-urlencoded": {"schema": schema},
		},
	}


def standard_responses(data_schema: dict) -> dict:
	success_status = "200"
	return {
		success_status: {
			"description": "Successful response.",
			"content": {"application/json": {"schema": frappe_data_schema(data_schema)}},
		},
		"default": error_response(),
	}


def frappe_data_schema(data_schema: dict) -> dict:
	return {
		"type": "object",
		"properties": {
			"data": data_schema,
		},
		"additionalProperties": True,
	}


def error_response() -> dict:
	return {
		"description": "Frappe error response.",
		"content": {
			"application/json": {
				"schema": {
					"type": "object",
					"properties": {
						"errors": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
						"messages": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
						"exception": {"type": "string"},
						"exc_type": {"type": "string"},
					},
					"additionalProperties": True,
				}
			}
		},
	}


def build_security_schemes() -> dict:
	return {
		"sessionCookie": {
			"type": "apiKey",
			"in": "cookie",
			"name": "sid",
			"description": "Frappe session cookie. Unsafe methods also require X-Frappe-CSRF-Token.",
		},
		"csrfToken": {
			"type": "apiKey",
			"in": "header",
			"name": "X-Frappe-CSRF-Token",
		},
		"apiToken": {
			"type": "apiKey",
			"in": "header",
			"name": "Authorization",
			"description": "Use Authorization: token api_key:api_secret.",
		},
		"basicApiKey": {
			"type": "http",
			"scheme": "basic",
			"description": "Basic auth with api_key as username and api_secret as password.",
		},
		"oauth2": {
			"type": "oauth2",
			"flows": {
				"authorizationCode": {
					"authorizationUrl": "/api/method/frappe.integrations.oauth2.authorize",
					"tokenUrl": "/api/method/frappe.integrations.oauth2.get_token",
					"refreshUrl": "/api/method/frappe.integrations.oauth2.get_token",
					"scopes": {},
				}
			},
		},
	}


def default_security_requirements() -> list[dict]:
	return [
		{"sessionCookie": []},
		{"apiToken": []},
		{"basicApiKey": []},
		{"oauth2": []},
	]
