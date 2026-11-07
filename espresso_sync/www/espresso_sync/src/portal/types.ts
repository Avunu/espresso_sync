// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/** frappe-js-sdk's call.get/call.post resolve with the raw HTTP body -
 * Frappe's `{ message: <return value> }` envelope - not the inner payload,
 * even though the SDK's own generic pretends otherwise. useBackendCall
 * unwraps it; anything read straight through the SDK (useFrappeGetCall) must
 * type its response as an envelope. */
export interface FrappeEnvelope<T> {
	message: T;
}

export type ToastKind = "success" | "warning" | "error" | "info";

export interface ToastState {
	id: number;
	kind: ToastKind;
	title: string;
	subtitle?: string;
}

export type ShowToast = (toast: Omit<ToastState, "id">) => void;

/** What espresso_sync/portal.py's get_boot() puts in `boot`: no Connection data, nothing secret. */
export interface PortalBoot {
	user: string;
	full_name: string;
	/** System Settings' session_expiry, "HH:MM[:SS]". */
	session_expiry?: string;
}

declare global {
	interface Window {
		csrf_token?: string;
		sitename?: string;
		developer_mode?: boolean;
		portal_boot?: PortalBoot;
	}
}
