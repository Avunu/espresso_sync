/** The error a failed entry ends with, or null when it has none. `diagnostics`
 * is the entry's JSON field, as text or already parsed: the sync appends the
 * failure itself after the schema's findings, so the last error is the reason. */
export declare function lastError(diagnostics: unknown): {
    code: string;
    message: string;
} | null;
/** The Sync log's filters. `since` is `1h`, `24h`, `7d`, `attempt` (since the
 * Connection's last sync attempt) or one day as `YYYY-MM-DD`; `docs` is `1`
 * for the entries of documents alone, without those of requests; `code` is an
 * error code, matched in the page. */
export interface LogFilters {
    connection?: string;
    status?: string;
    direction?: string;
    doctype?: string;
    transform?: string;
    doc?: string;
    docs?: string;
    since?: string;
    code?: string;
}
/** Every filter of the Sync log, in the order its query and its tags list them. */
export declare const FILTER_KEYS: readonly (keyof LogFilters)[];
/** The filters a route's query carries; any other key (`page`) is left out. */
export declare function filtersFromQuery(query: Readonly<Record<string, string>>): LogFilters;
/** The filters that are set, as a query for `hrefFor`. */
export declare function queryFromFilters(filters: LogFilters): Record<string, string>;
/** The filters as the list request takes them. `now` is the server's time;
 * `lastAttempt` is the Connection's Last Sync Attempt, for `since=attempt`
 * (without one, that filter is no filter). `code` is not sent: the code is
 * inside the diagnostics JSON, which the server cannot filter on. */
export declare function frappeFilters(filters: LogFilters, now: string, lastAttempt?: string | null): [string, string, string][];
/** A value as indented JSON. JSON text is parsed first, so a stored payload is
 * laid out too; text that is not JSON is given back as it is, and nothing is "". */
export declare function prettyJson(value: unknown): string;
/** What to do about a failure, by the code of its last error. */
export declare const ERROR_HINTS: Record<string, string>;
