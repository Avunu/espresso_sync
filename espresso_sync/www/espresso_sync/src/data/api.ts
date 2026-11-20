// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type {
	ConnectionDetail,
	Direction,
	Link,
	Shot,
	StatusRow,
	SyncState,
} from "../../../../public/js/portal/types.ts";

/**
 * The portal's own endpoints (espresso_sync/api/connection.py, logs.py, links.py) and
 * what each answers with. Every one is for System Managers only; none answers with a
 * secret. The shapes shared with the pure modules are declared in
 * public/js/portal/types.ts and passed on from here.
 */

export type {
	Check,
	ConnectionDetail,
	Direction,
	LastFailure,
	Link,
	Shot,
	ShotOption,
	StatusProblem,
	StatusRow,
	SyncState,
} from "../../../../public/js/portal/types.ts";

export const CONNECTION = "Espresso Sync Connection";
export const PULL_LOG = "Espresso Sync Pull Log";
export const SYNC_ID = "Espresso Sync ID";

/** The dotted paths of the endpoints. Those under a `// GET` are read with
 * useFrappeGetCall, the others are POST-only and go through useBackendCall. */
export const METHODS = {
	// GET
	listStatus: "espresso_sync.api.connection.list_status",
	getConnection: "espresso_sync.api.connection.get_connection",
	cronPreview: "espresso_sync.api.connection.cron_preview",
	shotOptions: "espresso_sync.api.connection.shot_options",
	deleteImpact: "espresso_sync.api.connection.delete_impact",
	failureGroups: "espresso_sync.api.logs.failure_groups",
	activity: "espresso_sync.api.logs.activity",
	getRetention: "espresso_sync.api.logs.get_retention",
	listLinks: "espresso_sync.api.links.list_links",
	listDoctypes: "espresso_sync.api.schema.list_doctypes",
	// POST
	createConnection: "espresso_sync.api.connection.create_connection",
	saveConnection: "espresso_sync.api.connection.save_connection",
	syncNow: "espresso_sync.api.connection.sync_now",
	resync: "espresso_sync.api.connection.resync",
	setEnabled: "espresso_sync.api.connection.set_enabled",
	checkConnection: "espresso_sync.api.connection.check_connection",
	saveShot: "espresso_sync.api.connection.save_shot",
	removeShot: "espresso_sync.api.connection.remove_shot",
	moveShot: "espresso_sync.api.connection.move_shot",
	resetShot: "espresso_sync.api.connection.reset_shot",
	deleteConnection: "espresso_sync.api.connection.delete_connection",
	setRetention: "espresso_sync.api.logs.set_retention",
	clearLogs: "espresso_sync.api.logs.clear_logs",
	addLink: "espresso_sync.api.links.add_link",
	updateLink: "espresso_sync.api.links.update_link",
	forgetLink: "espresso_sync.api.links.forget_link",
	deleteLink: "espresso_sync.api.links.delete_link",
} as const;

/** `list_status`: the Connections (or the one asked for), and the server's time, which
 * every "ago" and every health is reckoned from. */
export interface StatusList {
	now: string;
	connections: StatusRow[];
}

/** `ConnectionDetail.auth_hints`: what the Connection's first API Spec with a usable
 * hint suggests. `api_key` is null for a Basic suggestion. */
export interface AuthHints {
	spec: string;
	scheme: string | null;
	note: string | null;
	auth_type: string | null;
	api_key: string | null;
}

function text(value: unknown): string | null {
	return typeof value === "string" && value ? value : null;
}

/** The auth hints of a Connection, read (not asserted) off its `auth_hints`. */
export function authHintsOf(detail: ConnectionDetail): AuthHints | null {
	const hints = detail.auth_hints;
	const spec = text(hints?.["spec"]);
	if (!hints || !spec) return null;
	return {
		spec,
		scheme: text(hints["scheme"]),
		note: text(hints["note"]),
		auth_type: text(hints["auth_type"]),
		api_key: text(hints["api_key"]),
	};
}

/** How the test request was answered: below 400, 401 or 403, another 4xx (a 429
 * included), 5xx, or not at all. */
