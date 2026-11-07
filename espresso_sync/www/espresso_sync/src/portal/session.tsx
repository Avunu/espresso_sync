// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import {
	createContext,
	type PropsWithChildren,
	useCallback,
	useContext,
	useEffect,
	useMemo,
	useRef,
} from "react";

/** System Settings' session_expiry ("HH:MM[:SS]", frappe/sessions.py) in milliseconds. */
export function parseSessionExpiry(value: string | undefined): number {
	if (!value) return 240 * 60 * 60 * 1000; // the System Settings default, "240:00"
	const [hours = 0, minutes = 0, seconds = 0] = value.split(":").map(Number);
	return ((hours * 60 + minutes) * 60 + seconds) * 1000;
}

export interface SessionContextValue {
	/** Call after any successful backend response - each one extends the server-side session. */
	recordActivity: () => void;
	/** Call from any call site that gets back a 403. */
	reportForbidden: () => void;
}

const noop = () => {};

const SessionContext = createContext<SessionContextValue>({
	recordActivity: noop,
	reportForbidden: noop,
});

export function useSession(): SessionContextValue {
	return useContext(SessionContext);
}

/**
 * Keeps an open editor from sitting on a dead session. The timer starts from
 * System Settings' session_expiry at page load and restarts on every
 * successful backend call - the same thing that extends Frappe's own session.
 * When it runs out, or any call comes back 403 (a server-side logout beats any
 * client timer), the page reloads. A reload as a Guest hits portal.py's
 * require_login(), which hands off to core /login and comes back here
 * afterwards - this side never needs to know how signing in works.
 */
export function SessionProvider({ children }: PropsWithChildren) {
	const expiryMs = useRef(parseSessionExpiry(window.portal_boot?.session_expiry));
	// Set when the timer starts, below: Date.now() is impure, so not while rendering.
	const lastActivity = useRef(0);
	const reloading = useRef(false);

	const reload = useCallback(() => {
		if (reloading.current) return;
		reloading.current = true;
		// Keeps the hash, so the user comes back to the same screen after signing in.
		window.location.reload();
	}, []);

	const recordActivity = useCallback(() => {
		lastActivity.current = Date.now();
	}, []);

	useEffect(() => {
		lastActivity.current = Date.now();
		const interval = window.setInterval(() => {
			if (Date.now() - lastActivity.current >= expiryMs.current) reload();
		}, 5000);
		return () => window.clearInterval(interval);
	}, [reload]);

	const value = useMemo(() => ({ recordActivity, reportForbidden: reload }), [recordActivity, reload]);

	return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
