// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { formatAbsolute, parseServerDatetime, relativeTime } from "../../../../public/js/portal/datetime.ts";

interface DateTimeProps {
	/** A datetime as the server answers with one: naive, in the site's time zone. */
	value: string | null;
	/** The server's own time (`list_status`): with it, the time reads as "5 minutes ago". */
	now?: string | undefined;
	/** The date and time even though `now` is given. */
	absolute?: boolean;
}

/**
 * A time the server gave, "Never" for none. Shown relative to `now`, or as the date and
 * time; either way the exact time and the site's time zone are its tooltip. Nothing here
 * reads the browser's clock or time zone: the server's times are the site's.
 */
export function DateTime({ value, now, absolute = false }: DateTimeProps) {
	if (!value) return <span>Never</span>;
	const exact = formatAbsolute(value);
	const zone = window.portal_boot?.time_zone;
	const shown = now && !absolute ? relativeTime(value, now) : exact;
	// a naive `YYYY-MM-DDTHH:MM:SS` is what <time> calls a local date and time
	const machine = parseServerDatetime(value)?.toISOString().slice(0, 19);
	return (
		<time
			{...(machine ? { dateTime: machine } : {})}
			title={zone ? `${exact} ${zone}` : exact}
			// "5 minutes ago" is one thing: a narrow column doesn't stack its words
			style={{ whiteSpace: "nowrap" }}
		>
			{shown}
		</time>
	);
}
