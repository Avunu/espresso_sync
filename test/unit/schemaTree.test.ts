// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	findNode,
	fromDocTypeSchema,
	fromOpenApiSchema,
	mappableNodes,
	ruleKind,
	type TreeNode,
	walkTree,
} from "../../espresso_sync/public/js/editor/schemaTree.ts";

/** A small OpenAPI document: an order built with allOf, variants, a recursive category, and maps. */
const document = {
	openapi: "3.1.0",
	components: {
		schemas: {
			Base: {
				type: "object",
				required: ["id"],
				properties: {
					id: { type: "integer", readOnly: true },
					created_at: { type: "string", format: "date-time" },
				},
			},
			Card: { title: "Card", type: "object", required: ["last4"], properties: { last4: { type: "string" } } },
			Bank: { type: "object", properties: { iban: { type: "string" } } },
			Category: {
				type: "object",
				properties: {
					name: { type: "string" },
					children: { type: "array", items: { $ref: "#/components/schemas/Category" } },
				},
			},
			Order: {
				allOf: [
					{ $ref: "#/components/schemas/Base" },
					{
						type: "object",
						required: ["lines"],
						properties: {
							note: { oneOf: [{ type: "string" }, { type: "null" }] },
							legacy_note: { type: "string", nullable: true },
							code: { anyOf: [{ type: "string" }, { type: "integer" }] },
							status: { type: "string", enum: ["open", "paid"] },
							tags: { type: "array", items: { type: "string" } },
							metadata: { type: "object", additionalProperties: { type: "string" } },
							anything: {},
							matrix: { type: "array", items: { type: "array", items: { type: "number" } } },
							payment: {
								oneOf: [{ $ref: "#/components/schemas/Card" }, { $ref: "#/components/schemas/Bank" }],
							},
							category: { $ref: "#/components/schemas/Category" },
							lines: {
								type: "array",
								items: {
									type: "object",
									required: ["sku"],
									properties: { sku: { type: "string" }, qty: { type: "number", minimum: 1 } },
								},
							},
						},
					},
				],
			},
		},
	},
};

function child(node: TreeNode, key: string): TreeNode {
	const found = node.children.find((c) => c.key === key);
	assert.ok(found, `${node.pointer || "(root)"} has ${key}`);
	return found;
}

