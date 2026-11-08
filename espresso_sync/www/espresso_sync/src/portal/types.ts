// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

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
