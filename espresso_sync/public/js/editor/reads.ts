// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * Which input fields a JSONata expression reads.
 *
 * The editor draws a connector from each source field a rule reads to the
 * target field the rule fills, and counts a source field as used when any rule
 * reads it. This walks the parsed expression (jsonata's own parser, so the
 * answer matches what the engine runs) and resolves every path it can back to
 * the input document:
 *
 * - `a.b`, `$.a`, `$$.a`, `a.%.b` (parent), `a@$x` (focus) and variables bound
 *   to a path (`$c := customer; $c.email`) all resolve.
 * - `*` and `**` resolve to a pattern: the read keeps the segment and is marked
 *   `wildcard`.
 * - The lambda of `$map`, `$filter`, `$single`, `$sort`, `$reduce`, `$each` and
 *   `$sift` has its item parameter bound to the array (or the object's values)
 *   it is given.
 * - What can't be resolved without running the expression is reported in
 *   `dynamic` instead: `$lookup` (its key is a value), `$eval`, a path through
 *   a lambda parameter nobody bound, and the transform operator `| … |`.
 *
 * Pointers follow pointer.ts: the items of an array are implied, never indexed,
 * so `line_items[0].sku` reads `/line_items/sku`.
 */

import jsonata from "jsonata";
import { toPointer } from "./pointer.ts";

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

export interface ReadsError {
	code: string;
	message: string;
	position: number | undefined;
	token: string | undefined;
}

export type ReadsResult = ({ ok: true } & Reads) | { ok: false; error: ReadsError };

export interface ReadsOptions {
	/**
	 * Where the expression is evaluated, as path segments from the input root:
	 * a rule inside a collection reads relative to the collection's items.
	 * `$` is this context; `$$` is always the input root.
	 */
	context?: readonly string[];
}

/** The parts of jsonata's AST this walker reads. Every field is optional because node types differ. */
interface AstNode {
	type: string;
	value?: unknown;
	position?: number;
	steps?: AstNode[];
	stages?: AstNode[];
	expr?: AstNode;
	expression?: AstNode;
	expressions?: AstNode[];
	arguments?: AstNode[];
	procedure?: AstNode;
	lhs?: AstNode | [AstNode, AstNode][];
	rhs?: AstNode;
	condition?: AstNode;
	then?: AstNode;
	else?: AstNode;
	body?: AstNode;
	pattern?: AstNode;
	update?: AstNode;
	delete?: AstNode;
	terms?: { expression: AstNode }[];
	group?: { lhs: [AstNode, AstNode][] };
	focus?: string;
	index?: string;
	ancestor?: { label: string };
	slot?: { label: string };
}

/** A resolved input path, or null for a computed value. */
type Path = readonly string[] | null;

/** What a variable holds: an input path, a computed value, or an unbound lambda parameter. */
type Binding = { kind: "path"; path: readonly string[] } | { kind: "value" } | { kind: "param" };

class Scope {
	private readonly vars = new Map<string, Binding>();
	private readonly parent: Scope | undefined;

	constructor(parent: Scope | undefined) {
		this.parent = parent;
	}

	bind(name: string, binding: Binding): void {
		this.vars.set(name, binding);
	}

	lookup(name: string): Binding | undefined {
		return this.vars.get(name) ?? this.parent?.lookup(name);
	}

	child(): Scope {
		return new Scope(this);
	}
}

/** Higher-order functions whose lambda gets the items of the first argument, and which parameter that is. */
const ITEM_PARAMETER: Record<string, { index: number; values?: boolean; also?: number[] }> = {
	map: { index: 0 },
	filter: { index: 0 },
	single: { index: 0 },
	sort: { index: 0, also: [1] },
	reduce: { index: 1 },
	each: { index: 0, values: true },
	sift: { index: 0, values: true },
};

const BINDING_VALUE: Binding = { kind: "value" };

function bindingOf(path: Path): Binding {
	return path === null ? BINDING_VALUE : { kind: "path", path };
}

class Walker {
	private readonly reads = new Map<string, ReadRef>();
	private readonly dynamic: DynamicRead[] = [];
	/** The path before each step that `%` can climb back to, by the parser's slot label. */
	private readonly ancestors = new Map<string, Path>();

	result(): Reads {
		return { reads: [...this.reads.values()], dynamic: this.dynamic };
	}

	private record(path: Path): void {
		if (path === null) return;
		const pointer = toPointer(path);
		const wildcard = path.some((segment) => segment === "*" || segment === "**");
		const key = `${wildcard ? "w" : "p"}${pointer}`;
		if (!this.reads.has(key)) this.reads.set(key, { pointer, segments: [...path], wildcard });
	}

	private flag(reason: DynamicReason, node: AstNode, base?: Path): void {
		const entry: DynamicRead = { reason, position: node.position };
		if (base) entry.base = toPointer(base);
		this.dynamic.push(entry);
	}

	/** Evaluate a node whose value is used: whatever input path it resolves to is a read. */
	use(node: AstNode | undefined, ctx: Path, scope: Scope): void {
		if (node) this.record(this.walk(node, ctx, scope));
	}

	/** Walk a node, recording the reads inside it, and answer the input path its value is (if any). */
	walk(node: AstNode, ctx: Path, scope: Scope): Path {
		switch (node.type) {
			case "path":
				return this.path(node, ctx, scope);
			case "name":
				return ctx === null ? null : [...ctx, String(node.value)];
			case "wildcard":
				return ctx === null ? null : [...ctx, "*"];
			case "descendant":
				return ctx === null ? null : [...ctx, "**"];
			case "variable":
				return this.variable(node, ctx, scope);
			case "block": {
				const inner = scope.child();
				const expressions = node.expressions ?? [];
				const last = expressions.at(-1);
				for (const expression of expressions.slice(0, -1)) this.use(expression, ctx, inner);
				return last ? this.walk(last, ctx, inner) : null;
			}
			case "bind": {
				const name = this.variableName(node.lhs);
				const value = node.rhs ? this.bound(node.rhs, ctx, scope) : BINDING_VALUE;
				if (name !== undefined) scope.bind(name, value);
				// The variable's path is read where the variable is used, not here.
				return null;
			}
			case "function":
			case "partial":
				this.call(node, ctx, scope);
				return null;
			case "apply":
				this.apply(node, ctx, scope);
				return null;
			case "lambda":
				this.lambda(node, ctx, scope, new Map());
				return null;
			case "condition":
				this.use(node.condition, ctx, scope);
				this.use(node.then, ctx, scope);
				this.use(node.else, ctx, scope);
				return null;
			case "transform":
				this.flag("transform", node);
				this.use(node.pattern, null, scope);
				this.use(node.update, null, scope);
				this.use(node.delete, null, scope);
				return null;
			case "unary":
				this.unary(node, ctx, scope);
				return null;
			case "binary":
				if (!Array.isArray(node.lhs)) this.use(node.lhs, ctx, scope);
				this.use(node.rhs, ctx, scope);
				return null;
			default:
				// string, number, value, regex, operator, error: no input read.
				return null;
		}
	}

	private variableName(node: AstNode | [AstNode, AstNode][] | undefined): string | undefined {
		if (!node || Array.isArray(node) || node.type !== "variable") return undefined;
		return String(node.value);
	}

	/** What `$name := <node>` binds: a lambda's reads stay unresolved until it's called. */
	private bound(node: AstNode, ctx: Path, scope: Scope): Binding {
		return bindingOf(this.walk(node, ctx, scope));
	}

	private variable(node: AstNode, ctx: Path, scope: Scope): Path {
		const name = String(node.value);
		if (name === "") return ctx; // $: the context
		if (name === "$") return []; // $$: the input root
		const binding = scope.lookup(name);
		return binding?.kind === "path" ? binding.path : null;
	}

	private path(node: AstNode, ctx: Path, scope: Scope): Path {
		let cur: Path = ctx;
		const steps = node.steps ?? [];
		for (const [index, step] of steps.entries()) {
			const before = cur;
			if (step.ancestor) this.ancestors.set(step.ancestor.label, before);
			cur = this.step(step, cur, scope, index < steps.length - 1);
			if (step.focus !== undefined) {
				// `a@$x`: $x is each a, and the context stays where it was.
				scope.bind(step.focus, bindingOf(cur));
				cur = before;
			}
			if (step.index !== undefined) scope.bind(step.index, BINDING_VALUE);
			for (const stage of step.stages ?? []) {
				if (stage.type === "filter") this.use(stage.expr, cur, scope);
			}
		}
		if (node.group) {
			for (const [key, value] of node.group.lhs) {
				this.use(key, cur, scope);
				this.use(value, cur, scope);
			}
			return null;
		}
		return cur;
	}

	private step(step: AstNode, cur: Path, scope: Scope, more: boolean): Path {
		switch (step.type) {
			case "name":
				return cur === null ? null : [...cur, String(step.value)];
			case "wildcard":
				return cur === null ? null : [...cur, "*"];
			case "descendant":
				return cur === null ? null : [...cur, "**"];
			case "parent":
				return step.slot ? (this.ancestors.get(step.slot.label) ?? null) : null;
			case "variable": {
				const name = String(step.value);
				if (name === "") return cur; // `$` at the start, or `a.$`: the context
				if (name === "$") return []; // `$$`: the input root
				const binding = scope.lookup(name);
				if (binding?.kind === "param" && more) this.flag("lambda", step);
				return binding?.kind === "path" ? binding.path : null;
			}
			case "sort":
				for (const term of step.terms ?? []) this.use(term.expression, cur, scope);
				return cur;
			default:
				// A computed step: `a.(b)` still resolves, `a.$string(b)` and `a.{…}` don't.
				return this.walk(step, cur, scope);
		}
	}

	private unary(node: AstNode, ctx: Path, scope: Scope): void {
		if (node.value === "{" && Array.isArray(node.lhs)) {
			for (const [key, value] of node.lhs) {
				this.use(key, ctx, scope);
				this.use(value, ctx, scope);
			}
			return;
		}
		for (const expression of node.expressions ?? []) this.use(expression, ctx, scope);
		this.use(node.expression, ctx, scope);
	}

	private procedureName(node: AstNode): string | undefined {
		const procedure = node.procedure;
		return procedure?.type === "variable" ? String(procedure.value) : undefined;
	}

	private call(node: AstNode, ctx: Path, scope: Scope, piped?: AstNode): void {
		const name = this.procedureName(node);
		const args = piped ? [piped, ...(node.arguments ?? [])] : (node.arguments ?? []);
		if (name !== undefined && scope.lookup(name) === undefined) {
			if (name === "lookup") {
				const [object, ...rest] = args;
				this.flag("lookup", node, object ? this.walk(object, ctx, scope) : null);
				for (const arg of rest) this.use(arg, ctx, scope);
				return;
			}
			if (name === "eval") {
				this.flag("eval", node);
				for (const arg of args) this.use(arg, ctx, scope);
				return;
			}
			const item = ITEM_PARAMETER[name];
			const [source, fn, ...rest] = args;
			if (item && source && fn?.type === "lambda") {
				let items = this.walk(source, ctx, scope);
				if (items !== null && item.values) items = [...items, "*"];
				const params = new Map<number, Binding>();
				for (const position of [item.index, ...(item.also ?? [])]) params.set(position, bindingOf(items));
				this.lambda(fn, ctx, scope, params);
				for (const arg of rest) this.use(arg, ctx, scope);
				return;
			}
		}
		for (const arg of args) this.use(arg, ctx, scope);
	}

	private apply(node: AstNode, ctx: Path, scope: Scope): void {
		const lhs = Array.isArray(node.lhs) ? undefined : node.lhs;
		const rhs = node.rhs;
		if (lhs && (rhs?.type === "function" || rhs?.type === "partial")) {
			this.call(rhs, ctx, scope, lhs);
			return;
		}
		this.use(lhs, ctx, scope);
		this.use(rhs, ctx, scope);
	}

	/** Walk a lambda's body, its parameters bound as given (by position) or else unresolved. */
	private lambda(node: AstNode, ctx: Path, scope: Scope, params: Map<number, Binding>): void {
		const inner = scope.child();
		for (const [position, param] of (node.arguments ?? []).entries()) {
			inner.bind(String(param.value), params.get(position) ?? { kind: "param" });
		}
		this.use(node.body, ctx, inner);
	}
}

/** The reads of an already-parsed expression (`jsonata(text).ast()`). */
export function readsOfAst(ast: unknown, options: ReadsOptions = {}): Reads {
	const walker = new Walker();
	walker.use(ast as AstNode, options.context ?? [], new Scope(undefined));
	return walker.result();
}

function parseError(error: unknown): ReadsError {
	const fields = typeof error === "object" && error !== null ? (error as Record<string, unknown>) : {};
	const { code, message, position, token } = fields;
	return {
		code: typeof code === "string" ? code : "S0000",
		message: typeof message === "string" ? message : String(error),
		position: typeof position === "number" ? position : undefined,
		token: typeof token === "string" ? token : undefined,
	};
}

/** The reads of an expression's source text, or the parse error that stopped it. */
export function readsOf(expression: string, options: ReadsOptions = {}): ReadsResult {
	let ast: unknown;
	try {
		ast = jsonata(expression).ast();
	} catch (error) {
		return { ok: false, error: parseError(error) };
	}
	return { ok: true, ...readsOfAst(ast, options) };
}