describe("fromOpenApiSchema", () => {
	const tree = fromOpenApiSchema(document.components.schemas.Order, { document });

	it("merges allOf into one object, required lists and all", () => {
		assert.equal(tree.kind, "object");
		assert.deepEqual(
			tree.children.map((c) => c.key),
			[
				"id",
				"created_at",
				"note",
				"legacy_note",
				"code",
				"status",
				"tags",
				"metadata",
				"anything",
				"matrix",
				"payment",
				"category",
				"lines",
			],
		);
		assert.equal(child(tree, "id").required, "hard");
		assert.equal(child(tree, "id").readOnly, true);
		assert.equal(child(tree, "lines").required, "hard");
		assert.equal(child(tree, "note").required, null);
		assert.equal(child(tree, "created_at").format, "date-time");
	});

	it("folds null-only variants and OAS 3.0 nullable into a nullable field", () => {
		const note = child(tree, "note");
		assert.equal(note.kind, "field");
		assert.deepEqual(note.types, ["string"]);
		assert.equal(note.nullable, true);
		const legacy = child(tree, "legacy_note");
		assert.deepEqual([legacy.kind, legacy.types, legacy.nullable], ["field", ["string"], true]);
	});

	it("makes a union of scalar variants one field", () => {
		const code = child(tree, "code");
		assert.equal(code.kind, "field");
		assert.deepEqual(code.types, ["string", "integer"]);
		assert.equal(code.variants, undefined);
		assert.deepEqual(child(tree, "status").enum, ["open", "paid"]);
	});

	it("gives a folded union an enum only when every option is a fixed set", () => {
		const mixed = fromOpenApiSchema({
			type: "object",
			properties: {
				status: { oneOf: [{ type: "string", enum: ["a", "b"] }, { type: "integer" }] },
				level: { anyOf: [{ enum: ["low", "high"] }, { const: 3 }, { type: "null" }] },
			},
		});
		const status = child(mixed, "status");
		assert.deepEqual([status.kind, status.types, status.enum], ["field", ["string", "integer"], undefined]);
		const level = child(mixed, "level");
		assert.deepEqual(
			[level.types, level.enum, level.nullable],
			[["string", "integer"], ["low", "high", 3], true],
		);
	});

	it("makes object variants a variant group", () => {
		const payment = child(tree, "payment");
		assert.equal(payment.kind, "variants");
		assert.equal(payment.variantMode, "oneOf");
		assert.deepEqual(
			payment.variants?.map((v) => [v.label, v.node.children.map((c) => c.pointer)]),
			[
				["Card", ["/payment/last4"]],
				["Bank", ["/payment/iban"]],
			],
		);
		assert.equal(payment.variants?.[0]?.node.children[0]?.required, "hard");
	});

	it("stops at a recursive reference with a cycle node", () => {
		const children = child(child(tree, "category"), "children");
		assert.equal(children.kind, "collection");
		assert.equal(children.cycle, "#/components/schemas/Category");
		assert.deepEqual(children.children, []);
	});

	it("tells collections, scalar collections, maps and leaves apart", () => {
		const lines = child(tree, "lines");
		assert.equal(lines.kind, "collection");
		assert.deepEqual(
			lines.children.map((c) => [c.pointer, c.required]),
			[
				["/lines/sku", "hard"],
				["/lines/qty", null],
			],
		);
		const tags = child(tree, "tags");
		assert.deepEqual([tags.kind, tags.itemTypes], ["scalar_collection", ["string"]]);
		const metadata = child(tree, "metadata");
		assert.deepEqual([metadata.kind, metadata.itemTypes, metadata.open], ["map", ["string"], true]);
		assert.deepEqual([child(tree, "anything").kind, child(tree, "anything").types], ["field", []]);
		assert.equal(child(tree, "matrix").kind, "field");
	});

	it("turns the server's x-cycle marker into a cycle node", () => {
		const marked = fromOpenApiSchema({
			type: "object",
			properties: { parent: { "x-cycle": "#/components/schemas/Node" } },
		});
		assert.deepEqual(
			[child(marked, "parent").kind, child(marked, "parent").cycle],
			["cycle", "#/components/schemas/Node"],
		);
	});

	it("handles a top-level array, keywords beside $ref, and refs it can't resolve", () => {
		const list = fromOpenApiSchema(
			{ type: "array", items: { $ref: "#/components/schemas/Card", description: "A saved card" } },
			{ document },
		);
		assert.equal(list.kind, "collection");
		assert.equal(list.pointer, "");
		assert.deepEqual(
			list.children.map((c) => c.pointer),
			["/last4"],
		);
		assert.equal(list.description, "A saved card");
		const missing = fromOpenApiSchema({ $ref: "#/nowhere", type: "string" });
		assert.deepEqual([missing.kind, missing.types], ["field", ["string"]]);
		const scalars = fromOpenApiSchema({ type: "array", items: { enum: ["a", "b"] } });
		assert.deepEqual(
			[scalars.kind, scalars.itemTypes, scalars.enum],
			["scalar_collection", ["string"], ["a", "b"]],
		);
	});

	it("keeps properties declared beside a variant group", () => {
		const node = fromOpenApiSchema({
			type: "object",
			properties: { kind: { type: "string" } },
			anyOf: [
				{ type: "object", properties: { a: { type: "string" } } },
				{ type: "object", properties: { b: { type: "string" } } },
			],
		});
		assert.equal(node.kind, "object");
		assert.equal(node.variantMode, "anyOf");
		assert.deepEqual(
			node.children.map((c) => c.key),
			["kind"],
		);
		assert.deepEqual(
			[...walkTree(node)].map((n) => n.pointer),
			["", "/kind", "/a", "/b"],
		);
	});

	it("merges a property declared in two allOf parts", () => {
		const node = fromOpenApiSchema({
			allOf: [
				{ type: "object", properties: { qty: { type: "number" } } },
				{ type: "object", properties: { qty: { type: "integer", minimum: 0 } }, additionalProperties: false },
			],
		});
		assert.deepEqual(child(node, "qty").types, ["integer"]);
		assert.equal(node.open, false);
	});
});

