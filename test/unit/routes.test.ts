// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deskFormUrl, href, isAnchorHash, parseRoute } from "../../espresso_sync/public/js/editor/routes.ts";
import {
	escapeSegment,
	fromPointer,
	parentPointer,
	toPointer,
} from "../../espresso_sync/public/js/editor/pointer.ts";

describe("routes", () => {
	it("reads the hash routes, tolerating missing and extra slashes", () => {
		for (const hash of ["", "#", "#/", "#//"]) assert.deepEqual(parseRoute(hash), { page: "home" });
		assert.deepEqual(parseRoute("#/specs/Shop%20API"), { page: "spec", name: "Shop API" });
		assert.deepEqual(parseRoute("#/transforms/Orders%2FIn/"), { page: "transform", name: "Orders/In" });
		assert.deepEqual(parseRoute("#specs/x"), { page: "spec", name: "x" });
	});

	it("sends anything else to not-found", () => {
		for (const hash of ["#/specs", "#/specs/", "#/specs/a/b", "#/other/a", "#/transforms/%E0%A4%A"]) {
			assert.deepEqual(parseRoute(hash), { page: "not-found", hash });
		}
	});

	it("tells in-page anchors from routes", () => {
		assert.equal(isAnchorHash("#main-content"), true);
		for (const hash of ["", "#", "#/", "#/specs/x", "#specs/x", "#/nope"])
			assert.equal(isAnchorHash(hash), false, hash);
	});

	it("writes hashes that read back as the same route", () => {
		for (const route of [
			{ page: "home" },
			{ page: "spec", name: "Shop API / v2" },
			{ page: "transform", name: "Orders → ERP" },
		] as const) {
			assert.deepEqual(parseRoute(href(route)), route);
		}
		assert.equal(href({ page: "not-found", hash: "#/nope" }), "#/nope");
	});

	it("links to a document's desk form, or a new one", () => {
		assert.equal(
			deskFormUrl("Espresso Sync Connection", "Shop / EU"),
			"/desk/espresso-sync-connection/Shop%20%2F%20EU",
		);
		assert.equal(deskFormUrl("Espresso Sync Connection"), "/desk/espresso-sync-connection/new");
	});
});

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
