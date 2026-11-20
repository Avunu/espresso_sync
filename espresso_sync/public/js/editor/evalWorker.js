// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
/**
 * JSONata evaluation off the main thread, with a deadline.
 *
 * The editor re-evaluates rules on every keystroke, against data it didn't
 * write. An expression can loop or backtrack for ever, so evaluation runs in a
 * Web Worker and is bounded twice:
 *
 * 1. Inside the worker, jsonata's own guardrails stop a runaway evaluation
 *    between steps: `timeoutMs` (D1012) and `maxDepth` (D1011). These are the
 *    limits the server's jsonata-python timebox uses (transform/engine.py), so
 *    an expression stopped on the server is stopped here, and only then.
 * 2. Outside it, `EvalClient` sends the worker one request at a time and gives
 *    each a deadline a little past `timeoutMs`, counted from when it is sent.
 *    Something the guardrails can't interrupt (a catastrophic regular
 *    expression, a giant result) runs past it, and the client then terminates
 *    the worker and starts a new one for the requests still waiting.
 *
 * `evaluate` and `serve` are the worker's side and `EvalClient` the page's; all
 * three are plain functions of their inputs, so the tests run them in Node with
 * a stand-in for the Worker. The page's worker entry
 * (public/js/espresso-sync-eval.bundle.js) is two lines: import `serve` and
 * call it on `self`.
 *
 * The app's own functions (`$syncId`, `$getValue`, … in transform/engine.py)
 * read the site, so only the server can answer them. A request that carries
 * `functions`, the server's answers so far, binds them: a call answered there
 * gives that answer, and any other gives nothing and is listed in the
 * response's `calls`. `evaluateAll` sends those to the server
 * (resolve_functions) and evaluates again, until nothing new is called.
 *
 * The server runs regular expressions on RE2, which refuses a lookaround or a
 * backreference; a pattern with one fails here too, with RE2's message, rather
 * than working in the preview only.
 */
import jsonata from "jsonata";
/** transform/engine.py's TIMEOUT_MS and MAX_DEPTH. */
export const DEFAULT_LIMITS = { timeoutMs: 5000, maxDepth: 200 };
/** The functions transform/engine.py gives an expression besides JSONata's own. */
export const APP_FUNCTIONS = [
    "syncId",
    "localName",
    "getValue",
    "frappeDate",
    "frappeDatetime",
    "frappeCheck",
];
/** What identifies a call: the function and its arguments, as JSON. */
export function callKey(call) {
    return JSON.stringify([call.function, call.args]);
}
/** A jsonata function value, which can't cross to the page: shown by this text instead. */
export const FUNCTION_PLACEHOLDER = "[function]";
function isJsonataFunction(value) {
    if (typeof value === "function")
        return true;
    if (typeof value !== "object" || value === null)
        return false;
    const record = value;
    return record["_jsonata_function"] === true || record["_jsonata_lambda"] === true;
}
/**
 * A result as plain JSON data: sequences become arrays, functions the
 * placeholder. What the page receives is then exactly what the server would
 * write, and structured cloning can't fail on it.
 */
export function toPlain(value) {
    if (value === undefined)
        return null;
    const text = JSON.stringify(value, (_key, item) => isJsonataFunction(item) ? FUNCTION_PLACEHOLDER : item);
    return text === undefined ? null : JSON.parse(text);
}
/** jsonata throws plain objects, not Errors; this reads either. */
export function toEvalError(error) {
    const fields = typeof error === "object" && error !== null ? error : {};
    const { code, message, position, token } = fields;
    const result = {
        code: typeof code === "string" ? code : "ES_ERROR",
        message: typeof message === "string" ? message : String(error),
    };
    if (typeof position === "number")
        result.position = position;
    if (typeof token === "string")
        result.token = token;
    return result;
}
/**
 * The app's functions, answered from `results`. A value of null is nothing, as
 * a Python function's None is to jsonata-python; an error is thrown with
 * resolve_functions' code, so it reads as the server's `eval.<code>`. A call
 * with no answer gives nothing and is added to `unanswered`.
 */
