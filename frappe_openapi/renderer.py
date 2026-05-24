import mimetypes
from pathlib import Path

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response

from frappe_openapi.openapi import get_document
from frappe_openapi.settings import is_openapi_spec_public, require_swagger_ui_access

OPENAPI_HTTP_CACHE_MAX_AGE = 300
SWAGGER_ASSET_PATH_PREFIX = "swagger-ui-assets/"
SWAGGER_SHELL_ASSET_PATH_PREFIX = "swagger/assets/"
SWAGGER_ASSET_NAMES = {
	"index.css",
	"index.css.map",
	"oauth2-redirect.html",
	"oauth2-redirect.js",
	"swagger-ui-bundle.js",
	"swagger-ui-bundle.js.map",
	"swagger-ui.css",
	"swagger-ui.css.map",
	"swagger-ui-standalone-preset.js",
	"swagger-ui-standalone-preset.js.map",
}
SWAGGER_SHELL_ASSETS = {
	"swagger.css": ("public", "css", "swagger.css"),
	"swagger.js": ("public", "js", "swagger.js"),
}
SWAGGER_TEMPLATE_PATH = "templates/pages/swagger.html"


class OpenAPIRenderer(BaseRenderer):
	def can_render(self):
		return (
			self.path
			in {"openapi.json", "openapi", "swagger", "swagger/oauth2-redirect.html", "swagger/oauth2-redirect.js"}
			or self.path.startswith("openapi/")
			or self.path.startswith(SWAGGER_ASSET_PATH_PREFIX)
			or self.path.startswith(SWAGGER_SHELL_ASSET_PATH_PREFIX)
		)

	def render(self):
		if self.path == "swagger":
			return self.render_swagger()
		if self.path in {"swagger/oauth2-redirect.html", "swagger/oauth2-redirect.js"}:
			return self.render_swagger_asset(self.path.removeprefix("swagger/"))
		if self.path.startswith(SWAGGER_ASSET_PATH_PREFIX):
			return self.render_swagger_asset(self.path.removeprefix(SWAGGER_ASSET_PATH_PREFIX))
		if self.path.startswith(SWAGGER_SHELL_ASSET_PATH_PREFIX):
			return self.render_swagger_shell_asset(self.path.removeprefix(SWAGGER_SHELL_ASSET_PATH_PREFIX))

		path = "openapi.json" if self.path == "openapi" else self.path

		try:
			document = get_document(path)
		except NotFound:
			raise frappe.DoesNotExistError

		response = Response(frappe.as_json(document), mimetype="application/json")
		response.headers["X-Page-Name"] = self.path
		response.headers["Cache-Control"] = get_openapi_cache_control()
		return response

	def render_swagger(self):
		require_swagger_ui_access()

		response = Response(build_swagger_html(), mimetype="text/html")
		response.headers["X-Page-Name"] = self.path
		response.headers["Cache-Control"] = get_openapi_cache_control()
		return response

	def render_swagger_asset(self, asset_name: str):
		if asset_name not in SWAGGER_ASSET_NAMES:
			raise frappe.DoesNotExistError

		asset_path = get_swagger_asset_dir() / asset_name
		if not asset_path.is_file():
			raise frappe.DoesNotExistError

		mimetype = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
		response = Response(asset_path.read_bytes(), mimetype=mimetype)
		response.headers["X-Page-Name"] = self.path
		response.headers["Cache-Control"] = "public, max-age=86400"
		return response

	def render_swagger_shell_asset(self, asset_name: str):
		if asset_name not in SWAGGER_SHELL_ASSETS:
			raise frappe.DoesNotExistError

		asset_path = get_swagger_shell_asset_path(asset_name)
		if not asset_path.is_file():
			raise frappe.DoesNotExistError

		mimetype = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
		response = Response(asset_path.read_bytes(), mimetype=mimetype)
		response.headers["X-Page-Name"] = self.path
		response.headers["Cache-Control"] = "no-store" if frappe._dev_server else "public, max-age=86400"
		return response


def get_swagger_asset_dir() -> Path:
	return Path(frappe.get_app_path("frappe_openapi")).parent / "node_modules" / "swagger-ui-dist"


def get_swagger_shell_asset_path(asset_name: str) -> Path:
	return Path(frappe.get_app_path("frappe_openapi", *SWAGGER_SHELL_ASSETS[asset_name]))


def get_openapi_cache_control() -> str:
	if frappe._dev_server:
		return "no-store"

	visibility = "public" if is_openapi_spec_public() else "private"
	return f"{visibility}, max-age={OPENAPI_HTTP_CACHE_MAX_AGE}"


def build_swagger_html() -> str:
	return frappe.get_template(SWAGGER_TEMPLATE_PATH).render({"csrf_token": get_csrf_token()})


def get_csrf_token() -> str:
	csrf_token = ""
	session = getattr(frappe.local, "session", None)
	if session and getattr(session, "data", None):
		csrf_token = session.data.csrf_token or ""
	return csrf_token
