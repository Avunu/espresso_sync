import { type EvalError } from "./evalWorker.ts";
/** One input field (or pattern of fields) the expression reads. */
export interface ReadRef {
    pointer: string;
    segments: readonly string[];
    /** A `*` or `**` segment: the read covers whatever matches. */
    wildcard: boolean;
}
export type DynamicReason = "lookup" | "eval" | "lambda" | "transform";
/** A read that can't be resolved without evaluating the expression. */
export interface DynamicRead {
    reason: DynamicReason;
    /** Where in the expression, as jsonata's parser counts (the end of the token). */
    position: number | undefined;
    /** The pointer of the object read from, when that much resolves (`$lookup(customer, $k)`). */
    base?: string;
}
export interface Reads {
    reads: ReadRef[];
    dynamic: DynamicRead[];
}
export type ReadsResult = ({
    ok: true;
} & Reads) | {
    ok: false;
    error: EvalError;
};
export interface ReadsOptions {
    /**
     * Where the expression is evaluated, as path segments from the input root:
     * a rule inside a collection reads relative to the collection's items.
     * `$` is this context; `$$` is always the input root.
     */
    context?: readonly string[];
}
/** The reads of an already-parsed expression (`jsonata(text).ast()`). */
export declare function readsOfAst(ast: unknown, options?: ReadsOptions): Reads;
/** The reads of an expression's source text, or the parse error that stopped it. */
export declare function readsOf(expression: string, options?: ReadsOptions): ReadsResult;
