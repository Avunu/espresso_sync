// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import {
	byRule,
	countBySeverity,
	type Diagnostic,
	fromAjvErrors,
	mergeDiagnostics,
	nearestRule,
	sortDiagnostics,
	stripIndexes,
} from "../../espresso_sync/public/js/editor/diagnostics.ts";
import { fromOpenApiSchema } from "../../espresso_sync/public/js/editor/schemaTree.ts";

const schema = {
	type: "object",
	required: ["customer", "lines"],
	additionalProperties: false,
	properties: {
		customer: { type: "string" },
		status: { enum: ["Draft", "Submitted"] },
		delivery_date: { type: "string", format: "date" },
		lines: {
			type: "array",
			items: {
				type: "object",
				required: ["item_code"],
				properties: { item_code: { type: "string" }, qty: { type: "number" } },
			},
		},
		// A key made of digits, which is not an array index.
		totals: { type: "object", properties: { "2026": { type: "number" } } },
	},
};

function validate(data: unknown) {
	const ajv = new Ajv2020({ allErrors: true, strict: false });
	ajv.addFormat("date", /^\d{4}-\d{2}-\d{2}$/);
	const check = ajv.compile(schema);
	assert.equal(check(data), false);
	return check.errors ?? [];
}

const produced = {
	status: "Open",
	delivery_date: "soon",
	lines: [{ item_code: "MUG" }, { qty: "two" }],
	totals: { "2026": "lots" },
	shipping: 5,
};

describe("diagnostics", () => {
	it("maps each validator error to the rule that produced the value", () => {
		const rules = ["/customer", "/status", "/delivery_date", "/lines", "/lines/qty", "/totals/2026"];
		const diagnostics = fromAjvErrors(validate(produced), {
			rules,
			item: 3,
			tree: fromOpenApiSchema(schema),
		});
		const summary = sortDiagnostics(diagnostics).map((d) => [d.rule, d.path, d.code, d.message]);
		assert.deepEqual(summary, [
			["/customer", "/customer", "schema.required", "“customer” is required"],
			["/delivery_date", "/delivery_date", "schema.format", "must be a date"],
			["/lines", "/lines/1/item_code", "schema.required", "“item_code” is required"],
			["/lines/qty", "/lines/1/qty", "schema.type", "must be number"],
			["/shipping", "/shipping", "schema.additionalProperties", "“shipping” is not a field of the target"],
			["/status", "/status", "schema.enum", 'must be one of "Draft", "Submitted"'],
			["/totals/2026", "/totals/2026", "schema.type", "must be number"],
		]);
		assert.ok(diagnostics.every((d) => d.item === 3 && d.origin === "client" && d.severity === "error"));
	});

	it("takes a severity per error, and an origin", () => {
		const diagnostics = fromAjvErrors(validate({ lines: [] }), {
			origin: "server",
			severity: (error) => (error.keyword === "required" ? "warning" : "error"),
		});
		assert.deepEqual(
			diagnostics.map((d) => [d.rule, d.severity, d.origin, "item" in d]),
			[["/customer", "warning", "server", false]],
		);
		assert.deepEqual(fromAjvErrors(null), []);
		assert.deepEqual(fromAjvErrors(validate({ lines: [] }), { severity: "info" })[0]?.severity, "info");
	});

	it("falls back to the validator's message for other keywords", () => {
		const [diagnostic] = fromAjvErrors([
			{
				instancePath: "/qty",
				schemaPath: "#/minimum",
				keyword: "minimum",
				params: { limit: 1 },
				message: "must be >= 1",
			},
			{ instancePath: "/x", schemaPath: "#/const", keyword: "const", params: { allowedValue: 1 } },
		]);
		assert.equal(diagnostic?.message, "must be >= 1");
		const [, constant] = fromAjvErrors([
			{ instancePath: "/qty", schemaPath: "#/minimum", keyword: "minimum", params: {} },
			{ instancePath: "/x", schemaPath: "#/const", keyword: "const", params: { allowedValue: 1 } },
		]);
		assert.equal(constant?.message, "must be 1");
		assert.equal(
			fromAjvErrors([{ instancePath: "", schemaPath: "#/not", keyword: "not", params: {} }])[0]?.message,
			"fails not",
		);
	});

	it("strips array indexes, using the tree to tell them from digit keys", () => {
		const tree = fromOpenApiSchema(schema);
		assert.equal(stripIndexes("/lines/12/qty", tree), "/lines/qty");
		assert.equal(stripIndexes("/totals/2026", tree), "/totals/2026");
		assert.equal(stripIndexes("/totals/2026"), "/totals");
		assert.equal(stripIndexes("/0/name", fromOpenApiSchema({ type: "array", items: schema })), "/name");
		assert.equal(stripIndexes(""), "");
	});

	it("finds fields inside a variant group's options", () => {
		const tree = fromOpenApiSchema({
			type: "object",
			properties: {
				payments: {
					type: "array",
					items: {
						oneOf: [
							{
								type: "object",
								properties: { card: { type: "object", properties: { "0": { type: "string" } } } },
							},
							{ type: "object", properties: { iban: { type: "string" } } },
						],
					},
				},
			},
		});
		assert.equal(stripIndexes("/payments/3/card/0", tree), "/payments/card/0");
		assert.equal(stripIndexes("/payments/3/iban", tree), "/payments/iban");
		assert.equal(stripIndexes("/payments/3/other/1", tree), "/payments/other/1");
	});

	it("finds the nearest rule at or above a pointer", () => {
		const rules = new Set(["/lines", ""]);
		assert.equal(nearestRule("/lines/qty", rules), "/lines");
		assert.equal(nearestRule("/other", rules), "");
		assert.equal(nearestRule("/other", new Set()), "/other");
	});

	it("replaces one origin's findings, keeps the other's, and drops duplicates", () => {
		const base = { path: "/a", severity: "error", code: "x", message: "m" } as const;
		const client: Diagnostic = { ...base, rule: "/a", origin: "client" };
		const oldServer: Diagnostic = { ...base, rule: "/b", origin: "server" };
		const fresh: Diagnostic[] = [
			{ ...base, rule: "/c", origin: "server", severity: "warning" },
			{ ...base, rule: "/c", origin: "server", severity: "warning" },
		];
		const merged = mergeDiagnostics([client, oldServer], fresh, "server");
		assert.deepEqual(
			merged.map((d) => [d.rule, d.origin]),
			[
				["/a", "client"],
				["/c", "server"],
			],
		);
		assert.deepEqual(countBySeverity(merged), { error: 1, warning: 1, info: 0 });
		const grouped = byRule([...merged, { ...client, item: 2 }]);
		assert.deepEqual([...grouped.keys()], ["/a", "/c"]);
		assert.equal(grouped.get("/a")?.length, 2);
	});

	it("sorts errors before warnings, then by rule, path and item", () => {
		const d = (rule: string, severity: Diagnostic["severity"], item?: number): Diagnostic => ({
			rule,
			path: rule,
			severity,
			code: "c",
			message: "m",
			origin: "client",
			...(item === undefined ? {} : { item }),
		});
		const sorted = sortDiagnostics([
			d("/b", "warning"),
			d("/b", "error", 2),
			d("/a", "info"),
			d("/b", "error", 1),
			d("/b", "error"),
		]);
		assert.deepEqual(
			sorted.map((x) => [x.rule, x.severity, x.item]),
			[
				["/b", "error", undefined],
				["/b", "error", 1],
				["/b", "error", 2],
				["/b", "warning", undefined],
				["/a", "info", undefined],
			],
		);
	});
});
