// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { fromOpenApiSchema } from "../../espresso_sync/public/js/editor/schemaTree.ts";
import {
	compatibility,
	describeType,
	inferFromSamples,
	inferType,
	jsonType,
	mergeTypes,
	stringFormat,
	toJsonSchema,
} from "../../espresso_sync/public/js/editor/typeInfer.ts";

const order = {
	id: 1001,
	created_at: "2026-01-15T10:00:00Z",
	customer: { email: "ada@example.com", first_name: "Ada" },
	line_items: [
		{ sku: "MUG-12", quantity: 2, price: "18.00" },
		{ sku: "KTL-1L", quantity: 1, price: "64.00", gift: true },
	],
	tags: [],
	note: null,
};

describe("typeInfer", () => {
	it("names JSON types, integer apart from number", () => {
		assert.deepEqual([1, 1.5, "a", true, null, [], {}, undefined].map(jsonType), [
			"integer",
			"number",
			"string",
			"boolean",
			"null",
			"array",
			"object",
			"undefined",
		]);
	});

	it("recognises the date and time shapes Frappe uses", () => {
		assert.equal(stringFormat("2026-01-15"), "date");
		assert.equal(stringFormat("2026-01-15 10:00:00.000000"), "date-time");
		assert.equal(stringFormat("2026-01-15T10:00:00+05:30"), "date-time");
		assert.equal(stringFormat("10:00"), "time");
		assert.equal(stringFormat("tomorrow"), undefined);
	});

	it("infers a document, items merged and keys required only when always present", () => {
		const type = inferType(order);
		assert.deepEqual(type.types, ["object"]);
		assert.deepEqual(type.required, ["created_at", "customer", "id", "line_items", "note", "tags"]);
		assert.equal(type.properties?.["created_at"]?.format, "date-time");
		const items = type.properties?.["line_items"]?.items;
		assert.deepEqual(items?.required, ["price", "quantity", "sku"]);
		assert.deepEqual(items?.properties?.["gift"]?.types, ["boolean"]);
		assert.equal(type.properties?.["tags"]?.items, undefined);
		assert.equal(type.unsafeInteger, undefined);
	});

	it("flags a whole number JSON parsing has already rounded", () => {
		const type = inferType(JSON.parse('{"id": 12345678901234567890, "list": [9007199254740993]}'));
		assert.equal(type.unsafeInteger, true);
		assert.equal(type.properties?.["list"]?.unsafeInteger, true);
	});

	it("merges samples: unions types, folds integer into number, keeps a shared format", () => {
		const merged = inferFromSamples([1, 2.5, null]);
		assert.deepEqual(merged?.types, ["null", "number"]);
		assert.equal(merged?.count, 3);
		assert.equal(inferFromSamples([]), undefined);
		assert.equal(mergeTypes(inferType("2026-01-01"), inferType("2026-02-01")).format, "date");
		assert.equal(mergeTypes(inferType("2026-01-01"), inferType("10:00")).format, undefined);
		assert.equal(mergeTypes(inferType("2026-01-01"), inferType(null)).format, "date");
		assert.equal(mergeTypes(inferType(null), inferType("2026-01-01")).format, "date");
		const objects = mergeTypes(inferType({ a: 1 }), inferType({ a: 2, b: "x" }));
		assert.deepEqual(objects.required, ["a"]);
		const mixed = mergeTypes(inferType([1]), inferType("x"));
		assert.deepEqual(mixed.items?.types, ["integer"]);
		const objectOrString = mergeTypes(inferType("x"), inferType({ a: 1 }));
		assert.deepEqual(objectOrString.required, ["a"]);
	});

	it("types what an expression returned, nothing included", () => {
		assert.deepEqual(inferType(undefined).types, ["undefined"]);
		assert.equal(describeType(mergeTypes(inferType("a"), inferType(undefined))), "string | undefined");
		assert.equal(describeType(inferType([{ a: 1 }])), "array<object>");
		assert.equal(describeType(inferType([])), "array");
	});

	it("writes a JSON Schema the schema tree can read", () => {
		const schema = toJsonSchema(inferType(order));
		const tree = fromOpenApiSchema(schema);
		const lines = tree.children.find((c) => c.key === "line_items");
		assert.equal(lines?.kind, "collection");
		assert.deepEqual(
			lines?.children.map((c) => [c.key, c.required]),
			[
				["sku", "hard"],
				["quantity", "hard"],
				["price", "hard"],
				["gift", null],
			],
		);
		assert.deepEqual(toJsonSchema(mergeTypes(inferType(1), inferType("x"))), { type: ["integer", "string"] });
		assert.deepEqual(toJsonSchema(inferType(undefined)), {});
	});

	it("says whether values fit a field: ok, coerced (a warning) or a mismatch", () => {
		const text = { types: ["string"], nullable: false };
		const number = { types: ["number"], nullable: true };
		assert.deepEqual(compatibility(inferType("a"), text), { status: "ok" });
		assert.deepEqual(compatibility(inferType(1), number), { status: "ok" });
		assert.deepEqual(compatibility(inferType("x"), { types: [], nullable: false }), { status: "ok" });
		assert.equal(compatibility(inferType(5), text).status, "coerced");
		assert.equal(compatibility(inferType("18.00"), number).status, "coerced");
		assert.equal(compatibility(inferType(true), { types: ["integer"], nullable: false }).status, "coerced");
		assert.equal(compatibility(inferType(null), text).status, "coerced");
		assert.deepEqual(compatibility(inferType(null), number), { status: "ok" });
		assert.deepEqual(compatibility(inferType(undefined), text), { status: "ok" });
		const mismatch = compatibility(inferType({ a: 1 }), text);
		assert.equal(mismatch.status, "mismatch");
		assert.ok(mismatch.status === "mismatch" && mismatch.message.includes("object"));
		const date = compatibility(inferType("2026-01-15 10:00:00"), {
			types: ["string"],
			nullable: false,
			format: "date",
		});
		assert.equal(date.status, "coerced");
	});
});
