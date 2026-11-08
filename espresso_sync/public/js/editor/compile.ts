// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * A Transform's rules, compiled to the one JSONata expression it runs.
 *
 * The server's transform/compile.py gives the same text for the same rules,
 * byte for byte: both are checked against the golden files in
 * espresso_sync/tests/fixtures/compile. See there for what each kind of rule
 * compiles to; in short, a `field` is its expression, a `collection` is
 * `[(expr).{…rules under it…}]` and a `scalar_collection` is `[(expr)]`, so a
 * collection is always an array. Expressions are kept as written, newlines
 * included, and keys come in the order the rules first name them.
 */

import { fromPointer } from "./pointer.ts";

export type RuleKind = "field" | "collection" | "scalar_collection";

/** A rule: the target field it fills (pointer.ts's form) and the expression that fills it. */
export interface Rule {
	ptr: string;
	kind: RuleKind;
	expr: string;
}

export interface CompileError {
	rule: string;
	code: string;
	message: string;
}

export interface Compiled {
	jsonata: string;
	/** The rules left out, and why. */
	errors: CompileError[];
}

const KINDS: ReadonlySet<string> = new Set(["field", "collection", "scalar_collection"]);
const INDENT = "\t";

interface Node {
	rule?: Rule;
	children: Map<string, Node>;
}

function ruleError(rule: unknown): CompileError | undefined {
	if (typeof rule !== "object" || rule === null || Array.isArray(rule)) {
		return { rule: "", code: "compile.rule", message: "A rule is an object with ptr, kind and expr" };
	}
	const { ptr, kind, expr } = rule as Record<string, unknown>;
	if (typeof ptr !== "string" || (ptr !== "" && !ptr.startsWith("/"))) {
		const shown = typeof ptr === "string" ? ptr : "";
		return { rule: shown, code: "compile.pointer", message: `${String(ptr)} is not a JSON Pointer` };
	}
	if (typeof kind !== "string" || !KINDS.has(kind)) {
		return {
			rule: ptr,
			code: "compile.kind",
			message: `${String(kind)} is not field, collection or scalar_collection`,
		};
	}
	if (typeof expr !== "string" || expr.trim() === "") {
		return { rule: ptr, code: "compile.empty", message: "An expression is required" };
	}
	return undefined;
}

function* rulesUnder(node: Node): Generator<Rule> {
	for (const child of node.children.values()) {
		if (child.rule) yield child.rule;
		yield* rulesUnder(child);
	}
}

/** The JSONata of `rules`, with the rules it had to leave out. */
export function compileRules(rules: readonly unknown[]): Compiled {
	const root: Node = { children: new Map() };
	const errors: CompileError[] = [];
	for (const candidate of rules) {
		const error = ruleError(candidate);
		if (error) {
			errors.push(error);
			continue;
		}
		const rule = candidate as Rule;
		let node = root;
		for (const segment of fromPointer(rule.ptr)) {
			let child = node.children.get(segment);
			if (!child) {
				child = { children: new Map() };
				node.children.set(segment, child);
			}
			node = child;
		}
		if (node.rule) {
			errors.push({ rule: rule.ptr, code: "compile.duplicate", message: `${rule.ptr} has two rules` });
			continue;
		}
		node.rule = rule;
	}

	const parts: string[] = [];
	const writeObject = (node: Node, depth: number): void => {
		if (node.children.size === 0) {
			parts.push("{}");
			return;
		}
		parts.push("{");
		let index = 0;
		for (const [key, child] of node.children) {
			parts.push(`${index ? "," : ""}\n${INDENT.repeat(depth + 1)}${JSON.stringify(key)}: `);
			writeNode(child, depth + 1);
			index += 1;
		}
		parts.push(`\n${INDENT.repeat(depth)}}`);
	};
	const writeNode = (node: Node, depth: number): void => {
		const rule = node.rule;
		if (!rule) {
			writeObject(node, depth);
			return;
		}
		if (rule.kind !== "collection") {
			for (const nested of rulesUnder(node)) {
				errors.push({
					rule: nested.ptr,
					code: "compile.nested",
					message: `${rule.ptr} is filled by a ${rule.kind} rule: nothing can be under it`,
				});
			}
		}
		if (rule.kind === "field") {
			parts.push(`(${rule.expr})`);
			return;
		}
		parts.push(`[(${rule.expr})`);
		if (rule.kind === "collection") {
			parts.push(".");
			writeObject(node, depth);
		}
		parts.push("]");
	};
	writeNode(root, 0);
	return { jsonata: parts.join(""), errors };
}
