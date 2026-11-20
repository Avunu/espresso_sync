// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { describeSchedule, formatAbsolute, formatDuration, parseServerDatetime, plural, relativeTime, toServerDatetime, } from "../../espresso_sync/public/js/portal/datetime.ts";
const NOW = "2026-01-15 12:00:00.000000";
describe("portal datetime", () => {
    it("parses the server's naive datetimes", () => {
        assert.equal(parseServerDatetime("2026-01-15 09:30:05.123456")?.toISOString(), "2026-01-15T09:30:05.123Z");
        assert.equal(parseServerDatetime("2026-01-15 09:30:05")?.toISOString(), "2026-01-15T09:30:05.000Z");
        assert.equal(parseServerDatetime("2026-01-15T09:30")?.toISOString(), "2026-01-15T09:30:00.000Z");
        assert.equal(parseServerDatetime(" 2026-01-15 ")?.toISOString(), "2026-01-15T00:00:00.000Z");
        assert.equal(parseServerDatetime("2026-01-15 09:30:05.5")?.getUTCMilliseconds(), 500);
    });
    it("refuses what is not a datetime", () => {
        for (const text of ["", "yesterday", "2026-1-5", "2026-02-31", "2026-13-01 00:00:00", "15/01/2026"]) {
            assert.equal(parseServerDatetime(text), null, text);
        }
    });
    it("writes a datetime back in the server's form", () => {
        assert.equal(toServerDatetime(new Date(Date.UTC(2026, 0, 5, 3, 4, 9, 900))), "2026-01-05 03:04:09");
        assert.equal(formatAbsolute("2026-01-15 09:30:05.123456"), "2026-01-15 09:30");
        assert.equal(formatAbsolute("2026-01-15"), "2026-01-15 00:00");
        assert.equal(formatAbsolute("soon"), "soon");
    });
    it("counts with the right noun", () => {
        assert.equal(plural(1, "entry", "entries"), "1 entry");
        assert.equal(plural(0, "entry", "entries"), "0 entries");
        assert.equal(plural(12, "entry", "entries"), "12 entries");
    });
    it("words the past by bucket", () => {
        assert.equal(relativeTime(null, NOW), "Never");
        assert.equal(relativeTime("", NOW), "Never");
        assert.equal(relativeTime("2026-01-15 12:00:00", NOW), "Just now");
        assert.equal(relativeTime("2026-01-15 11:59:01", NOW), "Just now");
        assert.equal(relativeTime("2026-01-15 11:59:00", NOW), "1 minute ago");
        assert.equal(relativeTime("2026-01-15 11:00:01", NOW), "59 minutes ago");
        assert.equal(relativeTime("2026-01-15 11:00:00", NOW), "1 hour ago");
        assert.equal(relativeTime("2026-01-14 12:00:01", NOW), "23 hours ago");
        assert.equal(relativeTime("2026-01-14 12:00:00", NOW), "1 day ago");
        assert.equal(relativeTime("2026-01-08 12:00:01", NOW), "6 days ago");
        assert.equal(relativeTime("2026-01-08 12:00:00", NOW), "2026-01-08 12:00");
        assert.equal(relativeTime("2025-06-01 08:15:00", NOW), "2025-06-01 08:15");
    });
    it("words the future, and what it cannot read", () => {
        assert.equal(relativeTime("2026-01-15 12:00:30", NOW), "In a moment");
        assert.equal(relativeTime("2026-01-15 12:05:00", NOW), "In 5 minutes");
        assert.equal(relativeTime("2026-01-15 14:00:00", NOW), "In 2 hours");
        assert.equal(relativeTime("2026-01-18 12:00:00", NOW), "In 3 days");
        assert.equal(relativeTime("2026-02-01 06:00:00", NOW), "2026-02-01 06:00");
        assert.equal(relativeTime("soon", NOW), "soon");
        assert.equal(relativeTime("2026-01-15 11:00:00", "not a time"), "2026-01-15 11:00");
    });
    it("words a duration", () => {
        assert.equal(formatDuration(0), "0 ms");
        assert.equal(formatDuration(311.6), "312 ms");
        assert.equal(formatDuration(1000), "1.0 s");
        assert.equal(formatDuration(1249), "1.2 s");
        assert.equal(formatDuration(9999), "9.9 s");
        assert.equal(formatDuration(10000), "10 s");
        assert.equal(formatDuration(59999), "59 s");
        assert.equal(formatDuration(60000), "1 min");
        assert.equal(formatDuration(125000), "2 min 5 s");
        assert.equal(formatDuration(3600000), "1 h");
        assert.equal(formatDuration(3780000), "1 h 3 min");
        assert.equal(formatDuration(-1), "");
        assert.equal(formatDuration(Number.NaN), "");
    });
    it("describes a schedule", () => {
        assert.equal(describeSchedule(null, null), "Manual");
        assert.equal(describeSchedule("", null), "Manual");
        assert.equal(describeSchedule("Manual", null), "Manual");
        assert.equal(describeSchedule("Every Minute", null), "Every minute");
        assert.equal(describeSchedule("Hourly", "0 6 * * *"), "Hourly");
        assert.equal(describeSchedule("Daily", null), "Daily");
        assert.equal(describeSchedule("Weekly", null), "Weekly");
        assert.equal(describeSchedule("Monthly", null), "Monthly");
        assert.equal(describeSchedule("Cron", "0 6 * * *"), "Cron: 0 6 * * *");
        assert.equal(describeSchedule("Cron", null), "Cron");
        assert.equal(describeSchedule("Fortnightly", null), "Fortnightly");
    });
});
