import type { StatusRow } from "./types.ts";
export type HealthKind = "healthy" | "failing" | "warning" | "running" | "queued" | "paused" | "never" | "unknown";
export interface Health {
    kind: HealthKind;
    /** The state in a word or two, shown beside the icon. */
    label: string;
    /** Why, when there is something to say. */
    reason: string | null;
}
/** The health of a Connection at `now`, the server's own time. */
export declare function deriveHealth(row: StatusRow, now: string): Health;
/** Whether somebody should look at the Connection: it is failing or warning. */
export declare function needsAttention(row: StatusRow, now: string): boolean;
/** The sort order of a health: the lower, the sooner it is worth a look. */
export declare function severityRank(kind: HealthKind): number;
