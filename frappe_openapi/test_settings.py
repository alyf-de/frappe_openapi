from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe_openapi import openapi
from frappe_openapi import renderer as openapi_renderer
from frappe_openapi import settings as openapi_settings


class TestOpenAPISettings(TestCase):
	def has_access(self, access_for: str | None, user: str, roles: list[str]) -> bool:
		def get_single_value(doctype: str, fieldname: str):
			if fieldname == "allow_spec_access_for":
				return access_for
			return None

		with (
			patch.object(openapi_settings.frappe, "get_single_value", get_single_value),
			patch.object(openapi_settings.frappe, "session", SimpleNamespace(user=user), create=True),
			patch.object(openapi_settings.frappe, "get_roles", return_value=roles),
		):
			return openapi_settings.has_openapi_spec_access()

	def test_default_spec_access_is_limited_to_privileged_users(self):
		self.assertTrue(self.has_access(None, "manager@example.com", ["System Manager"]))
		self.assertTrue(self.has_access(None, "developer@example.com", ["Developer"]))
		self.assertTrue(self.has_access(None, "Administrator", []))
		self.assertFalse(self.has_access(None, "desk@example.com", ["Desk User"]))
		self.assertFalse(self.has_access(None, "Guest", []))

	def test_configured_access_modes_are_honored(self):
		self.assertFalse(self.has_access("Nobody", "manager@example.com", ["System Manager"]))
		self.assertTrue(self.has_access("Nobody", "Administrator", []))
		self.assertTrue(self.has_access("Desk User", "desk@example.com", ["Desk User"]))
		self.assertTrue(self.has_access("Desk User", "developer@example.com", ["Developer"]))
		self.assertFalse(self.has_access("Desk User", "website@example.com", ["Website User"]))
		self.assertTrue(self.has_access("Guest", "Guest", []))

	def test_openapi_routes_require_spec_access(self):
		with (
			patch("frappe_openapi.openapi.require_openapi_spec_access") as require_access,
			patch("frappe_openapi.openapi.build_root_spec", return_value={"openapi": "3.2.0"}),
		):
			self.assertEqual(openapi.get_document("openapi.json"), {"openapi": "3.2.0"})

		require_access.assert_called_once_with()

	def test_generated_routes_share_spec_access(self):
		with (
			patch("frappe_openapi.openapi.require_openapi_spec_access") as require_access,
			patch("frappe_openapi.openapi.read_manifest", return_value={"apps": {}}),
		):
			self.assertEqual(openapi.get_document("openapi/generated/manifest.json"), {"apps": {}})

		require_access.assert_called_once_with()

	def test_swagger_html_requires_swagger_access(self):
		with (
			patch("frappe_openapi.renderer.require_swagger_ui_access") as require_access,
			patch("frappe_openapi.renderer.build_swagger_html", return_value="<html></html>"),
			patch("frappe_openapi.renderer.get_openapi_cache_control", return_value="private, max-age=300"),
		):
			response = openapi_renderer.OpenAPIRenderer.render_swagger(SimpleNamespace(path="swagger"))

		require_access.assert_called_once_with()
		self.assertEqual(response.headers["Cache-Control"], "private, max-age=300")

	def test_cache_control_uses_settings_visibility_and_fixed_max_age(self):
		with (
			patch.object(openapi_renderer.frappe, "_dev_server", False, create=True),
			patch("frappe_openapi.renderer.is_openapi_spec_public", return_value=True),
		):
			self.assertEqual(openapi_renderer.get_openapi_cache_control(), "public, max-age=300")
