/** A server datetime (or date) as a Date whose UTC fields are the site's wall
 * clock; null for text that is not one. */
export declare function parseServerDatetime(value: string): Date | null;
/** A Date from `parseServerDatetime`, back in the server's form, to the second. */
export declare function toServerDatetime(date: Date): string;
/** `2026-01-15 09:30`, in the site's time zone. Text that is not a datetime is
 * given back as it is. */
export declare function formatAbsolute(value: string): string;
/** `3 minutes`: a count with its noun. */
export declare function plural(n: number, one: string, many: string): string;
/** "5 minutes ago", "In 2 hours", "Never" for null. From 7 days away, either
 * way, it is the absolute form. */
export declare function relativeTime(value: string | null, now: string): string;
/** `312 ms`, `1.2 s`, `2 min 5 s`, `1 h 3 min`. */
export declare function formatDuration(ms: number): string;
/** A Connection's Sync Frequency in a few words: "Hourly", "Cron: 0 6 * * *". */
export declare function describeSchedule(frequency: string | null, cron: string | null): string;
