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
 * 2. Outside it, `EvalClient` sends the worker one request at a time and gives
 *    each a deadline a little past `timeoutMs`, counted from when it is sent.
 *    Something the guardrails can't interrupt (a catastrophic regular
 *    expression, a giant result) runs past it, and the client then terminates
 *    the worker and starts a new one for the requests still waiting.
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
	/**
	 * jsonata's code (`S0201`, `T2001`, `D1012`), or one of the client's:
	 * `ES_DEADLINE`, `ES_SUPERSEDED`, `ES_ABORTED` or `ES_WORKER`.
	 */
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

/** A request as the page makes it: the client numbers it, and `key` names what it is for. */
export interface EvalCall extends Omit<EvalRequest, "id"> {
	/**
	 * What the request is for (a rule's pointer, say). A newer request with
	 * the same key replaces one still waiting its turn, which then resolves
	 * with `ES_SUPERSEDED`: a burst of keystrokes evaluates only the last.
	 */
	key?: string;
}

interface Job {
	id: number;
	key: string | undefined;
	request: EvalRequest;
	resolve: (response: EvalResponse) => void;
	/** When the request was made, then when it was sent: what `elapsedMs` counts from. */
	since: number;
	timer?: ReturnType<typeof setTimeout>;
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
	private readonly createWorker: () => WorkerLike;
	private readonly graceMs: number;
	private worker: WorkerLike | undefined;
	/** The request the worker is on. */
	private current: Job | undefined;
	/** The requests waiting their turn, oldest first. */
	private readonly queue: Job[] = [];
	private nextId = 1;

	constructor(createWorker: () => WorkerLike, options: EvalClientOptions = {}) {
		this.createWorker = createWorker;
		this.graceMs = options.graceMs ?? 500;
	}

	evaluate(call: EvalCall): Promise<EvalResponse> {
		const { key, ...request } = call;
		const id = this.nextId++;
		return new Promise<EvalResponse>((resolve) => {
			if (key !== undefined) {
				const index = this.queue.findIndex((job) => job.key === key);
				const [older] = index === -1 ? [] : this.queue.splice(index, 1);
				if (older) this.fail(older, "ES_SUPERSEDED", "Replaced by a newer evaluation of the same expression");
			}
			this.queue.push({ id, key, request: { ...request, id }, resolve, since: Date.now() });
			this.pump();
		});
	}

	/** Stop the worker; anything still waiting resolves as aborted. */
	dispose(): void {
		this.stopWorker();
		const message = "The expression engine was shut down";
		if (this.current) this.fail(this.current, "ES_ABORTED", message);
		this.current = undefined;
		for (const job of this.queue.splice(0)) this.fail(job, "ES_ABORTED", message);
	}

	/** Send the next waiting request, if the worker is free. */
	private pump(): void {
		if (this.current) return;
		const job = this.queue.shift();
		if (!job) return;
		const worker = this.ensureWorker();
		const timeoutMs = job.request.limits?.timeoutMs ?? DEFAULT_LIMITS.timeoutMs;
		this.current = job;
		job.since = Date.now();
		job.timer = setTimeout(() => this.expire(job), timeoutMs + this.graceMs);
		worker.postMessage(job.request);
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
			if (this.worker === worker) this.abandon("ES_WORKER", `The expression engine failed: ${event.message}`);
		});
		this.worker = worker;
		return worker;
	}

	private settle(response: EvalResponse): void {
		const job = this.current;
		if (job?.id !== response.id) return; // answered after its deadline: already settled
		this.current = undefined;
		clearTimeout(job.timer);
		job.resolve(response);
		this.pump();
	}

	private fail(job: Job, code: string, message: string): void {
		clearTimeout(job.timer);
		job.resolve({ id: job.id, ok: false, error: { code, message }, elapsedMs: Date.now() - job.since });
	}

	private expire(job: Job): void {
		if (this.current !== job) return;
		this.abandon("ES_DEADLINE", "The expression took too long and was stopped");
	}

	/** Fail the current request with `code` and replace the worker; those waiting go to the new one. */
	private abandon(code: string, message: string): void {
		this.stopWorker();
		const job = this.current;
		this.current = undefined;
		if (job) this.fail(job, code, message);
		this.pump();
	}

	private stopWorker(): void {
		this.worker?.terminate();
		this.worker = undefined;
	}
}