/** The x-frappe of a field, as doctype_json_schema writes it: every key, null when unset. */
function xFrappe(fieldtype: string, extra: Record<string, unknown> = {}) {
	return {
		fieldtype,
		options: null,
		link: null,
		dynamic_link: null,
		required: null,
		read_only: false,
		custom: false,
		...extra,
	};
}

/** A standard field (`doctype`, and `name` or a read's `modified`…), as the server writes it. */
function standard(type: string, fieldtype: string, title: string, extra: Record<string, unknown> = {}) {
	return { type, title, "x-frappe": xFrappe(fieldtype, { read_only: true }), ...extra };
}

/** doctype_json_schema("Contact", "insert"), cut down to the fields the tests read. */
const contact = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	type: "object",
	title: "Contact",
	"x-frappe": { doctype: "Contact", mode: "insert", istable: false },
	properties: {
		doctype: standard("string", "Data", "DocType", { const: "Contact" }),
		name: { type: "string", title: "ID", "x-frappe": xFrappe("Data") },
		first_name: {
			type: "string",
			maxLength: 140,
			title: "First Name",
			"x-frappe": xFrappe("Data", { required: "hard" }),
		},
		status: {
			type: "string",
			enum: ["Passive", "Open", "Replied"],
			title: "Status",
			"x-frappe": xFrappe("Select", { options: "Passive\nOpen\nReplied", required: "server" }),
		},
		unsubscribed: {
			type: ["integer", "boolean"],
			enum: [0, 1, false, true],
			title: "Unsubscribed",
			"x-frappe": xFrappe("Check"),
		},
		birthday: { type: "string", format: "date", title: "Birthday", "x-frappe": xFrappe("Date") },
		company_name: {
			type: "string",
			maxLength: 140,
			title: "Company Name",
			"x-frappe": xFrappe("Link", { options: "Company", link: "Company", custom: true }),
		},
		email_ids: {
			type: "array",
			title: "Email IDs",
			"x-frappe": xFrappe("Table", { options: "Contact Email" }),
			items: {
				type: "object",
				title: "Contact Email",
				"x-frappe": { doctype: "Contact Email", mode: "insert", istable: true },
				properties: {
					doctype: standard("string", "Data", "DocType", { const: "Contact Email" }),
					name: { type: "string", title: "ID", "x-frappe": xFrappe("Data") },
					email_id: {
						type: "string",
						format: "email",
						title: "Email ID",
						"x-frappe": xFrappe("Data", { options: "Email", required: "hard" }),
					},
					is_primary: {
						type: ["integer", "boolean"],
						enum: [0, 1, false, true],
						title: "Is Primary",
						"x-frappe": xFrappe("Check"),
					},
				},
				required: ["email_id"],
				additionalProperties: false,
			},
		},
		links: {
			type: "array",
			title: "Links",
			"x-frappe": xFrappe("Table", { options: "Dynamic Link" }),
			items: {
				type: "object",
				title: "Dynamic Link",
				"x-frappe": { doctype: "Dynamic Link", mode: "insert", istable: true },
				properties: {
					doctype: standard("string", "Data", "DocType", { const: "Dynamic Link" }),
					link_doctype: {
						type: "string",
						title: "Link Document Type",
						"x-frappe": xFrappe("Link", { options: "DocType", link: "DocType", required: "hard" }),
					},
					link_name: {
						type: "string",
						title: "Link Name",
						"x-frappe": xFrappe("Dynamic Link", {
							options: "link_doctype",
							dynamic_link: "link_doctype",
							required: "hard",
						}),
					},
				},
				required: ["link_doctype", "link_name"],
				additionalProperties: false,
			},
		},
	},
	required: ["first_name"],
	additionalProperties: false,
};

/** doctype_json_schema("ToDo", "read"), cut down: the standard fields, and no required tiers. */
const todoRead = {
	$schema: "https://json-schema.org/draft/2020-12/schema",
	type: "object",
	title: "ToDo",
	"x-frappe": { doctype: "ToDo", mode: "read", istable: false },
	properties: {
		doctype: standard("string", "Data", "DocType", { const: "ToDo" }),
		name: standard("string", "Data", "ID"),
		owner: {
			type: "string",
			title: "Created By",
			"x-frappe": xFrappe("Link", { options: "User", link: "User", read_only: true }),
		},
		modified: standard("string", "Datetime", "Last Updated On", { format: "date-time" }),
		docstatus: standard("integer", "Int", "Document Status"),
		description: { type: "string", title: "Description", "x-frappe": xFrappe("Text Editor") },
	},
	required: [],
	additionalProperties: false,
};

