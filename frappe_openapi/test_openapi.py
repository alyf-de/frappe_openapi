from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe_openapi import openapi


class TestDocTypeOpenAPI(TestCase):
	def file_method(self, customer: str = "") -> dict:
		return {"customer": customer}

	def test_doctype_spec_embeds_file_level_methods(self):
		method_name = "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_payment_request"
		meta = SimpleNamespace(module="Accounts", fields=[], istable=False)
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
			),
			patch("frappe_openapi.openapi.get_app_for_doctype", return_value="erpnext"),
			patch("frappe_openapi.openapi.get_doctype_whitelisted_methods", return_value=[]),
			patch("frappe_openapi.openapi.get_whitelisted_method_records", side_effect=get_method_records),
		):
			index = openapi.build_search_index.__wrapped__()

		method_items = [item for item in index["items"] if item.get("method") == method_name]
		self.assertEqual(len(method_items), 1)
		self.assertEqual(method_items[0]["type"], "File Method")
		self.assertEqual(method_items[0]["url"], "/openapi/doctypes/Sales%20Invoice.json")
