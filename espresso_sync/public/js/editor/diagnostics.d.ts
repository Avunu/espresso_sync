/**
 * The diagnostic shape the editor and the server share, and the mapping from a
 * JSON Schema validator's errors to the rule that caused them.
 *
 * A diagnostic belongs to a rule (`rule`, the rule's pointer, see pointer.ts)
 * so the editor can show it on the row of the field it is about; `path` is
 * where in the produced document it was found, array indexes included; and
 * `item` is which sample item produced it, when it came from evaluating one.
 * The server's validate_transform returns the same shape, with `origin`
 * "server", so its findings merge with the browser's (`mergeDiagnostics`).
 */
import type { ErrorObject } from "ajv";
import type { TreeNode } from "./schemaTree.ts";
export type Severity = "error" | "warning" | "info";
/** Where the check ran: in the browser, or on the server (validate_transform, a dry run). */
export type DiagnosticOrigin = "client" | "server";
export interface Diagnostic {
    /** The pointer of the rule it is about (or of the unmapped field, for a missing one). */
    rule: string;
    /** Where in the document: a pointer with array indexes. */
    path: string;
    severity: Severity;
    /** Stable and machine-readable: `schema.required`, `jsonata.S0201`, `eval.D1012`. */
    code: string;
    message: string;
    origin: DiagnosticOrigin;
    /** The index of the sample item the finding came from. */
    item?: number;
}
export interface FromAjvOptions {
    origin?: DiagnosticOrigin;
    item?: number;
    /** Every error's severity (a response checked in "Warn" mode is all warnings). */
    severity?: Severity;
    /** The pointers the transform has rules for: an error belongs to the nearest one at or above it. */
    rules?: Iterable<string>;
    /** The target's tree, to tell an array index from a key that happens to be digits. */
    tree?: TreeNode;
}
/**
 * A data path with array indexes (`/lines/0/qty`) as a rule pointer
 * (`/lines/qty`). With a tree, a segment is an index only where the tree has an
 * array; without one, any all-digit segment is taken for an index.
 */
export declare function stripIndexes(path: string, tree?: TreeNode): string;
/** The nearest pointer at or above `pointer` that has a rule; `pointer` itself when none does. */
export declare function nearestRule(pointer: string, rules: ReadonlySet<string>): string;
/** Diagnostics for a validator's errors, each attached to the rule it belongs to. */
export declare function fromAjvErrors(errors: readonly ErrorObject[] | null | undefined, options?: FromAjvOptions): Diagnostic[];
/** Errors first, then by rule, path and item, so a list reads top to bottom like the tree. */
export declare function sortDiagnostics(diagnostics: readonly Diagnostic[]): Diagnostic[];
/**
 * Replace one origin's diagnostics with a fresh set: a new server validation
 * replaces the last one's findings and keeps the browser's, and vice versa.
 * Duplicates are dropped.
 */
export declare function mergeDiagnostics(current: readonly Diagnostic[], fresh: readonly Diagnostic[], origin: DiagnosticOrigin): Diagnostic[];
