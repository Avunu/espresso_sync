// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

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

import { fromPointer, parentPointer, toPointer } from "./pointer.ts";
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

/** The part of an ajv `ErrorObject` this reads, so ajv itself stays a choice of the caller. */
export interface AjvErrorLike {
	instancePath: string;
	schemaPath: string;
	keyword: string;
	params: Record<string, unknown>;
	message?: string | undefined;
}

export interface FromAjvOptions {
	origin?: DiagnosticOrigin;
	item?: number;
	/** A fixed severity, or one per error (a response checked in "Warn" mode is all warnings). */
	severity?: Severity | ((error: AjvErrorLike) => Severity);
	/** The pointers the transform has rules for: an error belongs to the nearest one at or above it. */
	rules?: Iterable<string>;
	/** The target's tree, to tell an array index from a key that happens to be digits. */
	tree?: TreeNode;
}

const INDEX = /^(?:0|[1-9]\d*)$/;

/** The keyword's own property, for the errors that are about a property the object lacks or shouldn't have. */
function namedProperty(error: AjvErrorLike): string | undefined {
	const { missingProperty, additionalProperty, unevaluatedProperty } = error.params;
	for (const value of [missingProperty, additionalProperty, unevaluatedProperty]) {
		if (typeof value === "string") return value;
	}
	return undefined;
}

/** The child of `node` named `key` (in any of its variants), if the tree has it. */
function childOf(node: TreeNode | undefined, key: string): TreeNode | undefined {
	if (!node) return undefined;
	const direct = node.children.find((child) => child.key === key);
	if (direct) return direct;
	for (const variant of node.variants ?? []) {
		const found = variant.node.children.find((child) => child.key === key);
		if (found) return found;
	}
	return undefined;
}

/**
 * A data path with array indexes (`/lines/0/qty`) as a rule pointer
 * (`/lines/qty`). With a tree, a segment is an index only where the tree has an
 * array; without one, any all-digit segment is taken for an index.
 */
export function stripIndexes(path: string, tree?: TreeNode): string {
	const kept: string[] = [];
	let node = tree;
	let inArray = tree?.kind === "collection" || tree?.kind === "scalar_collection";
	for (const segment of fromPointer(path)) {
		const isIndex = tree ? inArray && INDEX.test(segment) : INDEX.test(segment);
		if (isIndex) {
			inArray = false;
			continue;
		}
		kept.push(segment);
		node = childOf(node, segment);
		inArray = node?.kind === "collection" || node?.kind === "scalar_collection";
	}
	return toPointer(kept);
}

/** The nearest pointer at or above `pointer` that has a rule; `pointer` itself when none does. */
export function nearestRule(pointer: string, rules: ReadonlySet<string>): string {
	for (let current = pointer; ; current = parentPointer(current)) {
		if (rules.has(current)) return current;
		if (current === "") return pointer;
	}
}

function quoted(name: string): string {
	return `“${name}”`;
}

function messageFor(error: AjvErrorLike, property: string | undefined): string {
	const { params } = error;
	switch (error.keyword) {
		case "required":
		case "dependentRequired":
			return `${quoted(property ?? "?")} is required`;
		case "additionalProperties":
		case "unevaluatedProperties":
			return `${quoted(property ?? "?")} is not a field of the target`;
		case "type":
			return `must be ${String(params["type"]).replaceAll(",", " or ")}`;
		case "enum": {
			const allowed = Array.isArray(params["allowedValues"]) ? params["allowedValues"] : [];
			return `must be one of ${allowed.map((value) => JSON.stringify(value)).join(", ")}`;
		}
		case "const":
			return `must be ${JSON.stringify(params["allowedValue"])}`;
		case "format":
			return `must be a ${String(params["format"])}`;
		default:
			return error.message ?? `fails ${error.keyword}`;
	}
}

/** Diagnostics for a validator's errors, each attached to the rule it belongs to. */
export function fromAjvErrors(
	errors: readonly AjvErrorLike[] | null | undefined,
	options: FromAjvOptions = {},
): Diagnostic[] {
	const rules = new Set(options.rules ?? []);
	const origin = options.origin ?? "client";
	return (errors ?? []).map((error) => {
		const property = namedProperty(error);
		const path =
			property === undefined ? error.instancePath : `${error.instancePath}/${toPointer([property]).slice(1)}`;
		const pointer = stripIndexes(path, options.tree);
		const severity =
			typeof options.severity === "function" ? options.severity(error) : (options.severity ?? "error");
		const diagnostic: Diagnostic = {
			rule: nearestRule(pointer, rules),
			path,
			severity,
			code: `schema.${error.keyword}`,
			message: messageFor(error, property),
			origin,
		};
		if (options.item !== undefined) diagnostic.item = options.item;
		return diagnostic;
	});
}

const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warning: 1, info: 2 };

/** Errors first, then by rule, path and item, so a list reads top to bottom like the tree. */
export function sortDiagnostics(diagnostics: readonly Diagnostic[]): Diagnostic[] {
	return [...diagnostics].sort(
		(a, b) =>
			SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
			a.rule.localeCompare(b.rule) ||
			a.path.localeCompare(b.path) ||
			(a.item ?? -1) - (b.item ?? -1) ||
			a.code.localeCompare(b.code),
	);
}

function identity(diagnostic: Diagnostic): string {
	const { rule, path, code, origin, item, message } = diagnostic;
	return JSON.stringify([rule, path, code, origin, item ?? null, message]);
}

/**
 * Replace one origin's diagnostics with a fresh set: a new server validation
 * replaces the last one's findings and keeps the browser's, and vice versa.
 * Duplicates are dropped.
 */
export function mergeDiagnostics(
	current: readonly Diagnostic[],
	fresh: readonly Diagnostic[],
	origin: DiagnosticOrigin,
): Diagnostic[] {
	const seen = new Set<string>();
	const merged: Diagnostic[] = [];
	for (const diagnostic of [...current.filter((d) => d.origin !== origin), ...fresh]) {
		const key = identity(diagnostic);
		if (seen.has(key)) continue;
		seen.add(key);
		merged.push(diagnostic);
	}
	return sortDiagnostics(merged);
}

/** Each rule's diagnostics. */
export function byRule(diagnostics: readonly Diagnostic[]): Map<string, Diagnostic[]> {
	const grouped = new Map<string, Diagnostic[]>();
	for (const diagnostic of diagnostics) {
		const list = grouped.get(diagnostic.rule);
		if (list) list.push(diagnostic);
		else grouped.set(diagnostic.rule, [diagnostic]);
	}
	return grouped;
}

/** How many of each severity. */
export function countBySeverity(diagnostics: readonly Diagnostic[]): Record<Severity, number> {
	const counts: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
	for (const diagnostic of diagnostics) counts[diagnostic.severity] += 1;
	return counts;
}
