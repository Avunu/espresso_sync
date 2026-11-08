// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	DEFAULT_LIMITS,
	EvalClient,
	type EvalRequest,
	type EvalResponse,
	evaluate,
	FUNCTION_PLACEHOLDER,
	serve,
	toEvalError,
	toPlain,
	type WorkerLike,
	type WorkerScopeLike,
} from "../../espresso_sync/public/js/editor/evalWorker.ts";

const order = { customer: { first_name: "Ada", last_name: "Lovelace" }, lines: [{ qty: 2 }, { qty: 3 }] };

function request(expression: string, extra: Partial<EvalRequest> = {}): EvalRequest {
	return { id: 7, expression, input: order, ...extra };
}

describe("evaluate", () => {
	it("returns the result as plain JSON, with the request's id", async () => {
		const response = await evaluate(request('customer.first_name & " " & customer.last_name'));
		assert.equal(response.id, 7);
		assert.ok(response.ok);
		assert.equal(response.value, "Ada Lovelace");
		assert.equal(response.defined, true);
		assert.ok(response.elapsedMs >= 0);
	});

	it("turns sequences into arrays and passes bindings", async () => {
		const response = await evaluate(request("lines.(qty * $factor)", { bindings: { factor: 10 } }));
		assert.ok(response.ok);
		assert.deepEqual(response.value, [20, 30]);
		assert.ok(Array.isArray(response.value) && !("sequence" in response.value));
	});

	it("says when the expression produced nothing", async () => {
		const response = await evaluate(request("customer.middle_name"));
		assert.ok(response.ok);
		assert.equal(response.value, null);
		assert.equal(response.defined, false);
	});

	it("replaces functions, which can't leave the worker", async () => {
		const response = await evaluate(request('{"f": function($x){ $x }, "n": 1}'));
		assert.ok(response.ok);
		assert.deepEqual(response.value, { f: FUNCTION_PLACEHOLDER, n: 1 });
		assert.equal(
			toPlain(() => 1),
			FUNCTION_PLACEHOLDER,
		);
		assert.equal(toPlain(undefined), null);
	});

	it("reports parse and evaluation errors as jsonata codes", async () => {
		const parse = await evaluate(request("customer."));
		assert.ok(!parse.ok);
		assert.equal(parse.error.code, "S0207");
		assert.equal(typeof parse.error.position, "number");
		const type = await evaluate(request('"a" + 1'));
		assert.ok(!type.ok);
		assert.equal(type.error.code, "T2001");
	});

	it("stops runaway recursion and evaluation past its timeout", async () => {
		const deep = await evaluate(
			request("($f := function($n){ 1 + $f($n + 1) }; $f(0))", { limits: { maxDepth: 50 } }),
		);
		assert.ok(!deep.ok);
		assert.equal(deep.error.code, "D1011");
		// A tail call doesn't deepen the stack, so only the timeout stops it.
		const forever = await evaluate(
			request("($f := function($n){ $f($n + 1) }; $f(0))", { limits: { timeoutMs: 40 } }),
		);
		assert.ok(!forever.ok);
		assert.equal(forever.error.code, "D1012");
		let clock = 0;
		const timed = await evaluate(request("1"), () => (clock += 5));
		assert.equal(timed.elapsedMs, 5);
		const huge = await evaluate(request("[1..1000]", { limits: { maxSequence: 10 } }));
		assert.ok(!huge.ok);
		assert.match(huge.error.code, /^D201[45]$/);
	});

	it("reads any thrown value as an error", () => {
		assert.deepEqual(toEvalError("boom"), { code: "ES_ERROR", message: "boom" });
		assert.deepEqual(toEvalError({ code: "X", message: "y", position: 3, token: "t" }), {
			code: "X",
			message: "y",
			position: 3,
			token: "t",
		});
		assert.ok(DEFAULT_LIMITS.timeoutMs > 0);
	});
});

