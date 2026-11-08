// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";
import jsonata from "jsonata";
import { compileRules } from "../../espresso_sync/public/js/editor/compile.ts";

// shared with the server's compiler (espresso_sync/tests/test_compile.py): the same rules
// must compile to the same text, byte for byte
const GOLDEN = new URL("../../espresso_sync/tests/fixtures/compile/", import.meta.url);

interface GoldenCase {
	rules: unknown[];
	errors: [string, string][];
	input: unknown;
	output: unknown;
}

const cases = readdirSync(GOLDEN)
	.filter((file) => file.endsWith(".json"))
	.map((file) => file.slice(0, -".json".length));

describe("compileRules", () => {
	it("has golden cases", () => {
		assert.ok(cases.length >= 5);
	});

	for (const name of cases) {
		it(`compiles ${name} as the golden file has it`, async () => {
			const golden = JSON.parse(readFileSync(new URL(`${name}.json`, GOLDEN), "utf8")) as GoldenCase;
			const expected = readFileSync(new URL(`${name}.jsonata`, GOLDEN), "utf8").replace(/\n$/, "");
			const compiled = compileRules(golden.rules);
			assert.equal(compiled.jsonata, expected);
			assert.deepEqual(
				compiled.errors.map((error) => [error.rule, error.code]),
				golden.errors,
			);
			const result: unknown = await jsonata(compiled.jsonata).evaluate(golden.input);
			assert.deepEqual(JSON.parse(JSON.stringify(result)), golden.output);
		});
	}

	it("refuses a pointer with a lone surrogate, as compile.py does", () => {
		// a golden file cannot hold one (check-json refuses it): test_compile.py has this case too
		const compiled = compileRules([{ ptr: "/\ud800", kind: "field", expr: "x" }]);
		assert.equal(compiled.jsonata, "{}");
		assert.deepEqual(
			compiled.errors.map((error) => [error.rule, error.code]),
			[["", "compile.pointer"]],
		);
	});

	it("compiles no rules to an empty object", () => {
		assert.deepEqual(compileRules([]), { jsonata: "{}", errors: [] });
	});
});
