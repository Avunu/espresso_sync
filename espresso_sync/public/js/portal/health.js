// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
/**
 * The health of a Connection, derived from its `list_status` row.
 *
 * There is no record of a run: "the last sync" is everything logged since the
 * Connection's Last Sync Attempt. The rules are read in order and the first that
 * applies names the health, so a Connection that is syncing or paused is never
 * also failing.
 */
import { parseServerDatetime, plural } from "./datetime.ts";
const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
/** How long after its last attempt a scheduled Connection is overdue. */
const OVERDUE_AFTER = {
    "Every Minute": 15 * MINUTE,
    Hourly: 2 * HOUR,
    Daily: 48 * HOUR,
    Weekly: 14 * DAY,
    Monthly: 62 * DAY,
};
/** How far past its next cron time a Cron Connection is overdue. */
const CRON_GRACE = 15 * MINUTE;
function time(value) {
    return value ? parseServerDatetime(value)?.getTime() : undefined;
}
/** Rule 5: an attempt that never set Last Pull, which only a finished sync does. */
function didNotFinish(row) {
    const attempt = time(row.last_sync_attempt);
    if (attempt === undefined)
        return false;
    const pull = time(row.last_pull);
    return pull === undefined || pull < attempt;
}
/** Rule 8: the scheduler should have synced the Connection by now. */
function isOverdue(row, now) {
    const current = time(now);
    if (current === undefined || !row.sync_frequency)
        return false;
    if (row.sync_frequency === "Cron") {
        const next = time(row.next_run);
        return next !== undefined && current - next > CRON_GRACE;
    }
    const allowed = OVERDUE_AFTER[row.sync_frequency];
    const attempt = time(row.last_sync_attempt);
    return allowed !== undefined && attempt !== undefined && current - attempt > allowed;
}
/** The health of a Connection at `now`, the server's own time. */
export function deriveHealth(row, now) {
    if (row.state === "running")
        return { kind: "running", label: "Syncing", reason: null };
    if (row.state === "queued")
        return { kind: "queued", label: "Queued", reason: null };
    if (!row.enabled)
        return { kind: "paused", label: "Paused", reason: null };
    const [problem] = row.problems;
    if (problem)
        return { kind: "failing", label: "Failing", reason: problem.message };
    if (didNotFinish(row))
        return { kind: "failing", label: "Failing", reason: "The last sync did not finish" };
    const failed = plural(row.failures_last_run, "failure", "failures");
    if (row.failures_last_run > 0 && row.successes_last_run === 0) {
        return { kind: "failing", label: "Failing", reason: `${failed} in the last sync, nothing synced` };
    }
    if (row.failures_last_run > 0) {
        return { kind: "warning", label: "Some failures", reason: `${failed} in the last sync` };
    }
    if (isOverdue(row, now)) {
        return { kind: "warning", label: "Overdue", reason: "Overdue: is the scheduler running?" };
    }
    if (!row.last_sync_attempt)
        return { kind: "never", label: "Never synced", reason: null };
    return { kind: "healthy", label: "Healthy", reason: null };
}
/** Whether somebody should look at the Connection: it is failing or warning. */
export function needsAttention(row, now) {
    const { kind } = deriveHealth(row, now);
    return kind === "failing" || kind === "warning";
}
const SEVERITY = {
    failing: 0,
    warning: 1,
    running: 2,
    queued: 3,
    never: 4,
    unknown: 5,
    healthy: 6,
    paused: 7,
};
/** The sort order of a health: the lower, the sooner it is worth a look. */
export function severityRank(kind) {
    return SEVERITY[kind];
}
