# Copyright (c) 2026, ALYF GbmH and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class OpenAPISettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allow_spec_access_for: DF.Literal["Nobody", "System Manager", "Desk User", "Guest"]
		enable_swagger_ui: DF.Check
	# end: auto-generated types

	pass
