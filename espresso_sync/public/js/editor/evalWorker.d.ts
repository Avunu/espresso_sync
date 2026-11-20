export interface EvalLimits {
    /** jsonata's own timeout, checked between evaluation steps. */
    timeoutMs: number;
    /** jsonata's maximum evaluation depth (recursion). */
    maxDepth: number;
}
/** transform/engine.py's TIMEOUT_MS and MAX_DEPTH. */
export declare const DEFAULT_LIMITS: Readonly<EvalLimits>;
/** The functions transform/engine.py gives an expression besides JSONata's own. */
export declare const APP_FUNCTIONS: readonly ["syncId", "localName", "getValue", "frappeDate", "frappeDatetime", "frappeCheck"];
/** A call of one of the app's functions, as resolve_functions takes it: named without the `$`. */
export interface FunctionCall {
    function: string;
    args: unknown[];
}
/** resolve_functions' answer to a call: its value, or the error it raised and its code. */
export interface FunctionResult {
    value?: unknown;
    error?: string;
    code?: string;
}
/** The server's answers, by `callKey`. */
export type FunctionResults = Record<string, FunctionResult>;
/** What identifies a call: the function and its arguments, as JSON. */
export declare function callKey(call: FunctionCall): string;
export interface EvalRequest {
    id: number;
    expression: string;
    input: unknown;
    bindings?: Record<string, unknown>;
    limits?: Partial<EvalLimits>;
    /** With this, the app's functions are bound and answered from it (see the module's comment). */
    functions?: FunctionResults;
}
export interface EvalError {
    /**
     * jsonata's code (`S0201`, `T2001`, `D1012`), or one of the client's:
     * `ES_DEADLINE`, `ES_SUPERSEDED`, `ES_ABORTED` or `ES_WORKER`.
     */
    code: string;
    message: string;
    position?: number;
    token?: string;
}
export type EvalResponse = {
    id: number;
    ok: true;
    /** The result as JSON would carry it; `null` when the expression produced nothing. */
    value: unknown;
    /** False when the expression produced nothing (`undefined`), which JSON can't say. */
    defined: boolean;
    elapsedMs: number;
    /** The calls of the app's functions `functions` had no answer for. */
    calls?: FunctionCall[];
} | {
    id: number;
    ok: false;
    error: EvalError;
    elapsedMs: number;
    calls?: FunctionCall[];
};
/** A jsonata function value, which can't cross to the page: shown by this text instead. */
export declare const FUNCTION_PLACEHOLDER = "[function]";
/**
 * A result as plain JSON data: sequences become arrays, functions the
 * placeholder. What the page receives is then exactly what the server would
 * write, and structured cloning can't fail on it.
 */
export declare function toPlain(value: unknown): unknown;
/** jsonata throws plain objects, not Errors; this reads either. */
export declare function toEvalError(error: unknown): EvalError;
/** What RE2 refuses in a pattern that RegExp takes (a lookaround, a backreference): RE2's message for it. */
export declare function re2Refusal(source: string): string | undefined;
/** Evaluate one request. Never throws: a failure is the response. */
export declare function evaluate(request: EvalRequest, now?: () => number): Promise<EvalResponse>;
/** What `serve` needs of a worker's global scope. */
export interface WorkerScopeLike {
    addEventListener(type: "message", listener: (event: MessageEvent) => void): void;
    postMessage(message: unknown): void;
}
/** The worker side: answer every request posted to `scope`. */
export declare function serve(scope: WorkerScopeLike): void;
/** What `EvalClient` needs of a Worker. */
export interface WorkerLike {
    postMessage(message: unknown): void;
    terminate(): void;
    addEventListener(type: "message", listener: (event: MessageEvent) => void): void;
    addEventListener(type: "error", listener: (event: ErrorEvent) => void): void;
}
export interface EvalClientOptions {
    /** How far past the request's `timeoutMs` the client waits before it kills the worker. */
    graceMs?: number;
}
/** A request as the page makes it: the client numbers it, and `key` names what it is for. */
export interface EvalCall extends Omit<EvalRequest, "id"> {
    /**
     * What the request is for (a rule's pointer, say). A newer request with
     * the same key replaces one still waiting its turn, which then resolves
     * with `ES_SUPERSEDED`: a burst of keystrokes evaluates only the last.
     */
    key?: string;
}
/**
 * The page's side: sends requests to a worker and resolves each with its
 * response. Its promises never reject.
 *
 * The worker gets one request at a time; the rest wait here, in order. A
 * request's deadline (its `timeoutMs` plus `graceMs`) starts when it is sent,
 * so time spent waiting behind others never counts against it. A request that
 * misses its deadline resolves with `ES_DEADLINE`, the worker is replaced, and
 * the requests still waiting go to the new one.
 */
export declare class EvalClient {
    private readonly createWorker;
    private readonly graceMs;
    private worker;
    /** The request the worker is on. */
    private current;
    /** The requests waiting their turn, oldest first. */
    private readonly queue;
    private nextId;
    constructor(createWorker: () => WorkerLike, options?: EvalClientOptions);
    evaluate(call: EvalCall): Promise<EvalResponse>;
    /** Stop the worker; anything still waiting resolves as aborted. */
    dispose(): void;
    /** Send the next waiting request, if the worker is free. */
    private pump;
    private ensureWorker;
    private settle;
    private fail;
    private expire;
    /** Fail the current request with `code` and replace the worker; those waiting go to the new one. */
    private abandon;
    private stopWorker;
}
/** How many times `evaluateAll` asks the server: a function's answer can be another's argument. */
export declare const MAX_FUNCTION_ROUNDS = 5;
/** The most calls one resolve_functions request takes (api/transform.py's MAX_CALLS). */
export declare const MAX_CALLS = 500;
/**
 * Evaluate every call, with the app's functions answered by the server: the
 * calls nothing in `results` answers are sent to `resolve` (one
 * resolve_functions request a round, for every `MAX_CALLS` of them), their
 * answers are added to `results` (the page's cache, kept between evaluations),
 * and the requests that made them are evaluated again. When `resolve` fails (it
 * answers undefined) or after `MAX_FUNCTION_ROUNDS` rounds, the last responses
 * stand. Once `signal` is aborted (a newer evaluation replaces this one), it
 * asks nothing more and starts no new round, so it can't take the place of the
 * newer one's requests.
 */
export declare function evaluateAll(client: Pick<EvalClient, "evaluate">, calls: readonly EvalCall[], results: FunctionResults, resolve: (calls: FunctionCall[]) => Promise<FunctionResult[] | undefined>, signal: AbortSignal): Promise<EvalResponse[]>;
