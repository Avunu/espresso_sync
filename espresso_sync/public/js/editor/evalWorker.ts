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
 *    between steps: `timeoutMs` (D1012), `maxDepth` (D1011) and `maxSequence`
 *    (D2015). These are the limits the server's jsonata-python `timebox` uses.
 * 2. Outside it, `EvalClient` gives each request a deadline a little past
 *    `timeoutMs`. Something the guardrails can't interrupt (a catastrophic
 *    regular expression, a giant result) runs past it, and the client then
 *    terminates the worker and starts a new one for the next request.
 *
 * `evaluate` and `serve` are the worker's side and `EvalClient` the page's; all
 * three are plain functions of their inputs, so the tests run them in Node with
 * a stand-in for the Worker. The page's worker entry is two lines: import
 * `serve` and call it on `self`.
 */

import jsonata from "jsonata";

export interface EvalLimits {
	/** jsonata's own timeout, checked between evaluation steps. */
	timeoutMs: number;
	/** jsonata's maximum evaluation depth (recursion). */
	maxDepth: number;
	/** The largest sequence an evaluation may build. */
	maxSequence: number;
}

export const DEFAULT_LIMITS: Readonly<EvalLimits> = { timeoutMs: 1000, maxDepth: 300, maxSequence: 100_000 };

export interface EvalRequest {
	id: number;
	expression: string;
	input: unknown;
	bindings?: Record<string, unknown>;
	limits?: Partial<EvalLimits>;
}

export interface EvalError {
	/** jsonata's code (`S0201`, `T2001`, `D1012`), or `ES_DEADLINE` / `ES_ABORTED` / `ES_WORKER` from the client. */
	code: string;
	message: string;
	position?: number;
	token?: string;
}

export type EvalResponse =
	| {
			id: number;
			ok: true;
			/** The result as JSON would carry it; `null` when the expression produced nothing. */
			value: unknown;
			/** False when the expression produced nothing (`undefined`), which JSON can't say. */
			defined: boolean;
			elapsedMs: number;
	  }
	| { id: number; ok: false; error: EvalError; elapsedMs: number };

/** A jsonata function value, which can't cross to the page: shown by this text instead. */
export const FUNCTION_PLACEHOLDER = "[function]";

function isJsonataFunction(value: unknown): boolean {
	if (typeof value === "function") return true;
	if (typeof value !== "object" || value === null) return false;
	const record = value as Record<string, unknown>;
	return record["_jsonata_function"] === true || record["_jsonata_lambda"] === true;
}

/**
 * A result as plain JSON data: sequences become arrays, functions the
 * placeholder. What the page receives is then exactly what the server would
 * write, and structured cloning can't fail on it.
 */
export function toPlain(value: unknown): unknown {
	if (value === undefined) return null;
	const text = JSON.stringify(value, (_key, item: unknown) =>
		isJsonataFunction(item) ? FUNCTION_PLACEHOLDER : item,
	);
	return text === undefined ? null : (JSON.parse(text) as unknown);
}

/** jsonata throws plain objects, not Errors; this reads either. */
export function toEvalError(error: unknown): EvalError {
	const fields = typeof error === "object" && error !== null ? (error as Record<string, unknown>) : {};
	const { code, message, position, token } = fields;
	const result: EvalError = {
		code: typeof code === "string" ? code : "ES_ERROR",
		message: typeof message === "string" ? message : String(error),
	};
	if (typeof position === "number") result.position = position;
	if (typeof token === "string") result.token = token;
	return result;
}

/** Evaluate one request. Never throws: a failure is the response. */
export async function evaluate(
	request: EvalRequest,
	now: () => number = () => performance.now(),
): Promise<EvalResponse> {
	const started = now();
	const limits = { ...DEFAULT_LIMITS, ...request.limits };
	try {
		const expression = jsonata(request.expression, {
			timeout: limits.timeoutMs,
			stack: limits.maxDepth,
			sequence: limits.maxSequence,
		});
		const result: unknown = await expression.evaluate(request.input, request.bindings);
		return {
			id: request.id,
			ok: true,
			value: toPlain(result),
			defined: result !== undefined,
			elapsedMs: now() - started,
		};
	} catch (error) {
		return { id: request.id, ok: false, error: toEvalError(error), elapsedMs: now() - started };
	}
}

