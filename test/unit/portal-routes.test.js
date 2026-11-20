// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { CONNECTION_TABS, SECTIONS, hrefFor, parseHash, } from "../../espresso_sync/public/js/portal/routes.ts";
function route(section, rest = {}) {
    return { section, name: undefined, tab: undefined, query: {}, ...rest };
}
describe("portal routes", () => {
    it("lists the sections in header order", () => {
        assert.deepEqual(SECTIONS, ["overview", "connections", "logs", "transforms", "specs"]);
        assert.deepEqual(CONNECTION_TABS, ["shots", "links", "settings"]);
    });
    it("lands on the Overview for nothing, the root and anything unknown", () => {
        for (const hash of ["", "#", "#/", "#/overview", "#/nowhere", "#/nowhere/Shop", "connections%2FShop"]) {
            assert.deepEqual(parseHash(hash), route("overview"), hash);
        }
        // a mangled escape in the section
        assert.deepEqual(parseHash("#/%E0%A4%A/Shop"), route("overview"));
        assert.deepEqual(parseHash("#/spec%s"), route("overview"));
        // the query survives the fallback
        assert.deepEqual(parseHash("#/nowhere?a=1"), route("overview", { query: { a: "1" } }));
    });
    it("reads the Connections list and its filters", () => {
        assert.deepEqual(parseHash("#/connections"), route("connections"));
        assert.deepEqual(parseHash("#/connections?health=attention"), route("connections", { query: { health: "attention" } }));
        assert.deepEqual(parseHash("#/connections?health=paused"), route("connections", { query: { health: "paused" } }));
        assert.deepEqual(parseHash("#/connections?new=1"), route("connections", { query: { new: "1" } }));
    });
    it("reads a Connection and its tabs", () => {
        assert.deepEqual(parseHash("#/connections/Example%20Shop"), route("connections", { name: "Example Shop" }));
        assert.deepEqual(parseHash("#/connections/Example%20Shop/shots"), route("connections", { name: "Example Shop", tab: "shots" }));
        assert.deepEqual(parseHash("#/connections/Shop/links?doctype=Task&q=a%20b&off=1&page=2"), route("connections", {
            name: "Shop",
            tab: "links",
            query: { doctype: "Task", q: "a b", off: "1", page: "2" },
        }));
        assert.deepEqual(parseHash("#/connections/Shop/settings"), route("connections", { name: "Shop", tab: "settings" }));
    });
    it("keeps a tab-like segment in the name when it is not a tab", () => {
        // an unknown second segment, or a third one, is a name written with a bare slash
        assert.deepEqual(parseHash("#/connections/Shop/activity"), route("connections", { name: "Shop/activity" }));
        assert.deepEqual(parseHash("#/connections/A/B/shots"), route("connections", { name: "A/B/shots" }));
        // an escaped slash is one segment, so the tab still reads
        assert.deepEqual(parseHash("#/connections/A%2FB/shots"), route("connections", { name: "A/B", tab: "shots" }));
        // only a Connection has tabs
        assert.deepEqual(parseHash("#/specs/Shop/shots"), route("specs", { name: "Shop/shots" }));
        assert.deepEqual(parseHash("#/connections//shots"), route("connections", { name: "/shots" }));
    });
    it("reads the Sync log, its filters and one entry", () => {
        assert.deepEqual(parseHash("#/logs"), route("logs"));
        assert.deepEqual(parseHash("#/logs?connection=Shop&status=Failure&direction=Import&doctype=Task&transform=T&doc=TASK-1&since=24h&code=http-status&page=3"), route("logs", {
            query: {
                connection: "Shop",
                status: "Failure",
                direction: "Import",
                doctype: "Task",
                transform: "T",
                doc: "TASK-1",
                since: "24h",
                code: "http-status",
                page: "3",
            },
        }));
        assert.deepEqual(parseHash("#/logs/abc123"), route("logs", { name: "abc123" }));
    });
    it("reads the existing sections as before", () => {
        assert.deepEqual(parseHash("#/transforms"), route("transforms"));
        assert.deepEqual(parseHash("#/transforms/Shop%20Tasks"), route("transforms", { name: "Shop Tasks" }));
        assert.deepEqual(parseHash("#/specs"), route("specs"));
        assert.deepEqual(parseHash("#/specs/Shop%20API"), route("specs", { name: "Shop API" }));
        assert.deepEqual(parseHash("#specs/Shop"), route("specs", { name: "Shop" }));
        // a legacy name containing a slash, bare or escaped
        assert.deepEqual(parseHash("#/specs/Shop%20-%20v1/v2"), route("specs", { name: "Shop - v1/v2" }));
        assert.deepEqual(parseHash("#/specs/Shop%2Fv2"), route("specs", { name: "Shop/v2" }));
        assert.deepEqual(parseHash("#/specs/"), route("specs"));
    });
    it("drops a name or a tabbed name with a mangled escape", () => {
        assert.deepEqual(parseHash("#/specs/100%"), route("specs"));
        assert.deepEqual(parseHash("#/connections/100%/shots"), route("connections", { tab: "shots" }));
    });
    it("reads a query leniently", () => {
        assert.deepEqual(parseHash("#/logs?").query, {});
        assert.deepEqual(parseHash("#/logs?a=1&&b&=c&d=&e=%&%=f&g=x+y&a=2&h=1=2").query, {
            a: "2",
            g: "x y",
            h: "1=2",
        });
        // a `?` inside the query is part of a value
        assert.deepEqual(parseHash("#/logs?doc=what?").query, { doc: "what?" });
        assert.equal(Object.getPrototypeOf(parseHash("#/logs?__proto__=x").query), Object.prototype);
    });
    it("writes the two-argument links as before", () => {
        assert.equal(hrefFor("overview"), "#/overview");
        assert.equal(hrefFor("specs"), "#/specs");
        assert.equal(hrefFor("specs", ""), "#/specs");
        assert.equal(hrefFor("specs", "Shop API"), "#/specs/Shop%20API");
        assert.equal(hrefFor("transforms", "A/B"), "#/transforms/A%2FB");
    });
    it("writes tabs and queries", () => {
        assert.equal(hrefFor("connections", "Shop", { tab: "shots" }), "#/connections/Shop/shots");
        assert.equal(hrefFor("connections", "Shop", {}), "#/connections/Shop");
        // a tab needs a Connection to belong to
        assert.equal(hrefFor("connections", undefined, { tab: "shots" }), "#/connections");
        assert.equal(hrefFor("specs", "Shop", { tab: "shots" }), "#/specs/Shop");
        assert.equal(hrefFor("logs", undefined, { query: { status: "Failure", since: "24h", doc: undefined, code: "" } }), "#/logs?status=Failure&since=24h");
        assert.equal(hrefFor("logs", undefined, { query: {} }), "#/logs");
        assert.equal(hrefFor("connections", "A B", { tab: "links", query: { q: "x&y=z ?", page: "2" } }), "#/connections/A%20B/links?q=x%26y%3Dz%20%3F&page=2");
    });
    it("round-trips a route through its link", () => {
        const cases = [
            route("overview"),
            route("connections", { query: { health: "attention" } }),
            route("connections", {
                name: "Shop / EU",
                tab: "links",
                query: { q: "a+b c", doctype: "Sales Order" },
            }),
            route("connections", { name: "shots" }),
            route("logs", { query: { connection: "Example Shop", since: "2026-01-15", status: "Failure" } }),
            route("logs", { name: "0kq1f2" }),
            route("transforms", { name: "Example Shop Tasks" }),
            route("specs", { name: "Example Shop - Shop" }),
        ];
        for (const expected of cases) {
            const href = hrefFor(expected.section, expected.name, {
                tab: expected.tab,
                query: { ...expected.query },
            });
            assert.deepEqual(parseHash(href), expected, href);
        }
    });
});
