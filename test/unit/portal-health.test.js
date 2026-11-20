// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deriveHealth, needsAttention, severityRank, } from "../../espresso_sync/public/js/portal/health.ts";
const NOW = "2026-01-15 12:00:00.000000";
/** An enabled, idle, Manual Connection whose last sync finished clean. */
function row(changes = {}) {
    return {
        name: "Shop",
        enabled: 1,
        server_url: "https://shop.example.com",
        sync_frequency: "Manual",
        cron_rule: null,
        last_pull: "2026-01-15 11:00:05",
        last_sync_attempt: "2026-01-15 11:00:00",
        state: "idle",
        next_run: null,
        shots: 1,
        problems: [],
        failures_last_run: 0,
        successes_last_run: 4,
        failures_24h: 0,
        successes_24h: 4,
        last_failure: null,
        ...changes,
    };
}
const PROBLEM = {
    code: "transform-not-active",
    message: "Shop Tasks is not Active",
    doctype: "Task",
    transform: "Shop Tasks",
};
/** Everything wrong at once: each rule below removes the one above it. */
const WORST = row({
    state: "running",
    enabled: 0,
    problems: [PROBLEM, { ...PROBLEM, message: "Another" }],
    last_pull: null,
    failures_last_run: 3,
    successes_last_run: 0,
    sync_frequency: "Hourly",
    last_sync_attempt: "2026-01-15 08:00:00",
});
describe("portal health", () => {
    it("rule 1: running", () => {
        assert.deepEqual(deriveHealth(WORST, NOW), { kind: "running", label: "Syncing", reason: null });
    });
    it("rule 2: queued", () => {
        assert.deepEqual(deriveHealth({ ...WORST, state: "queued" }, NOW), {
            kind: "queued",
            label: "Queued",
            reason: null,
        });
    });
    it("rule 3: paused", () => {
        assert.deepEqual(deriveHealth({ ...WORST, state: "idle" }, NOW), {
            kind: "paused",
            label: "Paused",
            reason: null,
        });
    });
    it("rule 4: a shot's transform no longer fits", () => {
        assert.deepEqual(deriveHealth({ ...WORST, state: "idle", enabled: 1 }, NOW), {
            kind: "failing",
            label: "Failing",
            reason: "Shop Tasks is not Active",
        });
    });
    it("rule 5: the last sync did not finish", () => {
        const unfinished = { ...WORST, state: "idle", enabled: 1, problems: [] };
        const expected = { kind: "failing", label: "Failing", reason: "The last sync did not finish" };
        assert.deepEqual(deriveHealth(unfinished, NOW), expected);
        // a Last Pull older than the attempt is the sync before it
        assert.deepEqual(deriveHealth({ ...unfinished, last_pull: "2026-01-15 07:59:59" }, NOW), expected);
        // one at the attempt's own time is not
        assert.notEqual(deriveHealth({ ...unfinished, last_pull: "2026-01-15 08:00:00" }, NOW).reason, expected.reason);
    });
    it("rule 6: everything failed", () => {
        const failed = row({ failures_last_run: 3, successes_last_run: 0 });
        assert.deepEqual(deriveHealth(failed, NOW), {
            kind: "failing",
            label: "Failing",
            reason: "3 failures in the last sync, nothing synced",
        });
        assert.equal(deriveHealth({ ...failed, failures_last_run: 1 }, NOW).reason, "1 failure in the last sync, nothing synced");
    });
    it("rule 7: some failed", () => {
        assert.deepEqual(deriveHealth(row({ failures_last_run: 1, successes_last_run: 9 }), NOW), {
            kind: "warning",
            label: "Some failures",
            reason: "1 failure in the last sync",
        });
        // before overdue
        const both = row({
            failures_last_run: 2,
            sync_frequency: "Hourly",
            last_sync_attempt: "2026-01-14 08:00:00",
            last_pull: "2026-01-14 08:00:01",
        });
        assert.equal(deriveHealth(both, NOW).reason, "2 failures in the last sync");
    });
    it("rule 8: overdue, by frequency", () => {
        const overdue = { kind: "warning", label: "Overdue", reason: "Overdue: is the scheduler running?" };
        const at = (sync_frequency, attempt) => deriveHealth(row({ sync_frequency, last_sync_attempt: attempt, last_pull: attempt }), NOW);
        // each threshold: just inside it, then just past it
        const cases = [
            ["Every Minute", "2026-01-15 11:45:00", "2026-01-15 11:44:59"],
            ["Hourly", "2026-01-15 10:00:00", "2026-01-15 09:59:59"],
            ["Daily", "2026-01-13 12:00:00", "2026-01-13 11:59:59"],
            ["Weekly", "2026-01-01 12:00:00", "2026-01-01 11:59:59"],
            ["Monthly", "2025-11-14 12:00:00", "2025-11-14 11:59:59"],
        ];
        for (const [frequency, inside, past] of cases) {
            assert.equal(at(frequency, inside).kind, "healthy", frequency);
            assert.deepEqual(at(frequency, past), overdue, frequency);
        }
        // a Manual Connection is never overdue, nor a frequency nobody knows
        assert.equal(at("Manual", "2020-01-01 00:00:00").kind, "healthy");
        assert.equal(at("Fortnightly", "2020-01-01 00:00:00").kind, "healthy");
        assert.equal(deriveHealth(row({
            sync_frequency: null,
            last_sync_attempt: "2020-01-01 00:00:00",
            last_pull: "2020-01-01 00:00:00",
        }), NOW).kind, "healthy");
        // without a time to measure from, nothing is
        assert.equal(deriveHealth(row({
            sync_frequency: "Hourly",
            last_sync_attempt: "2020-01-01 00:00:00",
            last_pull: "2020-01-01 00:00:00",
        }), "?").kind, "healthy");
    });
    it("rule 8: overdue, for a cron rule", () => {
        const cron = (next_run) => deriveHealth(row({
            sync_frequency: "Cron",
            cron_rule: "0 * * * *",
            next_run,
            last_sync_attempt: "2020-01-01 00:00:00",
            last_pull: "2020-01-01 00:00:00",
        }), NOW);
        assert.equal(cron("2026-01-15 13:00:00").kind, "healthy");
        assert.equal(cron("2026-01-15 11:45:00").kind, "healthy");
        assert.equal(cron("2026-01-15 11:44:59").label, "Overdue");
        assert.equal(cron(null).kind, "healthy");
    });
    it("rule 9: never synced", () => {
        const never = row({ last_sync_attempt: null, last_pull: null, successes_last_run: 0 });
        assert.deepEqual(deriveHealth(never, NOW), { kind: "never", label: "Never synced", reason: null });
        // a scheduled one has nothing to be overdue from
        assert.equal(deriveHealth({ ...never, sync_frequency: "Hourly" }, NOW).kind, "never");
        // but a cron one that missed its time is overdue first
        assert.equal(deriveHealth({ ...never, sync_frequency: "Cron", next_run: "2026-01-15 09:00:00" }, NOW).label, "Overdue");
    });
    it("rule 10: healthy", () => {
        assert.deepEqual(deriveHealth(row(), NOW), { kind: "healthy", label: "Healthy", reason: null });
        assert.equal(deriveHealth(row({ successes_last_run: 0 }), NOW).kind, "healthy");
    });
    it("needs attention when failing or warning only", () => {
        assert.equal(needsAttention(row({ problems: [PROBLEM] }), NOW), true);
        assert.equal(needsAttention(row({ last_pull: null }), NOW), true);
        assert.equal(needsAttention(row({ failures_last_run: 2, successes_last_run: 0 }), NOW), true);
        assert.equal(needsAttention(row({ failures_last_run: 2 }), NOW), true);
        assert.equal(needsAttention(row({
            sync_frequency: "Hourly",
            last_sync_attempt: "2026-01-14 00:00:00",
            last_pull: "2026-01-14 00:00:01",
        }), NOW), true);
        assert.equal(needsAttention(row(), NOW), false);
        assert.equal(needsAttention(row({ last_sync_attempt: null, last_pull: null }), NOW), false);
        // syncing or paused comes first
        assert.equal(needsAttention(WORST, NOW), false);
        assert.equal(needsAttention({ ...WORST, state: "queued" }, NOW), false);
        assert.equal(needsAttention({ ...WORST, state: "idle" }, NOW), false);
    });
    it("ranks the worst first", () => {
        const kinds = [
            "paused",
            "healthy",
            "unknown",
            "never",
            "queued",
            "running",
            "warning",
            "failing",
        ];
        assert.deepEqual([...kinds].sort((a, b) => severityRank(a) - severityRank(b)), ["failing", "warning", "running", "queued", "never", "unknown", "healthy", "paused"]);
    });
});
