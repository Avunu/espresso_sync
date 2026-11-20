/**
 * The shapes the portal's endpoints answer with (`espresso_sync.api.connection`
 * and `espresso_sync.api.links`), declared once for the pure modules here and
 * for the page. Datetimes are the server's naive site-time strings; checks are
 * `0 | 1`.
 */
export type Check = 0 | 1;
export type SyncState = "idle" | "queued" | "running";
export type Direction = "Import" | "Export";
/** A shot whose transform no longer fits it, as `list_status` reports it. */
export interface StatusProblem {
    code: string;
    message: string;
    doctype: string | null;
    transform: string | null;
}
/** The newest failed Pull Log entry of a Connection. */
export interface LastFailure {
    name: string;
    creation: string;
    code: string;
    message: string;
}
/** One Connection in `list_status`: what the health of it is derived from. */
export interface StatusRow {
    name: string;
    enabled: Check;
    server_url: string | null;
    sync_frequency: string | null;
    cron_rule: string | null;
    last_pull: string | null;
    last_sync_attempt: string | null;
    state: SyncState;
    /** The next cron time, for a Cron schedule only. */
    next_run: string | null;
    shots: number;
    problems: StatusProblem[];
    failures_last_run: number;
    successes_last_run: number;
    failures_24h: number;
    successes_24h: number;
    last_failure: LastFailure | null;
}
/** One row of a Connection's shots: a DocType and the transforms it syncs with. */
export interface Shot {
    name: string;
    idx: number;
    dt: string;
    do_import: Check;
    import_transform: string | null;
    last_import: string | null;
    do_export: Check;
    export_transform: string | null;
    update_transform: string | null;
    follow_up_transform: string | null;
    last_export: string | null;
}
/** What `get_connection` answers: never the secret, only whether one is stored. */
export interface ConnectionDetail {
    name: string;
    modified: string;
    enabled: Check;
    server_url: string | null;
    allowed_host: string | null;
    auth_type: string | null;
    api_key: string | null;
    sync_frequency: string | null;
    cron_rule: string | null;
    api_rate_limit: number | null;
    last_pull: string | null;
    last_sync_attempt: string | null;
    has_secret: boolean;
    shots: Shot[];
    setup: {
        specs: number;
        transforms: number;
        active_transforms: number;
    };
    /** The authentication the Connection's first API Spec with hints suggests. */
    auth_hints: Record<string, unknown> | null;
}
/** A transform a shot of the Connection could use, Drafts included. */
export interface ShotOption {
    name: string;
    direction: Direction;
    document_type: string;
    status: "Draft" | "Active";
    api_spec: string;
}
/** An Espresso Sync ID row: one document's link to its object in the API. */
export interface Link {
    name: string;
    parenttype: string;
    parent: string;
    external_id: string | null;
    last_synced_modified: string | null;
    external_modified: string | null;
    dont_sync: Check;
}
