from datetime import date, datetime
from typing import Any, get_args, get_origin

import frappe
from frappe.utils.caching import redis_cache

from frappe_openapi.refs import JSON_SCHEMA_DIALECT, absolute_url, doctype_schema_ref, schema_document_path

SPEC_CACHE_TTL = 300
FRAPPE_DATETIME_PATTERN = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{1,6})?$"
FRAPPE_DATETIME_EXAMPLE = "2026-05-24 16:10:57.157456"

NO_VALUE_FIELDTYPES = {
	"Button",
	"Column Break",
	"Fold",
	"Heading",
	"HTML",
	"Section Break",
	"Tab Break",
}

TEXT_FIELDTYPES = {
	"Autocomplete",
	"Attach",
	"Attach Image",
	"Barcode",
	"Code",
	"Color",
	"Data",
	"Dynamic Link",
	"Icon",
	"Image",
	"Link",
	"Long Text",
	"Markdown Editor",
	"Password",
	"Phone",
	"Read Only",
	"Select",
	"Signature",
	"Small Text",
	"Text",
	"Text Editor",
	"Time",
}

FLOAT_FIELDTYPES = {"Currency", "Duration", "Float", "Percent", "Rating"}


def frappe_datetime_schema() -> dict:
	return {
		"type": "string",
		"pattern": FRAPPE_DATETIME_PATTERN,
		"example": FRAPPE_DATETIME_EXAMPLE,
	}


SYSTEM_FIELDS = {
	"name": {"type": "string", "description": "Document name."},
	"owner": {"type": "string", "description": "User who created the document."},
	"creation": frappe_datetime_schema(),
	"modified": frappe_datetime_schema(),
	"modified_by": {"type": "string"},
	"docstatus": {"type": "integer", "enum": [0, 1, 2]},
	"idx": {"type": "integer"},
}
CHILD_TABLE_SYSTEM_FIELDS = {
	"parent": {"type": "string"},
	"parentfield": {"type": "string"},
	"parenttype": {"type": "string"},
}


@redis_cache(ttl=SPEC_CACHE_TTL)
def build_schema_document(doctype: str) -> dict:
	return {
		"$schema": JSON_SCHEMA_DIALECT,
		"$id": absolute_url(schema_document_path(doctype)),
		"$ref": "#/$defs/Read",
		"title": doctype,
		"$defs": {
			"Read": build_doctype_schema(doctype, "read"),
			"Create": build_doctype_schema(doctype, "create"),
			"Update": build_doctype_schema(doctype, "update"),
			"ListItem": build_list_item_schema(doctype),
			"ExpandedListItem": build_expanded_list_item_schema(doctype),
			"Name": {"type": "string", "title": f"{doctype} name"},
		},
	}


def build_doctype_schema(doctype: str, mode: str = "read") -> dict:
	meta = frappe.get_meta(doctype)
	properties = get_system_properties(meta)
	required = ["name"] if mode == "read" else []

	for field in meta.fields:
		if field.fieldtype in NO_VALUE_FIELDTYPES or not field.fieldname:
			continue

		if mode in {"create", "update"} and is_read_only_field(field):
			continue

		properties[field.fieldname] = field_to_schema(field, mode, doctype)
		if mode == "create" and field.reqd and not is_read_only_field(field):
			required.append(field.fieldname)

	schema = {
		"type": "object",
		"title": f"{doctype} {mode.title()}",
		"properties": properties,
		"additionalProperties": False,
		"x-frappe-doctype": doctype,
		"x-frappe-schema-mode": mode,
	}
	if required:
		schema["required"] = sorted(set(required))

	return schema


def build_list_item_schema(doctype: str) -> dict:
	return {
		"type": "object",
		"title": f"{doctype} List Item",
		"description": "Default list response item. Frappe returns only `name` unless the `fields` query parameter is provided.",
		"properties": {"name": SYSTEM_FIELDS["name"]},
		"additionalProperties": False,
		"required": ["name"],
		"x-frappe-doctype": doctype,
		"x-frappe-schema-mode": "list",
	}


def build_expanded_list_item_schema(doctype: str) -> dict:
	meta = frappe.get_meta(doctype)
	properties = get_system_properties(meta)

	for field in meta.fields:
		if field.fieldname and field.fieldtype not in NO_VALUE_FIELDTYPES:
			properties[field.fieldname] = field_to_schema(field, "read", doctype)

	return {
		"type": "object",
		"title": f"{doctype} Expanded List Item",
		"description": "List response item when `fields` is provided. Returned properties follow the requested field list.",
		"properties": properties,
		"additionalProperties": True,
		"x-frappe-doctype": doctype,
		"x-frappe-schema-mode": "list-fields",
	}


def get_system_properties(meta) -> dict:
	properties = SYSTEM_FIELDS.copy()
	if meta.istable:
		properties.update(CHILD_TABLE_SYSTEM_FIELDS)

	return properties


def is_read_only_field(field) -> bool:
	return bool(field.read_only or field.fieldtype == "Read Only" or field.is_virtual)


