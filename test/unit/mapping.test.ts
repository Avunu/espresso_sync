// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import jsonata from "jsonata";
import { compileRules, type Rule } from "../../espresso_sync/public/js/editor/compile.ts";
import type { Diagnostic } from "../../espresso_sync/public/js/editor/diagnostics.ts";
import {
	answerOf,
	outputDiagnostics,
	ruleLinks,
	ruleReads,
	insertSnippet,
	collectionChain,
	itemRanges,
	itemsSchema,
	mappingCounts,
	pathExpression,
	probeExpression,
	probesExpression,
	probeValues,
	requiredUnmapped,
	resultDiagnostics,
	ruleDiagnostics,
	ruleResults,
	sampleItems,
	schemaValidator,
	shownRow,
	simplePath,
	sourceContext,
	sourceReference,
	syntaxError,
	targetFields,
	valueCompatibility,
	valuesAt,
	withAncestors,
	withoutRepeats,
} from "../../espresso_sync/public/js/editor/mapping.ts";
import {
	findNode,
	fromOpenApiSchema,
	type TreeNode,
} from "../../espresso_sync/public/js/editor/schemaTree.ts";

function rulesOf(...list: [string, Rule["kind"], string][]): Map<string, Rule> {
	return new Map(list.map(([ptr, kind, expr]) => [ptr, { ptr, kind, expr }]));
}

const order = {
	order_number: 1042,
	currency: "USD",
	customer: { first_name: "Dana" },
	line_items: [
		{ sku: "MUG", quantity: 2, parts: [{ code: "a" }, { code: "b" }] },
		{ sku: "KTL", quantity: 1, parts: { code: "c" } },
	],
};

/** A sales order request body: a required customer, lines with a required item code, tags. */
const target = fromOpenApiSchema({
	type: "object",
	required: ["externalId", "lines"],
	properties: {
		externalId: { type: "string" },
		total: { type: "number" },
		customer: {
			type: "object",
			required: ["name"],
			properties: { name: { type: "string" }, email: { type: "string" } },
		},
		lines: {
			type: "array",
			items: {
				type: "object",
				required: ["itemCode"],
				properties: {
					itemCode: { type: "string" },
					qty: { type: "integer" },
					parts: { type: "array", items: { type: "object", properties: { code: { type: "string" } } } },
				},
			},
		},
		tags: { type: "array", items: { type: "string" } },
	},
});

function node(pointer: string): TreeNode {
	const found = findNode(target, pointer);
	assert.ok(found, pointer);
	return found;
}

async function run(expression: string, input: unknown): Promise<unknown> {
	return (await jsonata(expression).evaluate(input)) as unknown;
}

