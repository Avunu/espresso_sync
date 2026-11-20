// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * Dates and counts as the portal words them.
 *
 * The server answers with naive datetimes in the site's time zone
 * (`2026-01-15 09:30:00.123456`), and with its own `now` in the same form. Both
 * are read as if they were UTC, so the difference between two of them is right
 * whatever the browser's time zone is, and nothing here reads the clock.
 */

const SERVER_DATETIME = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?$/;

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function pad(value: number, length = 2): string {
	return String(value).padStart(length, "0");
}

/** A server datetime (or date) as a Date whose UTC fields are the site's wall
 * clock; null for text that is not one. */
export function parseServerDatetime(value: string): Date | null {
	const match = SERVER_DATETIME.exec(value.trim());
	if (!match) return null;
	const [year, month, day, hour, minute, second] = match.slice(1, 7).map((part) => Number(part ?? 0));
	const milliseconds = Number((match[7] ?? "").slice(0, 3).padEnd(3, "0"));
	const time = Date.UTC(year ?? 0, (month ?? 1) - 1, day, hour, minute, second, milliseconds);
	const date = new Date(time);
	// 2026-02-31 would roll over into March
	if (date.getUTCMonth() !== (month ?? 1) - 1 || date.getUTCDate() !== day) return null;
	return date;
}

/** A Date from `parseServerDatetime`, back in the server's form, to the second. */
export function toServerDatetime(date: Date): string {
	return (
		`${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
		`${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`
	);
}

/** `2026-01-15 09:30`, in the site's time zone. Text that is not a datetime is
 * given back as it is. */
export function formatAbsolute(value: string): string {
	const date = parseServerDatetime(value);
	return date ? toServerDatetime(date).slice(0, 16) : value;
}

/** `3 minutes`: a count with its noun. */
export function plural(n: number, one: string, many: string): string {
	return `${n} ${n === 1 ? one : many}`;
}

/** "5 minutes ago", "In 2 hours", "Never" for null. From 7 days away, either
 * way, it is the absolute form. */
export function relativeTime(value: string | null, now: string): string {
	if (!value) return "Never";
	const then = parseServerDatetime(value);
	const reference = parseServerDatetime(now);
	if (!then || !reference) return formatAbsolute(value);
	const elapsed = reference.getTime() - then.getTime();
	const distance = Math.abs(elapsed);
	if (distance >= 7 * DAY) return formatAbsolute(value);
	if (distance < MINUTE) return elapsed >= 0 ? "Just now" : "In a moment";
	const amount =
		distance < HOUR
			? plural(Math.floor(distance / MINUTE), "minute", "minutes")
			: distance < DAY
				? plural(Math.floor(distance / HOUR), "hour", "hours")
				: plural(Math.floor(distance / DAY), "day", "days");
	return elapsed >= 0 ? `${amount} ago` : `In ${amount}`;
}

/** `312 ms`, `1.2 s`, `2 min 5 s`, `1 h 3 min`. */
export function formatDuration(ms: number): string {
	if (!Number.isFinite(ms) || ms < 0) return "";
	if (ms < SECOND) return `${Math.round(ms)} ms`;
	if (ms < 10 * SECOND) return `${(Math.floor(ms / 100) / 10).toFixed(1)} s`;
	const seconds = Math.floor(ms / SECOND);
	if (seconds < 60) return `${seconds} s`;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return seconds % 60 ? `${minutes} min ${seconds % 60} s` : `${minutes} min`;
	const hours = Math.floor(minutes / 60);
	return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
}

const SCHEDULES: Record<string, string> = {
	Manual: "Manual",
	"Every Minute": "Every minute",
	Hourly: "Hourly",
	Daily: "Daily",
	Weekly: "Weekly",
	Monthly: "Monthly",
};

/** A Connection's Sync Frequency in a few words: "Hourly", "Cron: 0 6 * * *". */
export function describeSchedule(frequency: string | null, cron: string | null): string {
	if (!frequency) return "Manual";
	if (frequency === "Cron") return cron ? `Cron: ${cron}` : "Cron";
	return SCHEDULES[frequency] ?? frequency;
}
