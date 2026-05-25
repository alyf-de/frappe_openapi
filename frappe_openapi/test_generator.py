import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe_openapi.generator import build_app_bundle, generate_app_bundles


class TestGeneratedOpenAPISpecs(TestCase):
	def test_generate_app_bundles_writes_manifest_and_bundle(self):
		with TemporaryDirectory() as output:
			with (
				patch("frappe_openapi.generator.frappe.local", SimpleNamespace(site="test-site")),
				patch("frappe_openapi.generator.now_utc", return_value="2026-05-24T20:00:00Z"),
				patch("frappe_openapi.generator.get_installed_apps", return_value=["frappe_openapi"]),
				patch("frappe_openapi.generator.get_app_version", return_value="1.0.0"),
				patch("frappe_openapi.generator.build_app_bundle", return_value={"openapi": "3.2.0"}),
			):
				result = generate_app_bundles(["frappe_openapi"], output=output)

			output_path = Path(output).resolve()
			manifest_path = output_path / "manifest.json"
			bundle_path = output_path / "apps" / "frappe_openapi.json"
			manifest = json.loads(manifest_path.read_text())

			self.assertEqual(result["manifest_path"], str(manifest_path))
			self.assertEqual(result["output"], str(output_path))
			self.assertEqual(json.loads(bundle_path.read_text()), {"openapi": "3.2.0"})
			self.assertEqual(manifest["site"], "test-site")
			self.assertEqual(manifest["manifest_url"], "/openapi/generated/manifest.json")
			self.assertEqual(
				manifest["apps"]["frappe_openapi"]["url"],
				"/openapi/generated/apps/frappe_openapi.json",
			)
			self.assertGreater(manifest["apps"]["frappe_openapi"]["size_bytes"], 0)
			self.assertEqual(manifest["installed_apps"]["frappe_openapi"]["version"], "1.0.0")

	def test_build_app_bundle_has_sdk_ready_shape(self):
		doctype_spec = {
			"paths": {
				"/api/v2/document/ToDo": {
					"get": {
						"tags": ["ToDo"],
						"responses": {
							"200": {
								"description": "OK",
								"content": {
									"application/json": {
										"schema": {"$ref": "#/components/schemas/ToDo_ReadResponse"}
									}
								},
							}
						},
					}
				}
			},
			"components": {
				"schemas": {
					"ToDo_Read": {"$ref": "/openapi/schemas/ToDo.schema.json#/$defs/Read"},
					"ToDo_Create": {
						"type": "object",
						"properties": {
							"items": {
								"type": "array",
								"items": {"$ref": "/openapi/schemas/ToDo%20Item.schema.json#/$defs/Create"},
							},
						},
					},
					"ToDo_ReadResponse": {
						"type": "object",
						"properties": {"data": {"$ref": "#/components/schemas/ToDo_Read"}},
					},
				}
			},
		}
		method_spec = {
			"paths": {
				"/api/method/frappe_openapi.ping": {
					"post": {
						"tags": ["Methods"],
						"responses": {"200": {"description": "OK"}},
					}
				}
			}
		}

		with (
			patch("frappe_openapi.generator.get_installed_apps", return_value=["frappe_openapi"]),
			patch("frappe_openapi.generator.get_doctype_names", return_value=["ToDo"]) as get_doctype_names,
			patch(
				"frappe_openapi.generator.get_whitelisted_method_records",
				return_value=[{"name": "frappe_openapi.ping", "kind": "app"}],
			),
			patch("frappe_openapi.generator.build_doctype_spec", return_value=doctype_spec),
			patch("frappe_openapi.generator.build_method_spec", return_value=method_spec),
			patch(
				"frappe_openapi.generator.build_component_schemas",
				return_value={
					"ToDo_Read": {"type": "object"},
					"ToDo_Item_Create": {"type": "object"},
				},
			),
			patch("frappe_openapi.openapi.absolute_url", side_effect=lambda path: path),
			patch("frappe_openapi.openapi.get_spec_version", return_value="frappe_openapi:1.0.0"),
		):
			bundle = build_app_bundle("frappe_openapi", generated_at="2026-05-24T20:00:00Z")

		get_doctype_names.assert_called_once_with(app="frappe_openapi", include_child_tables=False)
		response_schema = bundle["paths"]["/api/v2/document/ToDo"]["get"]["responses"]["200"]["content"][
			"application/json"
		]["schema"]

		self.assertEqual(bundle["openapi"], "3.2.0")
		self.assertEqual(bundle["$self"], "/openapi/generated/apps/frappe_openapi.json")
		self.assertEqual(bundle["info"]["title"], "frappe_openapi Generated API")
		self.assertEqual(
			bundle["components"]["schemas"],
			{
				"ToDo_Create": {
					"type": "object",
					"properties": {
						"items": {
							"type": "array",
							"items": {"$ref": "#/components/schemas/ToDo_Item_Create"},
						},
					},
				},
				"ToDo_Read": {"type": "object"},
				"ToDo_Item_Create": {"type": "object"},
				"ToDo_ReadResponse": {
					"type": "object",
					"properties": {"data": {"$ref": "#/components/schemas/ToDo_Read"}},
				},
			},
		)
		self.assertEqual(response_schema["$ref"], "#/components/schemas/ToDo_ReadResponse")
		self.assertEqual(bundle["x-frappe-app"], "frappe_openapi")
		self.assertEqual(bundle["x-frappe-generated-at"], "2026-05-24T20:00:00Z")
		self.assertEqual(bundle["x-frappe-doctypes"], ["ToDo"])
		self.assertEqual(bundle["x-frappe-methods"], ["frappe_openapi.ping"])
		self.assertEqual(bundle["x-frappe-standalone-methods"], ["frappe_openapi.ping"])
		self.assertEqual(bundle["tags"], [{"name": "Methods"}, {"name": "ToDo"}])

	def test_build_app_bundle_does_not_overwrite_embedded_doctype_file_methods(self):
		doctype_method = "frappe_openapi.desk.doctype.todo.todo.file_method"
		child_method = "frappe_openapi.desk.doctype.todo_item.todo_item.file_method"
		doctype_spec = {
			"paths": {
				f"/api/v2/method/{doctype_method}": {
					"post": {
						"tags": ["ToDo File-level RPC"],
						"x-frappe-operation-group": "file",
						"responses": {"200": {"description": "OK"}},
					}
				}
			}
		}

		with (
			patch("frappe_openapi.generator.get_installed_apps", return_value=["frappe_openapi"]),
			patch("frappe_openapi.generator.get_doctype_names", return_value=["ToDo"]) as get_doctype_names,
			patch(
				"frappe_openapi.generator.get_whitelisted_method_records",
				return_value=[
					{"name": doctype_method, "kind": "doctype", "doctype": "ToDo"},
					{"name": child_method, "kind": "doctype", "doctype": "ToDo Item"},
				],
			),
			patch("frappe_openapi.generator.build_doctype_spec", return_value=doctype_spec),
			patch("frappe_openapi.generator.build_method_spec") as build_method_spec,
			patch("frappe_openapi.generator.build_component_schemas", return_value={}),
			patch("frappe_openapi.openapi.absolute_url", side_effect=lambda path: path),
			patch("frappe_openapi.openapi.get_spec_version", return_value="frappe_openapi:1.0.0"),
		):
			bundle = build_app_bundle("frappe_openapi", generated_at="2026-05-24T20:00:00Z")

		get_doctype_names.assert_called_once_with(app="frappe_openapi", include_child_tables=False)
		build_method_spec.assert_not_called()
		operation = bundle["paths"][f"/api/v2/method/{doctype_method}"]["post"]
		self.assertEqual(operation["x-frappe-operation-group"], "file")
		self.assertEqual(bundle["x-frappe-methods"], [doctype_method])
		self.assertEqual(bundle["x-frappe-standalone-methods"], [])
