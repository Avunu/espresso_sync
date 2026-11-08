// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/** frappe-js-sdk's call.get/call.post resolve with the raw HTTP body -
 * Frappe's `{ message: <return value> }` envelope - not the inner payload,
 * even though the SDK's own generic pretends otherwise (verified against the
 * bundled SDK 1.17.1, call.get `.then(m => m.data)`). useBackendCall unwraps
 * it; anything read straight through the SDK (useFrappeGetCall) must type
 * its response as an envelope. */
export interface FrappeEnvelope<T> {
	message: T;
}

export type ToastKind = "success" | "warning" | "error" | "info";

export interface ToastState {
	id: number;
	kind: ToastKind;
	title: string;
}

export type ShowToast = (toast: Omit<ToastState, "id">) => void;

/** What espresso_sync/portal.py's set_portal_context() puts in `boot`: nothing about any Connection. */
export interface PortalBoot {
	user: string;
	session_expiry?: string;
	/** The transform editor's JSONata worker script (public/js/espresso-sync-eval.bundle.js). */
	eval_worker: string;
}

declare global {
	interface Window {
		csrf_token?: string;
		sitename?: string;
		portal_boot?: PortalBoot;
	}
}
