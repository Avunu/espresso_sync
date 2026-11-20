// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * The Connection's Settings form and its shots, without the form: what the
 * fields start as, what is wrong with them, and what is sent.
 *
 * The secret is write-only. The page never has it, so a save says what to do
 * with the stored one: keep it (the field is left out), set it, or remove it
 * (Frappe drops a Password that is saved empty).
 */

import type { ConnectionDetail, Direction, ShotOption } from "./types.ts";

/** The editable fields of a Connection, as the inputs hold them. */
export interface ConnectionDraft {
	server_url: string;
	allowed_host: string;
	auth_type: string;
	api_key: string;
	sync_frequency: string;
	cron_rule: string;
	api_rate_limit: string;
}

export type SecretChange = { kind: "keep" } | { kind: "set"; value: string } | { kind: "remove" };

/** The form's starting values for a saved Connection. */
export function draftOf(detail: ConnectionDetail): ConnectionDraft {
	return {
		server_url: detail.server_url ?? "",
		allowed_host: detail.allowed_host ?? "",
		auth_type: detail.auth_type || "Header-based",
		api_key: detail.api_key ?? "",
		sync_frequency: detail.sync_frequency || "Manual",
		cron_rule: detail.cron_rule ?? "",
		api_rate_limit: detail.api_rate_limit ? String(detail.api_rate_limit) : "",
	};
}

function httpUrl(text: string): URL | undefined {
	try {
		const url = new URL(text.trim());
		return (url.protocol === "http:" || url.protocol === "https:") && url.hostname ? url : undefined;
	} catch {
		return undefined;
	}
}

/** The host of an http(s) URL as an Allowed Host is written: `shop.example.com`,
 * or `localhost:8080` with a port that is not the scheme's own. "" when the text
 * is not such a URL. */
export function hostOf(url: string): string {
	return httpUrl(url)?.host ?? "";
}

/** Whether `allowed` ("host" or "host:port") is where `url` goes: the same host,
 * and the same port, which is the scheme's own when the allowed host names none. */
function hostAllows(allowed: string, url: URL): boolean | "invalid" {
	if (/[/\\@?#\s]/.test(allowed)) return "invalid";
	const target = httpUrl(`${url.protocol}//${allowed}/`);
	if (!target) return "invalid";
	const dotless = (host: string) => host.replace(/\.$/, "");
	return dotless(target.hostname) === dotless(url.hostname) && target.port === url.port;
}

/** What is wrong with the draft, by field; empty when it can be saved. The
 * server checks the same again, and more (a valid cron rule). */
export function connectionErrors(draft: ConnectionDraft): Partial<Record<keyof ConnectionDraft, string>> {
	const errors: Partial<Record<keyof ConnectionDraft, string>> = {};
	const url = httpUrl(draft.server_url);
	if (!draft.server_url.trim()) errors.server_url = "A server URL is needed.";
	else if (!url) errors.server_url = "Give an http or https URL, such as https://shop.example.com.";
	const allowed = draft.allowed_host.trim();
	if (allowed && url) {
		const allows = hostAllows(allowed, url);
		if (allows === "invalid") {
			errors.allowed_host = "Give a host name, or host:port, without a scheme or a path.";
		} else if (!allows) {
			errors.allowed_host = `The server URL's host is ${url.host}, not ${allowed}.`;
		}
	}
	if (draft.sync_frequency === "Cron" && !draft.cron_rule.trim()) {
		errors.cron_rule = "A cron rule is needed when the frequency is Cron.";
	}
	const limit = draft.api_rate_limit.trim();
	if (limit && !/^\d+$/.test(limit)) {
		errors.api_rate_limit = "Give a whole number, 0 or more. 0 or empty is no limit.";
	}
	return errors;
}

/** What a save sends. Never the shots (they have endpoints that hold the sync
 * lock) and never Enabled (a toggle of its own). `modified` is the timestamp
 * the draft was read at, so a save over somebody else's is refused. */
export function connectionPayload(
	draft: ConnectionDraft,
	secret: SecretChange,
	modified: string,
): Record<string, unknown> {
	const text = (value: string) => value.trim() || null;
	const limit = draft.api_rate_limit.trim();
	const payload: Record<string, unknown> = {
		server_url: text(draft.server_url),
		allowed_host: text(draft.allowed_host),
		auth_type: text(draft.auth_type),
		api_key: text(draft.api_key),
		sync_frequency: text(draft.sync_frequency),
		cron_rule: text(draft.cron_rule),
		api_rate_limit: limit ? Number(limit) : null,
		modified,
	};
	if (secret.kind === "set") payload["api_secret"] = secret.value;
	if (secret.kind === "remove") payload["api_secret"] = "";
	return payload;
}

/** One shot, as its modal holds it. */
export interface ShotDraft {
	dt: string;
	do_import: 0 | 1;
	import_transform: string;
	do_export: 0 | 1;
	export_transform: string;
	update_transform: string;
	follow_up_transform: string;
}

/** What is wrong with a shot, by field. A shot that neither imports nor exports
 * is fine: it only adds the Sync tab to its DocType. */
export function shotErrors(shot: ShotDraft): Partial<Record<keyof ShotDraft, string>> {
	const errors: Partial<Record<keyof ShotDraft, string>> = {};
	if (!shot.dt) errors.dt = "Choose a DocType.";
	if (shot.do_import && !shot.import_transform) {
		errors.import_transform = "An import transform is needed to import.";
	}
	if (shot.do_export && !shot.export_transform) {
		errors.export_transform = "A create transform is needed to export.";
	}
	return errors;
}

/** The transforms a shot of `dt` can use in one direction: the Active ones
 * first, then the Drafts (which the modal lists disabled), each by name. */
export function optionsFor(options: ShotOption[], dt: string, direction: Direction): ShotOption[] {
	return options
		.filter((option) => option.document_type === dt && option.direction === direction)
		.sort(
			(a, b) => Number(a.status !== "Active") - Number(b.status !== "Active") || a.name.localeCompare(b.name),
		);
}