describe("mapping", () => {
	it("reads an expression that is only a path", () => {
		assert.deepEqual(simplePath("customer.first_name"), {
			absolute: false,
			segments: ["customer", "first_name"],
		});
		assert.deepEqual(simplePath("`odd name`"), { absolute: false, segments: ["odd name"] });
		assert.deepEqual(simplePath("$$.line_items"), { absolute: true, segments: ["line_items"] });
		assert.deepEqual(simplePath("$"), { absolute: false, segments: [] });
		assert.deepEqual(simplePath("$.sku"), { absolute: false, segments: ["sku"] });
		for (const expression of [
			"line_items[0]",
			"a.b[]",
			'"x"',
			"$sum(a)",
			"a{b: c}",
			"a@$x",
			"a#$i",
			"a.(",
			"a ? b : c",
		]) {
			assert.equal(simplePath(expression), undefined, expression);
		}
	});

	it("writes field names as a path, quoting what isn't a plain name", () => {
		assert.equal(pathExpression(["customer", "first_name"]), "customer.first_name");
		assert.equal(pathExpression(["odd name", "and", "x1"]), "`odd name`.`and`.x1");
	});

	it("finds the collections a rule runs under, and the source items that is", () => {
		const rules = rulesOf(
			["/lines", "collection", "line_items"],
			["/lines/parts", "collection", "parts"],
			["/lines/parts/code", "field", "code"],
			["/tags", "scalar_collection", "tags"],
		);
		assert.deepEqual(
			collectionChain("/lines/parts/code", rules).map((rule) => rule.ptr),
			["/lines", "/lines/parts"],
		);
		assert.deepEqual(collectionChain("/lines", rules), []);
		assert.deepEqual(sourceContext("/lines/parts/code", rules), ["line_items", "parts"]);
		assert.deepEqual(sourceContext("/lines/qty", rules), ["line_items"]);
		assert.deepEqual(sourceContext("/externalId", rules), []);
		const computed = rulesOf(["/lines", "collection", "line_items[quantity > 1]"]);
		assert.equal(sourceContext("/lines/qty", computed), undefined);
		const rooted = rulesOf(
			["/lines", "collection", "line_items"],
			["/lines/parts", "collection", "$$.line_items"],
		);
		assert.deepEqual(sourceContext("/lines/parts/code", rooted), ["line_items"]);
	});

	it("writes a source field as the rule reads it where it runs", () => {
		const rules = rulesOf(["/lines", "collection", "line_items"]);
		assert.equal(sourceReference("/currency", "/externalId", rules), "currency");
		assert.equal(sourceReference("/line_items", "/lines", rules), "line_items");
		assert.equal(sourceReference("/line_items/sku", "/lines/itemCode", rules), "sku");
		assert.equal(sourceReference("/line_items", "/lines/itemCode", rules), "$");
		assert.equal(sourceReference("/currency", "/lines/itemCode", rules), "$$.currency");
		assert.equal(sourceReference("", "/lines/itemCode", rules), "$$");
		const computed = rulesOf([
			"/lines",
			"collection",
			"$filter(line_items, function($l){ $l.quantity > 1 })",
		]);
		assert.equal(sourceReference("/line_items/sku", "/lines/itemCode", computed), "$$.line_items.sku");
	});

	it("probes each rule where the compiled transform evaluates it", async () => {
		const rules = rulesOf(
			["/externalId", "field", '"WEB-" & order_number'],
			["/lines", "collection", "line_items"],
			["/lines/itemCode", "field", "sku"],
			["/lines/qty", "field", "nothing"],
			["/lines/parts", "collection", "parts"],
			["/lines/parts/code", "field", "$uppercase(code)"],
			["/tags", "scalar_collection", "currency"],
		);
		const get = (ptr: string) => rules.get(ptr) as Rule;
		assert.equal(probeExpression(get("/externalId"), rules), '("WEB-" & order_number)');
		assert.equal(probeExpression(get("/lines/itemCode"), rules), '{"i": [(line_items).{"v": (sku)}]}');
		assert.equal(
			probeExpression(get("/lines/parts/code"), rules),
			'{"i": [(line_items).{"i": [(parts).{"v": ($uppercase(code))}]}]}',
		);

		const probe = async (ptr: string) => {
			const value = await run(probeExpression(get(ptr), rules), order);
			return probeValues(value, value !== undefined, collectionChain(ptr, rules).length);
		};
		assert.deepEqual(await probe("/externalId"), [{ at: [], value: "WEB-1042", defined: true }]);
		assert.deepEqual(await probe("/tags"), [{ at: [], value: ["USD"], defined: true }]);
		assert.deepEqual(await probe("/lines"), [{ at: [], value: order.line_items, defined: true }]);
		assert.deepEqual(await probe("/lines/qty"), [
			{ at: [0], value: null, defined: false },
			{ at: [1], value: null, defined: false },
		]);
		// one part (not a list) is still one item, as the compiled collection makes it
		assert.deepEqual(await probe("/lines/parts/code"), [
			{ at: [0, 0], value: "A", defined: true },
			{ at: [0, 1], value: "B", defined: true },
			{ at: [1, 0], value: "C", defined: true },
		]);
		assert.deepEqual(probeValues(undefined, false, 0), [{ at: [], value: null, defined: false }]);

		// all at once, and as the compiled transform has it
		const all = (await run(
			probesExpression([get("/externalId"), get("/lines/itemCode")], rules),
			order,
		)) as Record<string, unknown>;
		assert.deepEqual(
			probeValues(all["/lines/itemCode"], true, 1).map((value) => value.value),
			["MUG", "KTL"],
		);
		const output = (await run(compileRules([...rules.values()]).jsonata, order)) as {
			lines: { itemCode: string }[];
		};
		assert.deepEqual(
			output.lines.map((line) => line.itemCode),
			["MUG", "KTL"],
		);
	});

	it("reads each rule's answers on the sample, from the combined probe or its own", () => {
		const rules = rulesOf(
			["/lines", "collection", "line_items"],
			["/lines/qty", "field", "quantity"],
			["/total", "field", "x"],
		);
		const combined = {
			id: 1,
			ok: true as const,
			value: { "/lines/qty": { i: [{ v: 2 }, {}] } },
			defined: true,
			elapsedMs: 0,
		};
		assert.deepEqual(answerOf(combined, "/lines/qty"), {
			ok: true,
			value: { i: [{ v: 2 }, {}] },
			defined: true,
		});
		assert.deepEqual(answerOf(combined, "/total"), { ok: true, value: null, defined: false });
		assert.equal(
			answerOf({ id: 1, ok: false, error: { code: "T2001", message: "x" }, elapsedMs: 0 }, "/total"),
			undefined,
		);
		assert.equal(answerOf(undefined, "/total"), undefined);
		const qty = rules.get("/lines/qty") as Rule;
		const results = ruleResults(qty, rules, [
			answerOf(combined, "/lines/qty") as never,
			{ ok: false, error: { code: "D1012", message: "slow" } },
		]);
		assert.deepEqual(results.values, [
			{ at: [0], value: 2, defined: true },
			{ at: [1], value: null, defined: false },
		]);
		assert.deepEqual(
			results.byItem.map((values) => values.length),
			[2, 0],
		);
		assert.deepEqual(results.errors, [{ item: 1, error: { code: "D1012", message: "slow" } }]);
	});

	it("checks the values a rule gave against its field", () => {
		assert.deepEqual(valueCompatibility(node("/externalId"), ["a", "b"]), { status: "ok" });
		assert.equal(valueCompatibility(node("/externalId"), [{ a: 1 }]).status, "mismatch");
		assert.equal(valueCompatibility(node("/total"), ["12.5"]).status, "coerced");
		assert.equal(valueCompatibility(node("/tags"), [["a"], ["b", 1]]).status, "coerced");
		assert.equal(valueCompatibility(node("/tags"), [[{}]]).status, "mismatch");
		assert.deepEqual(valueCompatibility(node("/lines"), [1]), { status: "ok" });
		assert.deepEqual(valueCompatibility(node("/total"), []), { status: "ok" });
	});

	it("reads a source item's values, with collection items implied", () => {
		assert.deepEqual(valuesAt(order, "/currency"), ["USD"]);
		assert.deepEqual(valuesAt(order, "/line_items/sku"), ["MUG", "KTL"]);
		assert.deepEqual(valuesAt(order, "/line_items/parts/code"), ["a", "b", "c"]);
		assert.deepEqual(valuesAt(order, "/missing/x"), []);
		assert.deepEqual(sampleItems(null), []);
		assert.deepEqual(sampleItems({ a: 1 }), [{ a: 1 }]);
		assert.deepEqual(sampleItems([1, 2]), [1, 2]);
	});

	it("finds a response's item schema at the Items Pointer", () => {
		const task = { type: "object", properties: { id: { type: "string" } } };
		const response = {
			type: "object",
			allOf: [{ properties: { meta: { type: "object" } } }],
			properties: { data: { type: "array", items: task } },
		};
		assert.deepEqual(itemsSchema(response, "/data"), task);
		assert.deepEqual(itemsSchema(response, "/data/0"), task);
		assert.deepEqual(itemsSchema(response, "/meta"), { type: "object" });
		assert.deepEqual(itemsSchema({ type: "array", items: task }, ""), task);
		assert.deepEqual(itemsSchema(response, ""), response);
		assert.deepEqual(itemsSchema(response, "/nowhere"), {});
		assert.deepEqual(itemsSchema(response, "not a pointer"), {});
	});

	it("finds the required fields no rule fills, as the server does", () => {
		const pointers = (rules: Map<string, Rule>) => requiredUnmapped(target, rules).map((n) => n.pointer);
		assert.deepEqual(pointers(new Map()), ["/externalId", "/lines"]);
		// a collection's required fields count once it is mapped; an object's once a field of it is
		assert.deepEqual(pointers(rulesOf(["/lines", "collection", "line_items"])), [
			"/externalId",
			"/lines/itemCode",
		]);
		assert.deepEqual(pointers(rulesOf(["/customer/email", "field", "email"])), [
			"/externalId",
			"/customer/name",
			"/lines",
		]);
		assert.deepEqual(pointers(rulesOf(["/customer", "field", "customer"])), ["/externalId", "/lines"]);
		const all = rulesOf(
			["/externalId", "field", "x"],
			["/lines", "collection", "line_items"],
			["/lines/itemCode", "field", "sku"],
		);
		assert.deepEqual(pointers(all), []);
		assert.deepEqual(mappingCounts(target, all), { mapped: 3, total: 10 });
		const rootList = fromOpenApiSchema({
			type: "array",
			items: { type: "object", properties: { a: { type: "string" } } },
		});
		assert.deepEqual(
			targetFields(rootList).map((n) => n.pointer),
			["", "/a"],
		);
	});

	it("lists what the rules show before anything runs", () => {
		const rules = rulesOf(
			["/externalId", "field", "order_number +"],
			["/lines/qty", "field", "quantity"],
			["/gone", "field", "x"],
			["/lines/qty/deeper", "field", "y"],
		);
		const found = ruleDiagnostics(target, rules, compileRules([...rules.values()]));
		const codes = found.map((d) => `${d.rule} ${d.severity} ${d.code}`);
		assert.deepEqual(codes, [
			"/lines/qty/deeper error compile.nested",
			"/externalId error jsonata.S0207",
			"/gone warning rule-unknown",
			"/lines/qty/deeper warning rule-unknown",
			// a rule under /lines counts as mapping it, as on the server
		]);
		assert.ok(found.every((d) => d.origin === "client" && d.path === d.rule));
		assert.equal(syntaxError("a.b"), undefined);
		assert.equal(syntaxError("(")?.code, "S0203");
	});

	it("lists what a rule's results show", () => {
		const rule: Rule = { ptr: "/total", kind: "field", expr: "price" };
		const found = resultDiagnostics(node("/total"), rule, {
			values: [
				{ at: [], value: "12", defined: true },
				{ at: [], value: null, defined: false },
			],
			byItem: [],
			errors: [{ item: 2, error: { code: "T2001", message: "Not a number" } }],
		});
		assert.deepEqual(
			found.map((d) => [d.code, d.severity, d.item]),
			[
				["eval.T2001", "error", 2],
				["type-coerced", "warning", undefined],
			],
		);
		assert.deepEqual(resultDiagnostics(undefined, rule, { values: [], byItem: [], errors: [] }), []);
	});

	it("drops a finding the browser and the server both made", () => {
		const base: Diagnostic = {
			rule: "/a",
			path: "/a",
			severity: "error",
			code: "required-unmapped",
			message: "x",
			origin: "client",
		};
		const server = { ...base, message: "y", origin: "server" as const };
		const other = { ...base, item: 1 };
		assert.deepEqual(withoutRepeats([base, server, other]), [
			{ ...base, items: [] },
			{ ...other, items: [1] },
		]);
	});

	it("lists a finding the sample's items share once, with its items", () => {
		const on = (item: number, message = "must have required property first_name"): Diagnostic => ({
			rule: "",
			path: "",
			severity: "error",
			code: "schema.required",
			message,
			origin: "client",
			item,
		});
		const listed = withoutRepeats([on(0), on(1), on(2), on(4), on(3, "other")]);
		assert.deepEqual(
			listed.map((finding) => [finding.message, finding.items]),
			[
				["must have required property first_name", [0, 1, 2, 4]],
				["other", [3]],
			],
		);
		assert.equal(itemRanges([4, 0, 1, 2, 2]), "1–3, 5");
		assert.equal(itemRanges([7]), "8");
		assert.equal(itemRanges([]), "");
	});
});