describe("fromDocTypeSchema", () => {
	const tree = fromDocTypeSchema(contact);

	it("reads the required tier from x-frappe", () => {
		assert.equal(tree.title, "Contact");
		assert.deepEqual(
			tree.children.map((c) => [c.key, c.required]),
			[
				["name", null],
				["first_name", "hard"],
				["status", "server"],
				["unsubscribed", null],
				["birthday", null],
				["company_name", null],
				["email_ids", null],
				["links", null],
			],
		);
	});

	it("leaves out the doctype, which only names the DocType", () => {
		for (const node of walkTree(tree)) assert.notEqual(node.key, "doctype", node.pointer);
		assert.equal(findNode(tree, "/doctype"), undefined);
		assert.equal(findNode(tree, "/email_ids/doctype"), undefined);
	});

	it("keeps field metadata for the editor", () => {
		const company = child(tree, "company_name");
		assert.deepEqual(company.frappe, {
			fieldtype: "Link",
			options: "Company",
			link: "Company",
			dynamicLink: undefined,
			custom: true,
		});
		assert.equal(child(child(tree, "links"), "link_name").frappe?.dynamicLink, "link_doctype");
		assert.equal(child(tree, "status").frappe?.options, "Passive\nOpen\nReplied");
		const birthday = child(tree, "birthday");
		assert.deepEqual([birthday.types, birthday.nullable, birthday.format], [["string"], false, "date"]);
		// an insert may name its document
		assert.equal(child(tree, "name").readOnly, false);
	});

	it("makes a Check one field that takes 0, 1, true or false", () => {
		const check = child(tree, "unsubscribed");
		assert.deepEqual(
			[check.kind, check.types, check.enum, check.frappe?.fieldtype],
			["field", ["integer", "boolean"], [0, 1, false, true], "Check"],
		);
		assert.equal(ruleKind(check), "field");
	});

	it("makes child tables collections with pointers that match rule keys", () => {
		const emails = child(tree, "email_ids");
		assert.equal(emails.kind, "collection");
		assert.equal(emails.frappe?.fieldtype, "Table");
		assert.deepEqual(
			emails.children.map((c) => [c.pointer, c.required]),
			[
				["/email_ids/name", null],
				["/email_ids/email_id", "hard"],
				["/email_ids/is_primary", null],
			],
		);
		assert.equal(emails.open, false);
		assert.equal(findNode(tree, "/links/link_doctype")?.frappe?.link, "DocType");
		assert.equal(findNode(tree, "/nope"), undefined);
	});

	it("lists what a rule can fill, with the rule kind for each", () => {
		const nodes = mappableNodes(tree);
		assert.deepEqual(
			nodes.map((n) => [n.pointer, ruleKind(n)]),
			[
				["/name", "field"],
				["/first_name", "field"],
				["/status", "field"],
				["/unsubscribed", "field"],
				["/birthday", "field"],
				["/company_name", "field"],
				["/email_ids", "collection"],
				["/email_ids/name", "field"],
				["/email_ids/email_id", "field"],
				["/email_ids/is_primary", "field"],
				["/links", "collection"],
				["/links/link_doctype", "field"],
				["/links/link_name", "field"],
			],
		);
		assert.equal(ruleKind(tree), undefined);
		assert.equal(ruleKind({ ...tree, kind: "scalar_collection" }), "scalar_collection");
		assert.equal(ruleKind({ ...tree, kind: "cycle" }), undefined);
	});

	it("reads a document as an export does: standard fields read-only, nothing required", () => {
		const read = fromDocTypeSchema(todoRead);
		assert.deepEqual(
			read.children.map((c) => [c.key, c.readOnly, c.required, c.types]),
			[
				["name", true, null, ["string"]],
				["owner", true, null, ["string"]],
				["modified", true, null, ["string"]],
				["docstatus", true, null, ["integer"]],
				["description", false, null, ["string"]],
			],
		);
		assert.equal(child(read, "modified").format, "date-time");
		assert.equal(child(read, "owner").frappe?.link, "User");
	});
});