export type CheckVerdict = "ok" | "auth" | "reachable" | "error" | "unreachable";

/** `check_connection`. `status` and `reason` are null, and `error` set, only when the
 * verdict is `unreachable`. Limited to 10 calls a minute. */
export interface CheckResult {
	ok: boolean;
	verdict: CheckVerdict;
	status: number | null;
	reason: string | null;
	elapsed_ms: number;
	host: string;
	credentials_sent: boolean;
	error: string | null;
}

/** `cron_preview`: the next times of a rule, none for an invalid one. */
export interface CronPreview {
	valid: boolean;
	next: string[];
}

/** `save_shot`, `remove_shot`, `move_shot`: the shots as saved, and the Connection's new
 * `modified`, which a Settings save after it must send. */
export interface ShotsAnswer {
	modified: string;
	shots: Shot[];
}

/** `reset_shot`: it leaves the Connection's `modified` alone. */
export interface ResetShotAnswer {
	shots: Shot[];
}

/** What `save_shot` takes as `shot`; `dt` is read only for a new one. */
export interface ShotInput {
	dt: string;
	do_import: 0 | 1;
	import_transform: string | null;
	do_export: 0 | 1;
	export_transform: string | null;
	update_transform: string | null;
	follow_up_transform: string | null;
}

/** `delete_impact`: what a delete removes, and what refuses it (`specs`, a `state`
 * other than idle). */
export interface DeleteImpact {
	specs: string[];
	transforms: number;
	logs: number;
	links: number;
	state: SyncState;
}

/** `delete_connection`, `delete_link`. */
export interface Deleted {
	deleted: true;
}

/** One group of `failure_groups`: the failures of one Connection, error code, transform,
 * DocType and direction. `code` is "unknown" for an entry with no diagnostic; `message`
 * is that of the newest entry, `latest_log`. */
export interface FailureGroup {
	connection: string;
	code: string;
	message: string;
	doctype: string | null;
	direction: Direction | null;
	transform: string | null;
	count: number;
	latest: string;
	latest_log: string;
}

/** `failure_groups`, most frequent first. `truncated`: there were more failures than were read. */
export interface FailureGroups {
	groups: FailureGroup[];
	truncated: boolean;
}

/** One day of `activity` (`YYYY-MM-DD`); the answer is oldest first, today last. */
export interface ActivityDay {
	date: string;
	imported: number;
	exported: number;
	failed: number;
}

/** `get_retention`, `set_retention`: how many days a Pull Log entry is kept. */
export interface Retention {
	days: number;
}

/** All `clear_logs` can filter by: not a period's start, a document or an error code. */
export interface ClearLogsFilters {
	sync_status?: "Success" | "Failure";
	sync_direction?: Direction;
	sync_doctype?: string;
	transform?: string;
	/** A datetime: only the entries logged before it. */
	before?: string;
}

/** `clear_logs`. */
export interface ClearLogsAnswer {
	deleted: number;
}

/** `list_links`: a page of the Connection's links, how many match in all, and the
 * DocTypes it has links of (not narrowed by the filters). */
export interface LinkList {
	rows: Link[];
	total: number;
	doctypes: string[];
}

/** The Pull Log columns the Sync log lists (through the REST API): never the payloads. */
export const PULL_LOG_FIELDS = [
	"name",
	"creation",
	"sync_connection",
	"sync_doctype",
	"sync_doc",
	"sync_direction",
	"sync_status",
	"transform",
	"request_type",
	"url",
	"diagnostics",
] as const;

/** A Pull Log entry as listed. `sync_doc` is empty for the entry of a request;
 * `diagnostics` is JSON, read with `lastError`. */
export interface PullLogRow {
	name: string;
	creation: string;
	sync_connection: string | null;
	sync_doctype: string | null;
	sync_doc: string | null;
	sync_direction: Direction | null;
	sync_status: "Success" | "Failure" | null;
	transform: string | null;
	request_type: string | null;
	url: string | null;
	diagnostics: unknown;
}