/** What `serve` needs of a worker's global scope. */
export interface WorkerScopeLike {
	addEventListener(type: "message", listener: (event: MessageEvent) => void): void;
	postMessage(message: unknown): void;
}

/** The worker side: answer every request posted to `scope`. */
export function serve(scope: WorkerScopeLike): void {
	scope.addEventListener("message", (event) => {
		void evaluate(event.data as EvalRequest).then((response) => scope.postMessage(response));
	});
}

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

interface Pending {
	resolve: (response: EvalResponse) => void;
	timer: ReturnType<typeof setTimeout>;
	started: number;
}

/**
 * The page's side: sends requests to a worker and resolves each with its
 * response, or with an `ES_DEADLINE` error when the worker doesn't answer in
 * time (the worker is then replaced). Its promises never reject.
 */
export class EvalClient {
	private readonly createWorker: () => WorkerLike;
	private readonly graceMs: number;
	private worker: WorkerLike | undefined;
	private readonly pending = new Map<number, Pending>();
	private nextId = 1;

	constructor(createWorker: () => WorkerLike, options: EvalClientOptions = {}) {
		this.createWorker = createWorker;
		this.graceMs = options.graceMs ?? 500;
	}

	evaluate(request: Omit<EvalRequest, "id">): Promise<EvalResponse> {
		const id = this.nextId++;
		const timeoutMs = request.limits?.timeoutMs ?? DEFAULT_LIMITS.timeoutMs;
		const worker = this.ensureWorker();
		return new Promise<EvalResponse>((resolve) => {
			const timer = setTimeout(() => this.expire(id), timeoutMs + this.graceMs);
			this.pending.set(id, { resolve, timer, started: Date.now() });
			worker.postMessage({ ...request, id } satisfies EvalRequest);
		});
	}

	/** How many requests are waiting for an answer. */
	get inFlight(): number {
		return this.pending.size;
	}

	/** Stop the worker; anything still waiting resolves as aborted. */
	dispose(): void {
		this.restart("ES_ABORTED", "The expression engine was shut down");
	}

	private ensureWorker(): WorkerLike {
		if (this.worker) return this.worker;
		const worker = this.createWorker();
		worker.addEventListener("message", (event) => {
			// A terminated worker can still deliver what it had queued: only the current one counts.
			if (this.worker === worker) this.settle(event.data as EvalResponse);
		});
		worker.addEventListener("error", (event) => {
			event.preventDefault();
			if (this.worker === worker) this.restart("ES_WORKER", `The expression engine failed: ${event.message}`);
		});
		this.worker = worker;
		return worker;
	}

	private settle(response: EvalResponse): void {
		const entry = this.pending.get(response.id);
		if (!entry) return; // answered after its deadline: already settled
		clearTimeout(entry.timer);
		this.pending.delete(response.id);
		entry.resolve(response);
	}

	private fail(id: number, entry: Pending, code: string, message: string): void {
		clearTimeout(entry.timer);
		this.pending.delete(id);
		entry.resolve({ id, ok: false, error: { code, message }, elapsedMs: Date.now() - entry.started });
	}

	private expire(id: number): void {
		const entry = this.pending.get(id);
		if (!entry) return;
		this.fail(id, entry, "ES_DEADLINE", "The expression took too long and was stopped");
		this.restart("ES_ABORTED", "Stopped with another expression that took too long");
	}

	/** Kill the worker; every request still waiting resolves with `code`. The next request starts a new one. */
	private restart(code: string, message: string): void {
		this.worker?.terminate();
		this.worker = undefined;
		// Deleting the entry being visited is safe while iterating a Map.
		for (const [id, entry] of this.pending) this.fail(id, entry, code, message);
	}
}