describe("serve", () => {
	it("answers each message posted to the worker scope", async () => {
		let listener: ((event: MessageEvent) => void) | undefined;
		const posted: unknown[] = [];
		const answered = new Promise<void>((resolve) => {
			const scope: WorkerScopeLike = {
				addEventListener: (_type, fn) => {
					listener = fn;
				},
				postMessage: (message) => {
					posted.push(message);
					resolve();
				},
			};
			serve(scope);
		});
		listener?.({ data: request("$count(lines)") } as MessageEvent);
		await answered;
		assert.deepEqual(posted, [
			{ id: 7, ok: true, value: 2, defined: true, elapsedMs: (posted[0] as { elapsedMs: number }).elapsedMs },
		]);
	});
});

/** A Worker stand-in: evaluates in-process (after `delayMs`, like a slow expression), or with `hang` never answers. */
class FakeWorker implements WorkerLike {
	terminated = false;
	readonly hang: boolean;
	readonly delayMs: number;
	/** How many requests it has been sent, and the most it held unanswered at once. */
	received = 0;
	maxBusy = 0;
	private busy = 0;
	private readonly listeners = {
		message: [] as ((event: MessageEvent) => void)[],
		error: [] as ((event: ErrorEvent) => void)[],
	};

	constructor(hang: boolean, delayMs = 0) {
		this.hang = hang;
		this.delayMs = delayMs;
	}

	addEventListener(type: "message", listener: (event: MessageEvent) => void): void;
	addEventListener(type: "error", listener: (event: ErrorEvent) => void): void;
	addEventListener(
		type: "message" | "error",
		listener: ((event: MessageEvent) => void) | ((event: ErrorEvent) => void),
	): void {
		if (type === "message") this.listeners.message.push(listener as (event: MessageEvent) => void);
		else this.listeners.error.push(listener as (event: ErrorEvent) => void);
	}

	postMessage(message: unknown): void {
		this.received++;
		this.busy++;
		this.maxBusy = Math.max(this.maxBusy, this.busy);
		if (this.hang) return;
		setTimeout(() => {
			void evaluate(message as EvalRequest).then((response) => {
				this.busy--;
				this.answer(response);
			});
		}, this.delayMs);
	}

	/** Deliver a response, as a worker would (even a terminated one, with something already queued). */
	answer(response: EvalResponse): void {
		for (const listener of this.listeners.message) listener({ data: response } as MessageEvent);
	}

	terminate(): void {
		this.terminated = true;
	}

	fail(message: string): void {
		let prevented = false;
		const event = { message, preventDefault: () => (prevented = true) } as unknown as ErrorEvent;
		for (const listener of this.listeners.error) listener(event);
		assert.ok(prevented);
	}
}

