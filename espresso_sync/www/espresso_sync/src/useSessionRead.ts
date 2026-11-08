// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect } from "react";
import { useSession } from "./portal/session";
import { readFailure } from "./portal/useBackendCall";

/**
 * What a read hook's answer means for the session (see SessionProvider): data
 * restarts the session timer, and a 403 means the session ended, since
 * portal.py lets no one in who can't read what the page shows.
 */
export function useSessionRead(data: unknown, error: unknown): void {
	const { recordActivity, reportForbidden } = useSession();

	useEffect(() => {
		if (data) recordActivity();
	}, [data, recordActivity]);

	useEffect(() => {
		if (error && readFailure(error).httpStatus === 403) reportForbidden();
	}, [error, reportForbidden]);
}
