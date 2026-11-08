// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	escapeSegment,
	fromPointer,
	parentPointer,
	toPointer,
} from "../../espresso_sync/public/js/editor/pointer.ts";

describe("pointer", () => {
	it("escapes and reads back segments", () => {
		assert.equal(escapeSegment("a/b~c"), "a~1b~0c");
		assert.equal(toPointer(["a/b", "~", ""]), "/a~1b/~0/");
		assert.deepEqual(fromPointer("/a~1b/~0/"), ["a/b", "~", ""]);
		assert.deepEqual(fromPointer(""), []);
		assert.throws(() => fromPointer("a/b"), SyntaxError);
	});

	it("climbs to the parent", () => {
		assert.equal(parentPointer("/a/b"), "/a");
		assert.equal(parentPointer("/a"), "");
		assert.equal(parentPointer(""), "");
	});
});