function appFunctions(results, unanswered) {
    const bound = {};
    for (const name of APP_FUNCTIONS) {
        bound[name] = (...args) => {
            const call = { function: name, args: toPlain(args) };
            const key = callKey(call);
            const result = results[key];
            if (!result) {
                unanswered.set(key, call);
                return undefined;
            }
            if (result.error !== undefined) {
                throw Object.assign(new Error(result.error), { code: result.code ?? "error" });
            }
            return result.value ?? undefined;
        };
    }
    return bound;
}
/** What RE2 refuses in a pattern that RegExp takes (a lookaround, a backreference): RE2's message for it. */
export function re2Refusal(source) {
    let inClass = false;
    for (let at = 0; at < source.length; at += 1) {
        const char = source[at];
        if (char === "\\") {
            const escaped = source[at + 1] ?? "";
            if (/[1-9k]/.test(escaped))
                return `invalid escape sequence: \\${escaped}`;
            at += 1;
        }
        else if (inClass) {
            inClass = char !== "]";
        }
        else if (char === "[") {
            inClass = true;
        }
        else if (char === "(") {
            const lookaround = ["(?=", "(?!", "(?<=", "(?<!"].find((operator) => source.startsWith(operator, at));
            if (lookaround)
                return `invalid perl operator: ${lookaround}`;
        }
    }
    return undefined;
}
/** jsonata's regular expressions, refused where the server's RE2 refuses them. */
class Re2Pattern extends RegExp {
    constructor(pattern, flags) {
        const refusal = re2Refusal(typeof pattern === "string" ? pattern : pattern.source);
        // thrown as the server's engine.evaluate raises it: not a jsonata error, so `eval.error`
        if (refusal)
            throw Object.assign(new Error(refusal), { code: "error" });
        super(pattern, flags);
    }
}
/** Evaluate one request. Never throws: a failure is the response. */
export async function evaluate(request, now = () => performance.now()) {
    const started = now();
    const limits = { ...DEFAULT_LIMITS, ...request.limits };
    const unanswered = new Map();
    const bindings = request.functions
        ? { ...appFunctions(request.functions, unanswered), ...request.bindings }
        : request.bindings;
    const calls = () => unanswered.size > 0 ? { calls: [...unanswered.values()] } : {};
    try {
        const expression = jsonata(request.expression, {
            timeout: limits.timeoutMs,
            stack: limits.maxDepth,
            // jsonata only constructs it (`new RegexEngine(regex)`); its typings ask for RegExp's call signature too
            RegexEngine: Re2Pattern,
        });
        const result = await expression.evaluate(request.input, bindings);
        return {
            id: request.id,
            ok: true,
            value: toPlain(result),
            defined: result !== undefined,
            elapsedMs: now() - started,
            ...calls(),
        };
    }
    catch (error) {
        return { id: request.id, ok: false, error: toEvalError(error), elapsedMs: now() - started, ...calls() };
    }
}
/** The worker side: answer every request posted to `scope`. */
export function serve(scope) {
    scope.addEventListener("message", (event) => {
        void evaluate(event.data).then((response) => scope.postMessage(response));
    });
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
export class EvalClient {
    createWorker;
    graceMs;
    worker;
    /** The request the worker is on. */
    current;
    /** The requests waiting their turn, oldest first. */
    queue = [];
    nextId = 1;
    constructor(createWorker, options = {}) {
        this.createWorker = createWorker;
        this.graceMs = options.graceMs ?? 500;
    }
    evaluate(call) {
        const { key, ...request } = call;
        const id = this.nextId++;
        return new Promise((resolve) => {
            if (key !== undefined) {
                const index = this.queue.findIndex((job) => job.key === key);
                const [older] = index === -1 ? [] : this.queue.splice(index, 1);
                if (older)
                    this.fail(older, "ES_SUPERSEDED", "Replaced by a newer evaluation of the same expression");
            }
            this.queue.push({ id, key, request: { ...request, id }, resolve, since: Date.now() });
            this.pump();
        });
    }
    /** Stop the worker; anything still waiting resolves as aborted. */
    dispose() {
        this.stopWorker();
        const message = "The expression engine was shut down";
        if (this.current)
            this.fail(this.current, "ES_ABORTED", message);
        this.current = undefined;
        for (const job of this.queue.splice(0))
            this.fail(job, "ES_ABORTED", message);
    }
    /** Send the next waiting request, if the worker is free. */
    pump() {
        if (this.current)
            return;
        const job = this.queue.shift();
        if (!job)
            return;
        const worker = this.ensureWorker();
        const timeoutMs = job.request.limits?.timeoutMs ?? DEFAULT_LIMITS.timeoutMs;
        this.current = job;
        job.since = Date.now();
        job.timer = setTimeout(() => this.expire(job), timeoutMs + this.graceMs);
        worker.postMessage(job.request);
    }
    ensureWorker() {
        if (this.worker)
            return this.worker;
        const worker = this.createWorker();
        worker.addEventListener("message", (event) => {
            // A terminated worker can still deliver what it had queued: only the current one counts.
            if (this.worker === worker)
                this.settle(event.data);
        });
        worker.addEventListener("error", (event) => {
            event.preventDefault();
            if (this.worker === worker)
                this.abandon("ES_WORKER", `The expression engine failed: ${event.message}`);
        });
        this.worker = worker;
        return worker;
    }
    settle(response) {
        const job = this.current;
        if (job?.id !== response.id)
            return; // answered after its deadline: already settled
        this.current = undefined;
        clearTimeout(job.timer);
        job.resolve(response);
        this.pump();
    }
    fail(job, code, message) {
        clearTimeout(job.timer);
        job.resolve({ id: job.id, ok: false, error: { code, message }, elapsedMs: Date.now() - job.since });
    }
    expire(job) {
        if (this.current !== job)
            return;
        this.abandon("ES_DEADLINE", "The expression took too long and was stopped");
    }
    /** Fail the current request with `code` and replace the worker; those waiting go to the new one. */
    abandon(code, message) {
        this.stopWorker();
        const job = this.current;
        this.current = undefined;
        if (job)
            this.fail(job, code, message);
        this.pump();
    }
    stopWorker() {
        this.worker?.terminate();
        this.worker = undefined;
    }
}
/** How many times `evaluateAll` asks the server: a function's answer can be another's argument. */
export const MAX_FUNCTION_ROUNDS = 5;
/** The most calls one resolve_functions request takes (api/transform.py's MAX_CALLS). */
export const MAX_CALLS = 500;
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
export async function evaluateAll(client, calls, results, resolve, signal) {
    const responses = [];
    // one round: evaluate `pending` (indexes into `calls`), then ask for what they called
    const round = async (pending, number) => {
        if (signal.aborted)
            return;
        const answered = await Promise.all(pending.map((index) => client.evaluate({ ...calls[index], functions: results })));
        const unanswered = new Map();
        const again = [];
        for (const [position, response] of answered.entries()) {
            const index = pending[position];
            responses[index] = response;
            const missing = (response.calls ?? []).filter((call) => !results[callKey(call)]);
            if (missing.length === 0)
                continue;
            again.push(index);
            for (const call of missing)
                unanswered.set(callKey(call), call);
        }
        if (unanswered.size === 0 || number >= MAX_FUNCTION_ROUNDS)
            return;
        if (signal.aborted)
            return;
        const asked = [...unanswered.values()];
        const chunks = [];
        for (let start = 0; start < asked.length; start += MAX_CALLS)
            chunks.push(asked.slice(start, start + MAX_CALLS));
        const answers = await Promise.all(chunks.map((chunk) => resolve(chunk)));
        if (answers.some((answer) => !answer))
            return;
        for (const [index, chunk] of chunks.entries()) {
            for (const [position, call] of chunk.entries()) {
                results[callKey(call)] = answers[index]?.[position] ?? { error: "No answer", code: "error" };
            }
        }
        await round(again, number + 1);
    };
    await round(calls.map((_call, index) => index), 1);
    return responses;
}