describe("schemaValidator", () => {
	it("checks an object against the target's schema, whatever its dialect", () => {
		const validate = schemaValidator({
			$schema: "https://spec.openapis.org/oas/3.1/dialect/base",
			type: "object",
			required: ["id"],
			properties: { id: { type: "string" }, due: { type: "string", format: "date" } },
			"x-frappe": { doctype: "ToDo" },
		});
		assert.ok(validate);
		assert.equal(validate({ id: "a", due: "not a date" }), true);
		assert.equal(validate({ due: "2026-01-01" }), false);
		assert.equal(validate.errors?.[0]?.keyword, "required");
		assert.equal(schemaValidator(null), undefined);
		assert.equal(schemaValidator({ $ref: "#/nowhere" }), undefined);
	});
});

describe("insertSnippet", () => {
	it("puts the caret in the snippet's hole, or wraps the selection", () => {
		assert.deepEqual(insertSnippet("price", 5, 5, { before: " & ", after: "" }), {
			expression: "price & ",
			caret: 8,
		});
		assert.deepEqual(insertSnippet("", 0, 0, { before: "$substring(", after: ", 0, 10)" }), {
			expression: "$substring(, 0, 10)",
			caret: 11,
		});
		assert.deepEqual(insertSnippet("a + price", 4, 9, { before: "$number(", after: ")" }), {
			expression: "a + $number(price)",
			caret: 17,
		});
		// a selection made backwards, or past the end
		assert.deepEqual(insertSnippet("ab", 9, 1, { before: "[", after: "]" }), {
			expression: "a[b]",
			caret: 3,
		});
	});
});

