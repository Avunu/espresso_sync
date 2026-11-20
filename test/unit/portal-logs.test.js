// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ERROR_HINTS, filtersFromQuery, frappeFilters, lastError, prettyJson, queryFromFilters, } from "../../espresso_sync/public/js/portal/logs.ts";
const NOW = "2026-01-15 12:00:00.000000";
describe("portal logs", () => {
    it("reads the last error of an entry", () => {
        const diagnostics = [
            { severity: "error", code: "required", message: "subject is needed", path: "/subject" },
            {
                severity: "error",
                code: "invalid-payload",
                message: "The mapped object does not pass the schema",
                origin: "object",
            },
            { severity: "warning", code: "no-external-id", message: "External ID gives nothing" },
        ];
        const expected = { code: "invalid-payload", message: "The mapped object does not pass the schema" };
        assert.deepEqual(lastError(diagnostics), expected);
        assert.deepEqual(lastError(JSON.stringify(diagnostics)), expected);
        assert.deepEqual(lastError([{ severity: "error", code: "http-status" }]), {
            code: "http-status",
            message: "",
        });
    });
    it("finds no error in empty or malformed diagnostics", () => {
        const nothing = [
            null,
            undefined,
            "",
            "[]",
            [],
            "{not json",
            '{"code": "x"}',
            '"text"',
            42,
            { severity: "error", code: "x", message: "an object, not a list" },
            [null, "text", 7, { severity: "warning", code: "x", message: "m" }],
            [
                { severity: "error", message: "no code" },
                { severity: "error", code: "", message: "m" },
                { severity: "error", code: 5 },
            ],
        ];
        for (const diagnostics of nothing)
            assert.equal(lastError(diagnostics), null, JSON.stringify(diagnostics));
    });
    it("round-trips the filters through a query", () => {
        const filters = {
            connection: "Example Shop",
            status: "Failure",
            direction: "Import",
            doctype: "Task",
            transform: "Example Shop Tasks",
            doc: "TASK-0001",
            docs: "1",
            since: "attempt",
            code: "http-status",
        };
        assert.deepEqual(queryFromFilters(filters), filters);
        assert.deepEqual(filtersFromQuery(queryFromFilters(filters)), filters);
        // only the filters, and only those with a value
        assert.deepEqual(filtersFromQuery({ status: "Success", page: "3", doc: "", other: "x" }), {
            status: "Success",
        });
        assert.deepEqual(queryFromFilters({ status: "Success", doc: "" }), {
            status: "Success",
        });
        assert.deepEqual(filtersFromQuery({}), {});
        assert.deepEqual(queryFromFilters({}), {});
    });
    it("turns the filters into list filters", () => {
        assert.deepEqual(frappeFilters({}, NOW), []);
        assert.deepEqual(frappeFilters({
            connection: "Shop",
            status: "Failure",
            direction: "Export",
            doctype: "Task",
            transform: "T",
            doc: "TASK",
            code: "conflict",
        }, NOW), [
            ["sync_connection", "=", "Shop"],
            ["sync_status", "=", "Failure"],
            ["sync_direction", "=", "Export"],
            ["sync_doctype", "=", "Task"],
            ["transform", "=", "T"],
            ["sync_doc", "like", "%TASK%"],
        ]);
        // the entries of documents alone: a request's names none
        assert.deepEqual(frappeFilters({ status: "Success", docs: "1" }, NOW), [
            ["sync_status", "=", "Success"],
            ["sync_doc", "is", "set"],
        ]);
    });
    it("turns each period into a cutoff", () => {
        assert.deepEqual(frappeFilters({ since: "1h" }, NOW), [["creation", ">=", "2026-01-15 11:00:00"]]);
        assert.deepEqual(frappeFilters({ since: "24h" }, NOW), [["creation", ">=", "2026-01-14 12:00:00"]]);
        assert.deepEqual(frappeFilters({ since: "7d" }, NOW), [["creation", ">=", "2026-01-08 12:00:00"]]);
        assert.deepEqual(frappeFilters({ since: "24h" }, "2026-03-01 00:30:00"), [
            ["creation", ">=", "2026-02-28 00:30:00"],
        ]);
        assert.deepEqual(frappeFilters({ since: "24h" }, "not a time"), []);
    });
    it("filters since the last attempt when there is one", () => {
        const attempt = "2026-01-15 11:30:00.123456";
        assert.deepEqual(frappeFilters({ since: "attempt" }, NOW, attempt), [["creation", ">=", attempt]]);
        assert.deepEqual(frappeFilters({ since: "attempt" }, NOW, null), []);
        assert.deepEqual(frappeFilters({ since: "attempt" }, NOW), []);
        // the attempt is only for `attempt`
        assert.deepEqual(frappeFilters({ since: "1h" }, NOW, attempt), [
            ["creation", ">=", "2026-01-15 11:00:00"],
        ]);
    });
    it("filters one day for a date", () => {
        assert.deepEqual(frappeFilters({ since: "2026-01-14" }, NOW), [
            ["creation", ">=", "2026-01-14 00:00:00"],
            ["creation", "<", "2026-01-15 00:00:00"],
        ]);
        assert.deepEqual(frappeFilters({ since: "2025-12-31" }, NOW)[1], [
            "creation",
            "<",
            "2026-01-01 00:00:00",
        ]);
        for (const since of ["2026-02-31", "yesterday", "2026-01-14 10:00:00", "30d"]) {
            assert.deepEqual(frappeFilters({ since, status: "Failure" }, NOW), [["sync_status", "=", "Failure"]], since);
        }
    });
    it("lays JSON out", () => {
        assert.equal(prettyJson({ a: [1, 2] }), '{\n  "a": [\n    1,\n    2\n  ]\n}');
        assert.equal(prettyJson('{"a":1}'), '{\n  "a": 1\n}');
        assert.equal(prettyJson("<html>not json</html>"), "<html>not json</html>");
        assert.equal(prettyJson(null), "");
        assert.equal(prettyJson(undefined), "");
        assert.equal(prettyJson(""), "");
        assert.equal(prettyJson(0), "0");
        assert.equal(prettyJson(false), "false");
        assert.equal(prettyJson(() => 1), "");
    });
    it("has a hint for each code the sync fails with", () => {
        assert.deepEqual(Object.keys(ERROR_HINTS).sort(), [
            "conflict",
            "http-status",
            "invalid-json",
            "invalid-payload",
            "max-pages",
            "next-request",
            "no-external-id",
            "transform-not-active",
        ]);
        for (const hint of Object.values(ERROR_HINTS))
            assert.match(hint, /^[A-Z].*\.$/);
    });
});
