// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { connectionErrors, connectionPayload, draftOf, hostOf, optionsFor, shotErrors, } from "../../espresso_sync/public/js/portal/connectionForm.ts";
const DETAIL = {
    name: "Example Shop",
    modified: "2026-01-15 09:00:00.000000",
    enabled: 1,
    server_url: "https://shop.example.com/api",
    allowed_host: "shop.example.com",
    auth_type: "Basic",
    api_key: "robot",
    sync_frequency: "Cron",
    cron_rule: "0 6 * * *",
    api_rate_limit: 60,
    last_pull: null,
    last_sync_attempt: null,
    has_secret: true,
    shots: [
        {
            name: "row1",
            idx: 1,
            dt: "Task",
            do_import: 1,
            import_transform: "Example Shop Tasks",
            last_import: null,
            do_export: 0,
            export_transform: null,
            update_transform: null,
            follow_up_transform: null,
            last_export: null,
        },
    ],
    setup: { specs: 1, transforms: 1, active_transforms: 1 },
    auth_hints: null,
};
const DRAFT = {
    server_url: "https://shop.example.com/api",
    allowed_host: "shop.example.com",
    auth_type: "Basic",
    api_key: "robot",
    sync_frequency: "Cron",
    cron_rule: "0 6 * * *",
    api_rate_limit: "60",
};
const SHOT = {
    dt: "Task",
    do_import: 1,
    import_transform: "Example Shop Tasks",
    do_export: 1,
    export_transform: "Example Shop Create Task",
    update_transform: "",
    follow_up_transform: "",
};
describe("portal connection form", () => {
    it("starts the draft from the saved Connection", () => {
        assert.deepEqual(draftOf(DETAIL), DRAFT);
        assert.deepEqual(draftOf({
            ...DETAIL,
            server_url: null,
            allowed_host: null,
            auth_type: null,
            api_key: null,
            sync_frequency: null,
            cron_rule: null,
            api_rate_limit: 0,
        }), {
            server_url: "",
            allowed_host: "",
            auth_type: "Header-based",
            api_key: "",
            sync_frequency: "Manual",
            cron_rule: "",
            api_rate_limit: "",
        });
        assert.equal(draftOf({ ...DETAIL, api_rate_limit: null }).api_rate_limit, "");
    });
    it("reads the host of a URL", () => {
        assert.equal(hostOf("https://shop.example.com/api/v1?x=1"), "shop.example.com");
        assert.equal(hostOf(" https://Shop.Example.com "), "shop.example.com");
        assert.equal(hostOf("http://localhost:8080/"), "localhost:8080");
        assert.equal(hostOf("https://shop.example.com:443/"), "shop.example.com");
        assert.equal(hostOf("https://user:pass@shop.example.com/"), "shop.example.com");
        assert.equal(hostOf("http://[::1]:8000/"), "[::1]:8000");
        for (const text of ["", "shop.example.com", "ftp://shop.example.com", "https://", "not a url"]) {
            assert.equal(hostOf(text), "", text);
        }
    });
    it("passes a sound draft", () => {
        assert.deepEqual(connectionErrors(DRAFT), {});
        assert.deepEqual(connectionErrors({
            ...DRAFT,
            allowed_host: "",
            sync_frequency: "Manual",
            cron_rule: "",
            api_rate_limit: "",
        }), {});
        assert.deepEqual(connectionErrors({ ...DRAFT, api_rate_limit: "0" }), {});
    });
    it("wants an http or https server URL", () => {
        assert.deepEqual(connectionErrors({ ...DRAFT, server_url: "  " }), {
            server_url: "A server URL is needed.",
        });
        for (const server_url of ["shop.example.com", "ftp://shop.example.com", "https://"]) {
            assert.deepEqual(Object.keys(connectionErrors({ ...DRAFT, server_url })), ["server_url"], server_url);
        }
        assert.deepEqual(connectionErrors({ ...DRAFT, server_url: "http://shop.example.com" }), {});
    });
    it("wants the allowed host to be the URL's", () => {
        const hosts = (server_url, allowed_host) => connectionErrors({ ...DRAFT, server_url, allowed_host }).allowed_host;
        assert.equal(hosts("https://shop.example.com", "SHOP.example.com"), undefined);
        assert.equal(hosts("https://shop.example.com", " shop.example.com. "), undefined);
        assert.equal(hosts("https://shop.example.com", "shop.example.com:443"), undefined);
        assert.equal(hosts("http://shop.example.com", "shop.example.com:80"), undefined);
        assert.equal(hosts("http://localhost:8080/api", "localhost:8080"), undefined);
        assert.equal(hosts("https://shop.example.com", "evil.example.com"), "The server URL's host is shop.example.com, not evil.example.com.");
        assert.match(hosts("http://localhost:8080", "localhost") ?? "", /localhost:8080, not localhost\./);
        assert.match(hosts("https://shop.example.com", "shop.example.com:8443") ?? "", /not shop\.example\.com:8443/);
        for (const allowed of [
            "https://shop.example.com",
            "shop.example.com/api",
            "a b",
            "user@shop.example.com",
            "shop.example.com:port",
        ]) {
            assert.equal(hosts("https://shop.example.com", allowed), "Give a host name, or host:port, without a scheme or a path.", allowed);
        }
        // with no URL to compare with, only the URL is wrong
        assert.deepEqual(Object.keys(connectionErrors({ ...DRAFT, server_url: "", allowed_host: "x y" })), [
            "server_url",
        ]);
    });
    it("wants a cron rule for Cron and a whole rate limit", () => {
        assert.deepEqual(connectionErrors({ ...DRAFT, cron_rule: " " }), {
            cron_rule: "A cron rule is needed when the frequency is Cron.",
        });
        assert.deepEqual(connectionErrors({ ...DRAFT, sync_frequency: "Hourly", cron_rule: "" }), {});
        for (const api_rate_limit of ["-1", "1.5", "many", "1e3"]) {
            assert.deepEqual(Object.keys(connectionErrors({ ...DRAFT, api_rate_limit })), ["api_rate_limit"], api_rate_limit);
        }
    });
    it("keeps the stored secret by leaving it out", () => {
        const payload = connectionPayload(DRAFT, { kind: "keep" }, DETAIL.modified);
        assert.deepEqual(payload, {
            server_url: "https://shop.example.com/api",
            allowed_host: "shop.example.com",
            auth_type: "Basic",
            api_key: "robot",
            sync_frequency: "Cron",
            cron_rule: "0 6 * * *",
            api_rate_limit: 60,
            modified: "2026-01-15 09:00:00.000000",
        });
        assert.equal("api_secret" in payload, false);
    });
    it("sets and removes the secret", () => {
        assert.equal(connectionPayload(DRAFT, { kind: "set", value: " s3cret " }, DETAIL.modified)["api_secret"], " s3cret ");
        const removed = connectionPayload(DRAFT, { kind: "remove" }, DETAIL.modified);
        assert.equal("api_secret" in removed, true);
        assert.equal(removed["api_secret"], "");
    });
    it("never sends the shots or Enabled, and sends nothing as null", () => {
        const empty = {
            server_url: " https://shop.example.com ",
            allowed_host: "",
            auth_type: "Header-based",
            api_key: " ",
            sync_frequency: "Manual",
            cron_rule: "",
            api_rate_limit: "",
        };
        for (const secret of [{ kind: "keep" }, { kind: "set", value: "x" }, { kind: "remove" }]) {
            const payload = connectionPayload(empty, secret, "m");
            assert.equal("shots" in payload, false);
            assert.equal("enabled" in payload, false);
            assert.equal("name" in payload, false);
            assert.equal(payload["server_url"], "https://shop.example.com");
            assert.equal(payload["allowed_host"], null);
            assert.equal(payload["api_key"], null);
            assert.equal(payload["cron_rule"], null);
            assert.equal(payload["api_rate_limit"], null);
        }
        assert.equal(connectionPayload({ ...empty, api_rate_limit: " 0 " }, { kind: "keep" }, "m")["api_rate_limit"], 0);
    });
    it("checks a shot", () => {
        assert.deepEqual(shotErrors(SHOT), {});
        // neither importing nor exporting only adds the Sync tab
        assert.deepEqual(shotErrors({ ...SHOT, do_import: 0, import_transform: "", do_export: 0, export_transform: "" }), {});
        assert.deepEqual(shotErrors({ ...SHOT, dt: "" }), { dt: "Choose a DocType." });
        assert.deepEqual(shotErrors({ ...SHOT, import_transform: "" }), {
            import_transform: "An import transform is needed to import.",
        });
        assert.deepEqual(shotErrors({ ...SHOT, export_transform: "", update_transform: "U" }), {
            export_transform: "A create transform is needed to export.",
        });
        assert.deepEqual(Object.keys(shotErrors({ ...SHOT, dt: "", import_transform: "", export_transform: "" })), ["dt", "import_transform", "export_transform"]);
    });
    it("offers a shot the transforms of its DocType and direction", () => {
        const option = (name, direction, document_type, status) => ({
            name,
            direction,
            document_type,
            status,
            api_spec: "Example Shop - Shop",
        });
        const options = [
            option("Draft import", "Import", "Task", "Draft"),
            option("Zed import", "Import", "Task", "Active"),
            option("An import", "Import", "Task", "Active"),
            option("Create task", "Export", "Task", "Active"),
            option("Project import", "Import", "Project", "Active"),
        ];
        assert.deepEqual(optionsFor(options, "Task", "Import").map((each) => each.name), ["An import", "Zed import", "Draft import"]);
        assert.deepEqual(optionsFor(options, "Task", "Export").map((each) => each.name), ["Create task"]);
        assert.deepEqual(optionsFor(options, "Project", "Export"), []);
        assert.deepEqual(optionsFor([], "Task", "Import"), []);
        // the list given is left as it was
        assert.equal(options[0]?.name, "Draft import");
    });
});