describe("rows", () => {
	it("shows a filtered tree's matches with the groups above them", () => {
		assert.deepEqual([...withAncestors(["/a/b/c", "/a/d", "/e"])].sort(), [
			"",
			"/a",
			"/a/b",
			"/a/b/c",
			"/a/d",
			"/e",
		]);
	});

	it("finds the row a field shows on: its own, or its closed group's", () => {
		const fields = new Set(["/lines", "/lines/qty", "/lines/parts", "/lines/parts/code", "/total"]);
		assert.equal(
			shownRow("/lines/parts/code", fields, new Set(["/lines", "/lines/parts"])),
			"/lines/parts/code",
		);
		assert.equal(shownRow("/lines/parts/code", fields, new Set(["/lines"])), "/lines/parts");
		assert.equal(shownRow("/lines/parts/code", fields, new Set()), "/lines");
		// a read deeper than the tree goes (into a map, a wildcard) shows on the field holding it
		assert.equal(shownRow("/total/x/y", fields, new Set()), "/total");
		assert.equal(shownRow("/nowhere", fields, new Set()), undefined);
	});
});

describe("lines and checks", () => {
	const rules = rulesOf(
		["/externalId", "field", '"WEB-" & order_number'],
		["/lines", "collection", "line_items"],
		["/lines/itemCode", "field", "sku"],
		["/lines/qty", "field", "quantity * $$.currency.rate"],
		["/total", "field", "$sum(line_items.*)"],
		["/tags", "scalar_collection", "$distinct(line_items.sku)"],
		["/customer/name", "field", "customer.first_name"],
	);

	it("reads each rule's source fields where it runs", () => {
		const reads = ruleReads(rules);
		assert.deepEqual(reads.get("/lines/itemCode"), ["/line_items/sku"]);
		assert.deepEqual(reads.get("/lines/qty"), ["/line_items/quantity", "/currency/rate"]);
		// a wildcard read stops at the field above it
		assert.deepEqual(reads.get("/total"), ["/line_items"]);
		assert.deepEqual(reads.get("/tags"), ["/line_items/sku"]);
		const computed = rulesOf(
			["/lines", "collection", "line_items[quantity > 1]"],
			["/lines/qty", "field", "quantity"],
		);
		assert.equal(ruleReads(computed).has("/lines/qty"), false);
	});

	it("draws a line from each read field's row to the filled field's row, once", () => {
		// the source's line_items group is closed; the target's customer isn't shown
		const sourceRow = (pointer: string) => (pointer.startsWith("/line_items/") ? "/line_items" : pointer);
		const targetRow = (pointer: string) => (pointer.startsWith("/customer") ? undefined : pointer);
		const links = ruleLinks(rules, ruleReads(rules), sourceRow, targetRow);
		assert.deepEqual(
			links.map((link) => `${link.source}>${link.target} ${link.kind} ${link.rules.join(",")}`),
			[
				"/order_number>/externalId formula /externalId",
				"/line_items>/lines collection /lines",
				"/line_items>/lines/itemCode path /lines/itemCode",
				"/line_items>/lines/qty formula /lines/qty",
				"/currency/rate>/lines/qty formula /lines/qty",
				"/line_items>/total formula /total",
				"/line_items>/tags formula /tags",
			],
		);
		const merged = ruleLinks(
			rules,
			ruleReads(rules),
			() => "/all",
			() => "/one",
		);
		assert.equal(merged.length, 1);
		assert.equal(merged[0]?.rules.length, 7);
	});

	it("checks what each item maps to against the target's schema", () => {
		const validate = schemaValidator({
			type: "object",
			required: ["externalId"],
			properties: { externalId: { type: "string" } },
		});
		const placed: Diagnostic[] = [
			{
				rule: "/total",
				path: "/total",
				severity: "error",
				code: "eval.T2001",
				message: "x",
				origin: "client",
				item: 1,
			},
		];
		const found = outputDiagnostics(
			[
				{ id: 1, ok: true, value: { total: 1 }, defined: true, elapsedMs: 0 },
				{ id: 2, ok: false, error: { code: "T2001", message: "x" }, elapsedMs: 0 },
				{ id: 3, ok: false, error: { code: "D1012", message: "slow" }, elapsedMs: 0 },
				{ id: 4, ok: true, value: { externalId: "a" }, defined: true, elapsedMs: 0 },
			],
			validate,
			{ target, rules, severity: "warning", placed },
		);
		assert.deepEqual(
			found.map((d) => [d.rule, d.code, d.severity, d.item]),
			[
				["/externalId", "schema.required", "warning", 0],
				["", "eval.D1012", "error", 2],
			],
		);
		assert.deepEqual(
			outputDiagnostics([{ id: 1, ok: true, value: {}, defined: true, elapsedMs: 0 }], undefined, {
				target,
				rules,
				severity: "error",
				placed: [],
			}),
			[],
		);
	});
});
