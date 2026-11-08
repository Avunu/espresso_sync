// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useCallback } from "react";
import { useFrappePostCall } from "frappe-react-sdk";
import { useSession } from "./session";
import { useToasts } from "./Toasts";
import type { FrappeEnvelope } from "./types";

export type BackendResult<T> = { ok: true; data: T } | { ok: false };

/** The text of `html`, a `<br>` (between frappe.throw()'s reasons) and each item of a list as a line break. */
function stripHtml(html: string): string {
	return new DOMParser()
		.parseFromString(html.replace(/<br\s*\/?>|<li>/gi, "\n"), "text/html")
		.body.textContent.trim();
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

/** JSON.parse that answers undefined for text that isn't JSON. */
function parseJson(text: string): unknown {
	try {
		return JSON.parse(text);
	} catch {
		return undefined;
	}
}

/** What a failed call tells us, read off whatever was thrown. Nothing is asserted: a field
 * that isn't the type we expect is simply absent. */
export interface BackendFailure {
	httpStatus: number | undefined;
	message: string | undefined;
	/** The raw `_server_messages` text frappe.throw() leaves on the response. */
	serverMessages: string | undefined;
}

export function readFailure(error: unknown): BackendFailure {
	const failure = isRecord(error) ? error : {};
	const { httpStatus, message, _server_messages: serverMessages } = failure;
	return {
		httpStatus: typeof httpStatus === "number" ? httpStatus : undefined,
		message: typeof message === "string" ? message : undefined,
		serverMessages: typeof serverMessages === "string" ? serverMessages : undefined,
	};
}

/** One entry of `_server_messages`: JSON text of a `{message}` object, or else plain text. */
function messageOf(entry: unknown): string {
	if (typeof entry !== "string") return "";
	const parsed = parseJson(entry);
	return isRecord(parsed) && typeof parsed["message"] === "string" ? parsed["message"] : entry;
}

/**
 * The human-readable text of a failed call. frappe.throw() puts its message
 * in `_server_messages` (a JSON list of JSON-encoded `{message}` objects);
 * the SDK's own `message` is then only its generic "There was an error.".
 * With no HTTP response at all (offline, timeout), `message` is axios's own
 * text ("Network Error"), which is worth showing as-is.
 */
export function getErrorMessage(error: unknown, fallback: string): string {
	const { httpStatus, message, serverMessages } = readFailure(error);
	if (serverMessages) {
		const entries = parseJson(serverMessages);
		// Not a list - not the shape Frappe sends, so fall through to the generic text.
		if (Array.isArray(entries)) {
			const text = stripHtml(entries.map(messageOf).join(" "));
			if (text) return text;
		}
	}
	if (httpStatus === 0 && message) return message;
	return fallback;
}

/**
 * useFrappePostCall plus the plumbing every portal call site needs: unwraps
 * Frappe's `{message}` envelope, restarts the session timer on success,
 * reloads the page on a 403 (see SessionProvider), and shows any other
 * failure as an error toast. Callers get a result instead of an exception,
 * so a fire-and-forget call can't leak an unhandled rejection.
 */
export function useBackendCall<T>(method: string, errorTitle: string) {
	const { call, loading } = useFrappePostCall<FrappeEnvelope<T>>(method);
	const { recordActivity, reportForbidden } = useSession();
	const showToast = useToasts();

	const run = useCallback(
		async (params: Record<string, unknown> = {}): Promise<BackendResult<T>> => {
			try {
				const envelope = await call(params);
				recordActivity();
				return { ok: true, data: envelope.message };
			} catch (error) {
				if (readFailure(error).httpStatus === 403) {
					reportForbidden();
				} else {
					showToast({ kind: "error", title: getErrorMessage(error, errorTitle) });
				}
				return { ok: false };
			}
		},
		[call, errorTitle, recordActivity, reportForbidden, showToast],
	);

	return { call: run, loading };
}