def field_to_schema(field, mode: str, doctype: str) -> dict:
	field_schema = base_field_schema(field, mode)
	field_schema["x-frappe-fieldtype"] = field.fieldtype

	if field.label:
		field_schema["title"] = field.label
	if field.description:
		field_schema["description"] = field.description
	if field.options:
		field_schema["x-frappe-options"] = field.options
	if field.permlevel:
		field_schema["x-frappe-permlevel"] = field.permlevel
	if field.hidden:
		field_schema["x-frappe-hidden"] = True
	if field.read_only:
		field_schema["readOnly"] = True
	if field.fieldtype == "Link":
		field_schema["x-frappe-link-options"] = build_link_options_reference(field, doctype)
	if field.fieldtype == "Dynamic Link":
		field_schema["x-frappe-link-options"] = build_dynamic_link_options_reference(field, doctype)

	if field.fieldtype == "Password":
		field_schema["writeOnly"] = True

	return field_schema


def build_link_options_reference(field, doctype: str) -> dict:
	parameters = {
		"doctype": field.options,
		"reference_doctype": doctype,
		"link_fieldname": field.fieldname,
	}
	if field.ignore_user_permissions:
		parameters["ignore_user_permissions"] = True
	if field.link_filters:
		parameters["filters"] = field.link_filters

	return {
		"operationId": "frappe_desk_search_search_link",
		"method": "GET",
		"path": "/api/v2/method/frappe.desk.search.search_link",
		"parameters": parameters,
		"description": "Search endpoint used by Frappe Link controls to produce valid options.",
	}


def build_dynamic_link_options_reference(field, doctype: str) -> dict:
	return {
		"operationId": "frappe_desk_search_search_link",
		"method": "GET",
		"path": "/api/v2/method/frappe.desk.search.search_link",
		"parameters": {
			"doctype": {"$data": f"/{field.options}"},
			"reference_doctype": doctype,
			"link_fieldname": field.fieldname,
		},
		"description": f"Search endpoint used by Frappe Dynamic Link controls. Resolve doctype from `{field.options}` on the current document.",
	}


def base_field_schema(field, mode: str) -> dict:
	if field.fieldtype == "Check":
		return {"type": "integer", "enum": [0, 1]}

	if field.fieldtype == "Int":
		return {"type": "integer"}

	if field.fieldtype in FLOAT_FIELDTYPES:
		return {"type": "number"}

	if field.fieldtype == "Date":
		return {"type": "string", "format": "date"}

	if field.fieldtype == "Datetime":
		return frappe_datetime_schema()

	if field.fieldtype == "JSON":
		return {}

	if field.fieldtype == "Geolocation":
		return {"type": "object", "additionalProperties": True}

	if field.fieldtype in {"Table", "Table MultiSelect"}:
		child_doctype = field.options
		child_schema = "Create" if mode in {"create", "update"} else "Read"
		return {"type": "array", "items": {"$ref": doctype_schema_ref(child_doctype, child_schema)}}

	if field.fieldtype == "Select":
		schema = {"type": "string"}
		if options := get_select_options(field):
			schema["enum"] = options
		return schema

	if field.fieldtype == "Link":
		return {"type": "string"}

	if field.fieldtype == "Dynamic Link":
		return {"type": "string"}

	if field.fieldtype in TEXT_FIELDTYPES:
		schema = {"type": "string"}
		if field.length:
			schema["maxLength"] = field.length
		return schema

	return {"type": "string"}


def get_select_options(field) -> list[str]:
	if hasattr(field, "get_select_options"):
		return field.get_select_options() or []

	return [option for option in (field.options or "").split("\n") if option]


def python_type_to_schema(type_hint: Any) -> dict:
	if type_hint in {str, Any}:
		return {"type": "string"} if type_hint is str else {}
	if type_hint is int:
		return {"type": "integer"}
	if type_hint is float:
		return {"type": "number"}
	if type_hint is bool:
		return {"type": "boolean"}
	if type_hint is datetime:
		return frappe_datetime_schema()
	if type_hint is date:
		return {"type": "string", "format": "date"}
	if type_hint in {dict, frappe._dict}:
		return {"type": "object", "additionalProperties": True}
	if type_hint in {list, tuple, set}:
		return {"type": "array", "items": {}}

	origin = get_origin(type_hint)
	args = get_args(type_hint)
	if origin in {list, tuple, set}:
		item_type = args[0] if args else Any
		return {"type": "array", "items": python_type_to_schema(item_type)}
	if origin is dict:
		return {"type": "object", "additionalProperties": True}
	if origin is type(None):
		return {"type": "null"}
	if args and type(None) in args:
		non_null_args = [arg for arg in args if arg is not type(None)]
		if len(non_null_args) == 1:
			schema = python_type_to_schema(non_null_args[0])
			if isinstance(schema, dict) and "type" in schema:
				schema["type"] = [schema["type"], "null"]
			return schema

	return {}
