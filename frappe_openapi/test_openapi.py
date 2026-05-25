from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe_openapi import openapi


class TestDocTypeOpenAPI(TestCase):
	def file_method(self, customer: str = "") -> dict:
		return {"customer": customer}

	def schema_document(self, doctype: str) -> dict:
		return {
			"$defs": {
				"Read": {
					"type": "object",
					"title": f"{doctype} Read",
					"x-frappe-schema-mode": "read",
				},
				"Create": {
					"type": "object",
					"title": f"{doctype} Create",
					"x-frappe-schema-mode": "create",
				},
				"Update": {
					"type": "object",
					"title": f"{doctype} Update",
					"x-frappe-schema-mode": "update",
				},
				"ListItem": {
					"type": "object",
					"title": f"{doctype} List Item",
					"x-frappe-schema-mode": "list",
				},
				"ExpandedListItem": {
					"type": "object",
					"title": f"{doctype} Expanded List Item",
					"x-frappe-schema-mode": "list-fields",
				},
				"Name": {"type": "string", "title": f"{doctype} name"},
			},
		}

	def test_doctype_spec_embeds_file_level_methods(self):
		method_name = "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_payment_request"
		meta = SimpleNamespace(module="Accounts", fields=[], istable=False, issingle=False)
		file_method = {
			"name": method_name,
			"app": "erpnext",
			"module": "Accounts",
			"doctype": "Sales Invoice",
			"kind": "doctype",
			"http_methods": ["GET", "POST"],
			"allow_guest": True,
		}

		with (
			patch.object(openapi.frappe, "get_meta", return_value=meta),
			patch.object(openapi.frappe, "override_whitelisted_method", side_effect=lambda method: method),
			patch.object(openapi.frappe, "get_attr", return_value=self.file_method),
			patch("frappe_openapi.openapi.get_app_for_doctype", return_value="erpnext"),
			patch("frappe_openapi.openapi.get_doctype_whitelisted_methods", return_value=[]),
			patch("frappe_openapi.openapi.get_whitelisted_method_records", return_value=[file_method]),
			patch("frappe_openapi.openapi.build_schema_document", side_effect=self.schema_document),
			patch("frappe_openapi.openapi.absolute_url", side_effect=lambda path: path),
			patch("frappe_openapi.openapi.get_spec_version", return_value="erpnext:1.0.0"),
		):
			spec = openapi.build_doctype_spec.__wrapped__("Sales Invoice")

		method_path = f"/api/v2/method/{method_name}"
		self.assertIn(method_path, spec["paths"])
		self.assertEqual(
			spec["paths"][method_path]["get"]["tags"],
			["File-level RPC"],
		)
		self.assertEqual(spec["paths"][method_path]["get"]["x-frappe-operation-group"], "file")
		self.assertEqual(spec["paths"][method_path]["get"]["x-frappe-file-method"], method_name)
		self.assertEqual(spec["paths"][method_path]["get"]["security"], [{}])
		self.assertIn("post", spec["paths"][method_path])
		self.assertEqual(
			spec["paths"]["/api/v2/document/Sales Invoice"]["get"]["x-frappe-operation-group"],
			"crud",
		)
		self.assertEqual(
			spec["paths"]["/api/v2/document/Sales Invoice"]["get"]["responses"]["200"]["content"][
				"application/json"
			]["schema"]["$ref"],
			"#/components/schemas/Sales_Invoice_ListResponse",
		)
		self.assertEqual(
			spec["paths"]["/api/v2/document/Sales Invoice"]["post"]["requestBody"]["content"][
				"application/json"
			]["schema"]["$ref"],
			"#/components/schemas/Sales_Invoice_Create",
		)
		self.assertEqual(
			spec["paths"]["/api/v2/doctype/Sales Invoice/count"]["get"]["x-frappe-operation-group"],
			"standard",
		)
		schemas = spec["components"]["schemas"]
		self.assertNotIn("$ref", schemas["Sales_Invoice_Create"])
		self.assertEqual(schemas["Sales_Invoice_Create"]["title"], "Sales Invoice Create")
		self.assertEqual(schemas["Sales_Invoice_Create"]["x-frappe-schema-mode"], "create")
		self.assertEqual(
			schemas["Sales_Invoice_ListResponse"]["properties"]["data"]["items"]["anyOf"][0]["$ref"],
			"#/components/schemas/Sales_Invoice_ListItem",
		)
		self.assertNotIn("$ref", schemas["DocType_Read"])
		self.assertEqual(schemas["DocType_Read"]["title"], "DocType Read")
		self.assertEqual(
			spec["x-frappe-openapi-documents"]["file_methods"],
			{method_name: "/openapi/doctypes/Sales%20Invoice.json"},
		)
		self.assertEqual(
			spec["x-frappe-file-methods"][0]["included_in"], "/openapi/doctypes/Sales%20Invoice.json"
		)

	def test_doctype_component_schemas_include_local_child_components(self):
		def schema_document(doctype: str) -> dict:
			definitions = self.schema_document(doctype)["$defs"]
			if doctype == "Sales Invoice":
				definitions["Read"]["properties"] = {
					"items": {
						"type": "array",
						"items": {"$ref": "/openapi/schemas/Sales%20Invoice%20Item.schema.json#/$defs/Read"},
					}
				}
				definitions["Create"]["properties"] = {
					"items": {
						"type": "array",
						"items": {"$ref": "/openapi/schemas/Sales%20Invoice%20Item.schema.json#/$defs/Create"},
					}
				}
				definitions["Update"]["properties"] = {
					"items": {
						"type": "array",
						"items": {"$ref": "/openapi/schemas/Sales%20Invoice%20Item.schema.json#/$defs/Create"},
					}
				}
			return {"$defs": definitions}

		with patch("frappe_openapi.openapi.build_schema_document", side_effect=schema_document):
			schemas = openapi.build_doctype_model_component_schemas("Sales Invoice")

		self.assertIn("Sales_Invoice_Item_Read", schemas)
		self.assertIn("Sales_Invoice_Item_Create", schemas)
		self.assertNotIn("Sales_Invoice_Item_Update", schemas)
		self.assertEqual(
			schemas["Sales_Invoice_Read"]["properties"]["items"]["items"]["$ref"],
			"#/components/schemas/Sales_Invoice_Item_Read",
		)
		self.assertEqual(
			schemas["Sales_Invoice_Create"]["properties"]["items"]["items"]["$ref"],
			"#/components/schemas/Sales_Invoice_Item_Create",
		)
		self.assertEqual(
			schemas["Sales_Invoice_Update"]["properties"]["items"]["items"]["$ref"],
			"#/components/schemas/Sales_Invoice_Item_Create",
		)

	def test_single_doctype_spec_uses_concrete_singleton_document_path(self):
		meta = SimpleNamespace(module="Website", fields=[], istable=False, issingle=True)

		with (
			patch.object(openapi.frappe, "get_meta", return_value=meta),
			patch("frappe_openapi.openapi.get_app_for_doctype", return_value="frappe"),
			patch("frappe_openapi.openapi.get_doctype_whitelisted_methods", return_value=[]),
			patch("frappe_openapi.openapi.get_whitelisted_method_records", return_value=[]),
			patch("frappe_openapi.openapi.build_schema_document", side_effect=self.schema_document),
			patch("frappe_openapi.openapi.absolute_url", side_effect=lambda path: path),
			patch("frappe_openapi.openapi.get_spec_version", return_value="frappe:1.0.0"),
		):
			spec = openapi.build_doctype_spec.__wrapped__("Website Settings")

		singleton_path = "/api/v2/document/Website Settings/Website Settings"
		self.assertIn(singleton_path, spec["paths"])
		self.assertNotIn("/api/v2/document/Website Settings", spec["paths"])
		self.assertNotIn("/api/v2/document/Website Settings/{name}", spec["paths"])
		self.assertNotIn("/api/v2/document/Website Settings/Website Settings/copy", spec["paths"])
		self.assertNotIn("/api/v2/doctype/Website Settings/count", spec["paths"])
		self.assertEqual(set(spec["paths"][singleton_path]), {"get", "put", "patch"})
		self.assertEqual(
			spec["paths"][singleton_path]["get"]["summary"],
			"Read the Website Settings singleton document.",
		)
		self.assertTrue(spec["x-frappe-issingle"])
		self.assertFalse(spec["x-frappe-istable"])
		self.assertEqual(
			spec["tags"][0]["description"],
			"Read and update the Website Settings singleton document.",
		)

	def test_child_table_doctype_spec_omits_standalone_document_paths(self):
		meta = SimpleNamespace(module="Desk", fields=[], istable=True, issingle=False)

		with (
			patch.object(openapi.frappe, "get_meta", return_value=meta),
			patch("frappe_openapi.openapi.get_app_for_doctype", return_value="frappe"),
			patch("frappe_openapi.openapi.get_doctype_whitelisted_methods", return_value=[]),
			patch("frappe_openapi.openapi.get_whitelisted_method_records", return_value=[]),
			patch("frappe_openapi.openapi.build_schema_document", side_effect=self.schema_document),
			patch("frappe_openapi.openapi.absolute_url", side_effect=lambda path: path),
			patch("frappe_openapi.openapi.get_spec_version", return_value="frappe:1.0.0"),
		):
			spec = openapi.build_doctype_spec.__wrapped__("Note Seen By")

		self.assertEqual(list(spec["paths"]), ["/api/v2/doctype/Note Seen By/meta"])
		self.assertNotIn("/api/v2/document/Note Seen By", spec["paths"])
		self.assertNotIn("/api/v2/document/Note Seen By/{name}", spec["paths"])
		self.assertFalse(spec["x-frappe-issingle"])
		self.assertTrue(spec["x-frappe-istable"])
		self.assertEqual([tag["name"] for tag in spec["tags"]], ["Standard RPC"])

	def test_module_spec_lists_only_top_level_doctypes(self):
		with (
			patch("frappe_openapi.openapi.get_doctype_names", return_value=["Note"]) as get_doctype_names,
			patch("frappe_openapi.openapi.get_whitelisted_methods", return_value=[]),
			patch("frappe_openapi.openapi.get_whitelisted_method_records", return_value=[]),
			patch("frappe_openapi.openapi.absolute_url", side_effect=lambda path: path),
			patch("frappe_openapi.openapi.get_spec_version", return_value="frappe:1.0.0"),
		):
			spec = openapi.build_module_spec.__wrapped__("frappe", "Desk")

		get_doctype_names.assert_called_once_with(
			app="frappe",
			module="Desk",
			include_child_tables=False,
		)
		self.assertEqual(
			list(spec["x-frappe-openapi-documents"]["doctypes"]),
			["Note"],
		)

	def test_search_index_routes_doctype_file_methods_to_doctype_spec(self):
		method_name = "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_payment_request"
		file_method = {
			"name": method_name,
			"app": "erpnext",
			"module": "Accounts",
			"doctype": "Sales Invoice",
			"kind": "doctype",
			"http_methods": ["POST"],
			"allow_guest": False,
		}

		def get_method_records(**kwargs):
			if kwargs.get("kind") == "doctype":
				return [file_method]
			if kwargs:
				return []
			return [file_method]

		with (
			patch("frappe_openapi.openapi.get_installed_apps", return_value=["erpnext"]),
			patch("frappe_openapi.openapi.get_modules_by_app", return_value={"Accounts": ["Sales Invoice"]}),
			patch(
				"frappe_openapi.openapi.get_doctype_records",
				return_value=[SimpleNamespace(name="Sales Invoice", module="Accounts")],
			) as get_doctype_records,
			patch("frappe_openapi.openapi.get_app_for_doctype", return_value="erpnext"),
			patch("frappe_openapi.openapi.get_doctype_whitelisted_methods", return_value=[]),
			patch("frappe_openapi.openapi.get_whitelisted_method_records", side_effect=get_method_records),
		):
			index = openapi.build_search_index.__wrapped__()

		get_doctype_records.assert_called_once_with(include_child_tables=False)
		method_items = [item for item in index["items"] if item.get("method") == method_name]
		self.assertEqual(len(method_items), 1)
		self.assertEqual(method_items[0]["type"], "File Method")
		self.assertEqual(method_items[0]["url"], "/openapi/doctypes/Sales%20Invoice.json")

	def test_search_index_skips_child_table_file_methods(self):
		child_method = {
			"name": "frappe.desk.doctype.note_seen_by.note_seen_by.child_method",
			"app": "frappe",
			"module": "Desk",
			"doctype": "Note Seen By",
			"kind": "doctype",
			"http_methods": ["POST"],
			"allow_guest": False,
		}

		def get_method_records(**kwargs):
			if kwargs:
				return []
			return [child_method]

		with (
			patch("frappe_openapi.openapi.get_installed_apps", return_value=["frappe"]),
			patch("frappe_openapi.openapi.get_modules_by_app", return_value={"Desk": ["Note"]}),
			patch(
				"frappe_openapi.openapi.get_doctype_records",
				return_value=[SimpleNamespace(name="Note", module="Desk")],
			),
			patch("frappe_openapi.openapi.get_app_for_doctype", return_value="frappe"),
			patch("frappe_openapi.openapi.get_doctype_whitelisted_methods", return_value=[]),
			patch("frappe_openapi.openapi.get_whitelisted_method_records", side_effect=get_method_records),
		):
			index = openapi.build_search_index.__wrapped__()

		self.assertFalse([item for item in index["items"] if item.get("method") == child_method["name"]])
