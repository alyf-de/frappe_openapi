import frappe
from frappe.utils import cint

OPENAPI_SETTINGS_DOCTYPE = "OpenAPI Settings"
DEFAULT_SPEC_ACCESS_FOR = "System Manager"
PRIVILEGED_SPEC_ROLES = {"System Manager", "Developer"}


def is_swagger_ui_enabled() -> bool:
	enabled = frappe.get_single_value(OPENAPI_SETTINGS_DOCTYPE, "enable_swagger_ui")
	if enabled is None:
		enabled = 1
	return bool(cint(enabled))


def get_spec_access_for() -> str:
	return frappe.get_single_value(OPENAPI_SETTINGS_DOCTYPE, "allow_spec_access_for") or DEFAULT_SPEC_ACCESS_FOR


def has_openapi_spec_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	access_for = get_spec_access_for()
	if access_for == "Guest":
		return True
	if not user or user == "Guest" or access_for == "Nobody":
		return False

	roles = set(frappe.get_roles(user))
	if roles.intersection(PRIVILEGED_SPEC_ROLES):
		return True
	if access_for == "Desk User":
		return "Desk User" in roles

	return False


def is_openapi_spec_public() -> bool:
	return get_spec_access_for() == "Guest"


def require_openapi_spec_access() -> None:
	if has_openapi_spec_access():
		return

	frappe.throw(
		frappe._("Not permitted to access OpenAPI specs."),
		frappe.PermissionError,
	)


def require_swagger_ui_access() -> None:
	if not is_swagger_ui_enabled():
		frappe.throw(
			frappe._("Swagger UI is disabled."),
			frappe.PermissionError,
		)

	require_openapi_spec_access()
