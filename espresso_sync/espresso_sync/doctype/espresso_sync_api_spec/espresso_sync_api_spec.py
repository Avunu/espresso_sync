# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document

from espresso_sync.schema.openapi import (
	SpecError,
	auth_hints,
	list_operations,
	load_spec_text,
	spec_hash,
	spec_version,
	validate_canonical,
)


class EspressoSyncAPISpec(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		auth_hints: DF.JSON | None
		connection: DF.Link | None
		operations: DF.JSON | None
		original_version: DF.Data | None
		source_format: DF.Literal["OpenAPI 3.1", "OpenAPI 3.0", "Swagger 2.0"]
		source_url: DF.Data | None
		spec_hash: DF.Data | None
		spec_json: DF.JSON
		title: DF.Data
	# end: auto-generated types

	def autoname(self):
		# one name per Connection and title, whatever the spec holds
		self.name = f"{self.connection} - {self.title}" if self.connection else self.title

	def validate(self):
		# a share must not let anyone else change what the transforms are built on
		if not self.flags.ignore_permissions:
			frappe.only_for("System Manager")
		spec = self.get_spec()
		self.spec_json = json.dumps(spec, ensure_ascii=False)
		self.spec_hash = spec_hash(spec)
		self.operations = json.dumps(list_operations(spec), ensure_ascii=False)
		self.auth_hints = json.dumps(auth_hints(spec), ensure_ascii=False)
		self.original_version = self.original_version or spec_version(spec)

	def get_spec(self) -> dict:
		"""The spec, read and checked: OpenAPI 3.1, valid, and self-contained."""
		value = self.spec_json
		try:
			spec = value if isinstance(value, dict) else load_spec_text(value or "")
			return validate_canonical(spec)
		except SpecError as e:
			frappe.throw(
				"<br>".join(
					[
						frappe.utils.escape_html(str(e)),
						*(frappe.utils.escape_html(error) for error in e.errors),
					]
				),
				title=_("Invalid API Spec"),
			)
			raise
