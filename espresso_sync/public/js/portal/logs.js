// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
/**
 * Reading the Pull Log: the error of an entry, and the Sync log's filters as
 * they travel between the URL (`?status=Failure&since=24h`), the page, and the
 * list request.
 */
import { parseServerDatetime, toServerDatetime } from "./datetime.ts";
/** The error a failed entry ends with, or null when it has none. `diagnostics`
 * is the entry's JSON field, as text or already parsed: the sync appends the
 * failure itself after the schema's findings, so the last error is the reason. */
export function lastError(diagnostics) {
    let list = diagnostics;
    if (typeof list === "string") {
        try {
            list = JSON.parse(list);
        }
        catch {
            return null;
        }
    }
    if (!Array.isArray(list))
        return null;
    for (let index = list.length - 1; index >= 0; index--) {
        const entry = list[index];
        if (typeof entry !== "object" || entry === null)
            continue;
        const { severity, code, message } = entry;
        if (severity !== "error" || typeof code !== "string" || !code)
            continue;
        return { code, message: typeof message === "string" ? message : "" };
    }
    return null;
}
/** Every filter of the Sync log, in the order its query and its tags list them. */
export const FILTER_KEYS = [
    "connection",
    "status",
    "direction",
    "doctype",
    "transform",
    "doc",
    "docs",
    "since",
    "code",
];
/** The filters a route's query carries; any other key (`page`) is left out. */
export function filtersFromQuery(query) {
    const filters = {};
    for (const key of FILTER_KEYS) {
        const value = query[key];
        if (value)
            filters[key] = value;
    }
    return filters;
}
/** The filters that are set, as a query for `hrefFor`. */
export function queryFromFilters(filters) {
    const query = {};
    for (const key of FILTER_KEYS) {
        const value = filters[key];
        if (value)
            query[key] = value;
    }
    return query;
}
/** The Pull Log field each exact-match filter is. */
const FIELDS = [
    ["connection", "sync_connection"],
    ["status", "sync_status"],
    ["direction", "sync_direction"],
    ["doctype", "sync_doctype"],
    ["transform", "transform"],
];
const PERIODS = {
    "1h": 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
};
const DAY = /^\d{4}-\d{2}-\d{2}$/;
function sinceFilters(since, now, lastAttempt) {
    if (since === "attempt")
        return lastAttempt ? [["creation", ">=", lastAttempt]] : [];
    const period = PERIODS[since];
    if (period !== undefined) {
        const current = parseServerDatetime(now);
        return current ? [["creation", ">=", toServerDatetime(new Date(current.getTime() - period))]] : [];
    }
    const day = DAY.test(since) ? parseServerDatetime(since) : null;
    if (!day)
        return [];
    const next = toServerDatetime(new Date(day.getTime() + 24 * 60 * 60 * 1000));
    return [
        ["creation", ">=", `${since} 00:00:00`],
        ["creation", "<", next],
    ];
}
/** The filters as the list request takes them. `now` is the server's time;
 * `lastAttempt` is the Connection's Last Sync Attempt, for `since=attempt`
 * (without one, that filter is no filter). `code` is not sent: the code is
 * inside the diagnostics JSON, which the server cannot filter on. */
export function frappeFilters(filters, now, lastAttempt) {
    const result = [];
    for (const [key, field] of FIELDS) {
        const value = filters[key];
        if (value)
            result.push([field, "=", value]);
    }
    if (filters.doc)
        result.push(["sync_doc", "like", `%${filters.doc}%`]);
    // a request's entry names no document: what was synced is counted without them
    if (filters.docs)
        result.push(["sync_doc", "is", "set"]);
    if (filters.since)
        result.push(...sinceFilters(filters.since, now, lastAttempt));
    return result;
}
/** A value as indented JSON. JSON text is parsed first, so a stored payload is
 * laid out too; text that is not JSON is given back as it is, and nothing is "". */
export function prettyJson(value) {
    if (value === null || value === undefined || value === "")
        return "";
    if (typeof value === "string") {
        try {
            return JSON.stringify(JSON.parse(value), null, 2);
        }
        catch {
            return value;
        }
    }
    return JSON.stringify(value, null, 2) ?? "";
}
/** What to do about a failure, by the code of its last error. */
export const ERROR_HINTS = {
    "transform-not-active": "The transform went back to Draft. Activate it again, or pause the Connection until it is ready.",
    "http-status": "The API refused the request. The Response tab has its answer; a 401 or 403 means the credentials need a look.",
    conflict: "The document changed here and in the API since the last sync. The export sends the change made here; nothing was imported over it.",
    "invalid-payload": "The mapped object does not pass the schema. The diagnostics name the fields; fix the transform's rules, or set its Runtime Validation to Warn.",
    "no-external-id": "The transform's External ID expression gives nothing for this item. Check it against the API object.",
    "max-pages": "The transform's Maximum Pages was reached with more to read. Raise it, or narrow the request.",
    "next-request": "The transform's Next Request expression must give an object of query parameters, or nothing.",
    "invalid-json": "The API answered with something other than JSON. The Response tab has what it sent.",
};