describe("EvalClient", () => {
	it("sends requests to the worker and resolves each with its answer", async () => {
		const workers: FakeWorker[] = [];
		const client = new EvalClient(() => {
			const worker = new FakeWorker(false);
			workers.push(worker);
			return worker;
		});
		const [a, b] = await Promise.all([
			client.evaluate({ expression: "1 + 1", input: null }),
			client.evaluate({ expression: "$sum(lines.qty)", input: order }),
		]);
		assert.ok(a.ok && b.ok);
		assert.deepEqual([a.value, b.value], [2, 5]);
		assert.notEqual(a.id, b.id);
		assert.equal(workers.length, 1);
		assert.equal(client.inFlight, 0);
		client.dispose();
		assert.ok(workers[0]?.terminated);
	});

	it("gives up on a worker that misses the deadline, and sends what waits to a new one", async () => {
		const workers: FakeWorker[] = [];
		const client = new EvalClient(
			() => {
				// The first worker never answers; the next ones do.
				const worker = new FakeWorker(workers.length === 0);
				workers.push(worker);
				return worker;
			},
			{ graceMs: 5 },
		);
		const [late, other] = await Promise.all([
			client.evaluate({ expression: "1", input: null, limits: { timeoutMs: 5 } }),
			client.evaluate({ expression: "2", input: null, limits: { timeoutMs: 1000 } }),
		]);
		assert.ok(!late.ok);
		assert.equal(late.error.code, "ES_DEADLINE");
		assert.ok(other.ok);
		assert.equal(other.value, 2);
		assert.ok(workers[0]?.terminated);
		assert.equal(workers[0]?.received, 1);
		const next = await client.evaluate({ expression: "3", input: null });
		assert.ok(next.ok);
		assert.equal(next.value, 3);
		assert.equal(workers.length, 2);
		client.dispose();
	});

	it("sends one request at a time, so waiting never counts against a deadline", async () => {
		const workers: FakeWorker[] = [];
		const client = new EvalClient(
			() => {
				const worker = new FakeWorker(false, 10);
				workers.push(worker);
				return worker;
			},
			{ graceMs: 10 },
		);
		// Each takes 10 ms of a 50 ms deadline; all eight together take longer than one deadline.
		const responses = await Promise.all(
			Array.from({ length: 8 }, (_, index) =>
				client.evaluate({ expression: `${index} * 2`, input: null, limits: { timeoutMs: 40 } }),
			),
		);
		assert.deepEqual(
			responses.map((response) => (response.ok ? response.value : response.error.code)),
			[0, 2, 4, 6, 8, 10, 12, 14],
		);
		assert.equal(workers.length, 1);
		assert.equal(workers[0]?.maxBusy, 1);
		assert.equal(client.inFlight, 0);
		client.dispose();
	});

	it("replaces a waiting request with a newer one of the same key", async () => {
		const workers: FakeWorker[] = [];
		const client = new EvalClient(() => {
			const worker = new FakeWorker(false, 5);
			workers.push(worker);
			return worker;
		});
		const running = client.evaluate({ expression: "1", input: null, key: "/a" });
		const stale = client.evaluate({ expression: "2", input: null, key: "/a" });
		const other = client.evaluate({ expression: "3", input: null, key: "/b" });
		const fresh = client.evaluate({ expression: "4", input: null, key: "/a" });
		assert.equal(client.inFlight, 3);
		const responses = await Promise.all([running, stale, other, fresh]);
		assert.deepEqual(
			responses.map((response) => (response.ok ? response.value : response.error.code)),
			[1, "ES_SUPERSEDED", 3, 4],
		);
		// The one already sent runs to the end; the superseded one never reaches the worker.
		assert.equal(workers[0]?.received, 3);
		client.dispose();
	});

	it("fails what is waiting when the worker errors, or the client is disposed", async () => {
		const workers: FakeWorker[] = [];
		const client = new EvalClient(() => {
			const worker = new FakeWorker(true);
			workers.push(worker);
			return worker;
		});
		const waiting = client.evaluate({ expression: "1", input: null });
		workers[0]?.fail("script error");
		const failed = await waiting;
		assert.ok(!failed.ok);
		assert.equal(failed.error.code, "ES_WORKER");
		assert.match(failed.error.message, /script error/);

		const pending = client.evaluate({ expression: "1", input: null });
		const queued = client.evaluate({ expression: "2", input: null });
		assert.equal(client.inFlight, 2);
		client.dispose();
		const aborted = await Promise.all([pending, queued]);
		assert.deepEqual(
			aborted.map((response) => (response.ok ? response.value : response.error.code)),
			["ES_ABORTED", "ES_ABORTED"],
		);
		assert.equal(workers.length, 2);
		assert.equal(workers[1]?.received, 1);
	});

	it("ignores an answer that comes after its deadline", async () => {
		let worker: FakeWorker | undefined;
		const client = new EvalClient(
			() => {
				worker = new FakeWorker(true);
				return worker;
			},
			{ graceMs: 1 },
		);
		const response = await client.evaluate({ expression: "1", input: null, limits: { timeoutMs: 1 } });
		assert.ok(!response.ok);
		const late: EvalResponse = { id: response.id, ok: true, value: 1, defined: true, elapsedMs: 1 };
		worker?.answer(late);
		worker?.fail("too late to matter");
		assert.equal(client.inFlight, 0);
	});
});
