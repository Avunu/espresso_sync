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
export type SecretChange = {
    kind: "keep";
} | {
    kind: "set";
    value: string;
} | {
    kind: "remove";
};
/** The form's starting values for a saved Connection. */
export declare function draftOf(detail: ConnectionDetail): ConnectionDraft;
/** The host of an http(s) URL as an Allowed Host is written: `shop.example.com`,
 * or `localhost:8080` with a port that is not the scheme's own. "" when the text
 * is not such a URL. */
export declare function hostOf(url: string): string;
/** What is wrong with the draft, by field; empty when it can be saved. The
 * server checks the same again, and more (a valid cron rule). */
export declare function connectionErrors(draft: ConnectionDraft): Partial<Record<keyof ConnectionDraft, string>>;
/** What a save sends. Never the shots (they have endpoints that hold the sync
 * lock) and never Enabled (a toggle of its own). `modified` is the timestamp
 * the draft was read at, so a save over somebody else's is refused. */
export declare function connectionPayload(draft: ConnectionDraft, secret: SecretChange, modified: string): Record<string, unknown>;
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
export declare function shotErrors(shot: ShotDraft): Partial<Record<keyof ShotDraft, string>>;
/** The transforms a shot of `dt` can use in one direction: the Active ones
 * first, then the Drafts (which the modal lists disabled), each by name. */
export declare function optionsFor(options: ShotOption[], dt: string, direction: Direction): ShotOption[];
