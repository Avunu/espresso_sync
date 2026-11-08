// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import jsonata from "jsonata";
import { readsOf, readsOfAst, type ReadsResult } from "../../espresso_sync/public/js/editor/reads.ts";

function pointers(result: ReadsResult): string[] {
	assert.ok(result.ok, "the expression parses");
	return result.reads.map((read) => read.pointer);
}

function readsOfText(expression: string, context?: string[]): string[] {
	return pointers(readsOf(expression, context ? { context } : {}));
}

describe("reads", () => {
	it("lists each field a path reads, once", () => {
		assert.deepEqual(readsOfText('customer.first_name & " " & customer.last_name & customer.first_name'), [
			"/customer/first_name",
			"/customer/last_name",
		]);
	});

	it("reads through function arguments and object constructors, items implied", () => {
		assert.deepEqual(readsOfText("$sum(shipping_lines.$number(price))"), ["/shipping_lines/price"]);
		assert.deepEqual(
			readsOfText(
				'line_items.{"itemCode": sku, "amount": $number(price) * quantity - $number(total_discount)}',
			),
			["/line_items/sku", "/line_items/price", "/line_items/quantity", "/line_items/total_discount"],
		);
		assert.deepEqual(readsOfText("line_items[0].sku"), ["/line_items/sku"]);
	});

	it("reads filters relative to the items they filter", () => {
		assert.deepEqual(readsOfText("line_items[quantity > 1].sku"), [
			"/line_items/quantity",
			"/line_items/sku",
		]);
		assert.deepEqual(readsOfText("a[$.b = $$.c]"), ["/a/b", "/c", "/a"]);
	});

	it("follows variables bound to a path, and not the binding itself", () => {
		assert.deepEqual(readsOfText("($c := customer; $c.email)"), ["/customer/email"]);
		assert.deepEqual(readsOfText("($c := customer; $c)"), ["/customer"]);
		assert.deepEqual(readsOfText("($n := $count(a); $n)"), ["/a"]);
	});

	it("reads conditions, operators, sorts, groups and blocks", () => {
		assert.deepEqual(readsOfText('financial_status = "paid" ? "Approved" : total'), [
			"/financial_status",
			"/total",
		]);
		assert.deepEqual(readsOfText("a^(>c).d"), ["/a/c", "/a/d"]);
		assert.deepEqual(readsOfText("a{b: c}"), ["/a/b", "/a/c"]);
		assert.deepEqual(readsOfText("a.(b).c"), ["/a/b/c"]);
		assert.deepEqual(readsOfText("a.[b, c]"), ["/a/b", "/a/c"]);
		assert.deepEqual(readsOfText("-a and not(b) or c in [1, d]"), ["/a", "/b", "/c", "/d"]);
		assert.deepEqual(readsOfText("x.$string()"), []);
	});

	it("resolves the parent operator and focus variables", () => {
		assert.deepEqual(readsOfText("a.b.c.%.%.d"), ["/a/d"]);
		assert.deepEqual(readsOfText("orders@$o.customers[id = $o.customer_id].name"), [
			"/customers/id",
			"/orders/customer_id",
			"/customers/name",
		]);
		assert.deepEqual(readsOfText("items#$i.sku"), ["/items/sku"]);
	});

	it("binds the item parameter of higher-order functions", () => {
		assert.deepEqual(readsOfText("$map(items, function($v){ $v.sku })"), ["/items/sku"]);
		assert.deepEqual(readsOfText("items ~> $filter(function($v){ $v.qty > 0 })"), ["/items/qty"]);
		assert.deepEqual(readsOfText("$reduce(a, function($acc, $v){ $acc + $v.n }, 0)"), ["/a/n"]);
		assert.deepEqual(readsOfText("$sort(a, function($l, $r){ $l.x > $r.x })"), ["/a/x"]);
		const each = readsOf("$each(prices, function($v, $k){ $v.amount })");
		assert.ok(each.ok);
		assert.deepEqual(each.reads, [
			{ pointer: "/prices/*/amount", segments: ["prices", "*", "amount"], wildcard: true },
		]);
		assert.deepEqual(readsOfText("x ~> $string()"), ["/x"]);
	});

	it("marks wildcard and descendant reads", () => {
		const result = readsOf("*.x & **.id");
		assert.ok(result.ok);
		assert.deepEqual(
			result.reads.map((read) => [read.pointer, read.wildcard]),
			[
				["/*/x", true],
				["/**/id", true],
			],
		);
	});

	it("flags what only evaluation can resolve", () => {
		const lookup = readsOf('$lookup(customer, "na" & "me")');
		assert.ok(lookup.ok);
		assert.deepEqual(lookup.reads, []);
		assert.deepEqual(
			lookup.dynamic.map((d) => [d.reason, d.base]),
			[["lookup", "/customer"]],
		);

		const evalRead = readsOf('$eval("a")');
		assert.ok(evalRead.ok);
		assert.deepEqual(
			evalRead.dynamic.map((d) => d.reason),
			["eval"],
		);

		const lambda = readsOf("($f := function($x){ $x.y }; $f(a))");
		assert.ok(lambda.ok);
		assert.deepEqual(
			lambda.reads.map((r) => r.pointer),
			["/a"],
		);
		assert.deepEqual(
			lambda.dynamic.map((d) => d.reason),
			["lambda"],
		);

		const transform = readsOf('$ ~> |a|{"b": c}|');
		assert.ok(transform.ok);
		assert.deepEqual(
			transform.dynamic.map((d) => d.reason),
			["transform"],
		);
		assert.equal(typeof transform.dynamic[0]?.position, "number");
	});

	it("does not treat a function the expression defines as a builtin", () => {
		const result = readsOf("($lookup := function($o){ $o.name }; $lookup(customer))");
		assert.ok(result.ok);
		assert.deepEqual(
			result.reads.map((r) => r.pointer),
			["/customer"],
		);
		assert.deepEqual(
			result.dynamic.map((d) => d.reason),
			["lambda"],
		);
	});

	it("reads relative to a collection's items, with $$ still the root", () => {
		assert.deepEqual(readsOfText("sku & $$.currency & $.title", ["line_items"]), [
			"/line_items/sku",
			"/currency",
			"/line_items/title",
		]);
		assert.deepEqual(readsOfText("$", ["tags"]), ["/tags"]);
	});

	it("escapes keys that need it", () => {
		assert.deepEqual(readsOfText("`we/ird~`.x"), ["/we~1ird~0/x"]);
	});

	it("reports a parse error instead of throwing", () => {
		const result = readsOf("a.");
		assert.equal(result.ok, false);
		assert.ok(!result.ok);
		assert.equal(result.error.code, "S0207");
		assert.equal(result.error.position, 2);
		assert.equal(result.error.token, "(end)");
	});

	it("accepts an AST jsonata already parsed", () => {
		const reads = readsOfAst(jsonata("a.b").ast(), { context: ["x"] });
		assert.deepEqual(
			reads.reads.map((r) => r.pointer),
			["/x/a/b"],
		);
		assert.deepEqual(reads.dynamic, []);
	});

	it("reads nothing from literals and regular expressions", () => {
		assert.deepEqual(readsOfText('"x"'), []);
		assert.deepEqual(readsOfText("42"), []);
		assert.deepEqual(readsOfText("$match(name, /ab+/)"), ["/name"]);
	});
});
