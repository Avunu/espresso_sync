// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * The transform editor's rules, read against its two trees.
 *
 * - Where a rule is evaluated: a rule under a `collection` rule runs on each
 *   item that rule gives, so `collectionChain` and `sourceContext` say which
 *   items, and `sourceReference` writes a source field as the rule must read it
 *   there (`sku` on a line item, `$$.currency` from the document's root).
 * - What each rule gives on a sample item: `probeExpression` wraps a rule in
 *   the collections above it as `{"i": [(collection).{"v": (rule)}]}`, so every
 *   value keeps the index of the item it came from, and `probeValues` reads
 *   them back. `probesExpression` asks for every rule at once.
 * - What the editor shows before anything is saved: the required fields no
 *   rule fills (as the server's validate.required_diagnostics finds them), how
 *   many fields are mapped, and the findings of the rules themselves.
 */

import Ajv2020, { type ValidateFunction } from "ajv/dist/2020.js";
import jsonata from "jsonata";
import type { Compiled, Rule } from "./compile.ts";
import { type Diagnostic, fromAjvErrors, type Severity } from "./diagnostics.ts";
import type { EvalError, EvalResponse } from "./evalWorker.ts";
import { fromPointer, parentPointer, toPointer } from "./pointer.ts";
import { readsOf } from "./reads.ts";
import { type TreeNode, mappableNodes } from "./schemaTree.ts";
import { type Compatibility, compatibility, inferFromSamples } from "./typeInfer.ts";

/** The rules, by the pointer of the field each fills. */
export type Rules = ReadonlyMap<string, Rule>;

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A sample's items: a list, or one item (as the server's get_sample reads it). */
export function sampleItems(sample: unknown): unknown[] {
	if (sample === null || sample === undefined) return [];
	return Array.isArray(sample) ? sample : [sample];
}

// where a rule runs

/** A path an expression is, and nothing more: from the context (`a.b`, `$`), or from the root (`$$.a`). */
export interface SimplePath {
	absolute: boolean;
	segments: string[];
}

interface AstNode {
	type: string;
	value?: unknown;
	steps?: AstNode[];
	stages?: unknown[];
	predicate?: unknown[];
	group?: unknown;
	focus?: string;
	index?: string;
	keepArray?: boolean;
	keepSingletonArray?: boolean;
}

/** The path `expression` is, when it is only a path of field names; undefined for anything else. */
export function simplePath(expression: string): SimplePath | undefined {
	let ast: AstNode;
	try {
		ast = jsonata(expression).ast() as AstNode;
	} catch {
		return undefined;
	}
	if (ast.type === "path" && (ast.group !== undefined || ast.keepSingletonArray)) return undefined;
	const steps = ast.type === "path" ? (ast.steps ?? []) : [ast];
	const path: SimplePath = { absolute: false, segments: [] };
	for (const [index, step] of steps.entries()) {
		if (step.stages || step.predicate || step.group || step.focus || step.index || step.keepArray) {
			return undefined;
		}
		if (index === 0 && step.type === "variable" && (step.value === "" || step.value === "$")) {
			path.absolute = step.value === "$";
			continue;
		}
		if (step.type !== "name") return undefined;
		path.segments.push(String(step.value));
	}
	return path;
}

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
// what JSONata would read as an operator or a value, not as a field name
const RESERVED = new Set(["and", "or", "in", "true", "false", "null", "function"]);

/** Field names as a JSONata path: `customer.first_name`, with `` `odd name` `` quoted. */
export function pathExpression(segments: readonly string[]): string {
	return segments
		.map((segment) => (NAME.test(segment) && !RESERVED.has(segment) ? segment : `\`${segment}\``))
		.join(".");
}

/** The `collection` rules above `pointer` (not its own), outermost first: what its rule runs on. */
export function collectionChain(pointer: string, rules: Rules): Rule[] {
	const chain: Rule[] = [];
	let current = pointer;
	while (current !== "") {
		current = parentPointer(current);
		const rule = rules.get(current);
		if (rule?.kind === "collection") chain.unshift(rule);
	}
	return chain;
}

/**
 * The source path of the items a rule at `pointer` runs on: `[]` for the
 * source item itself, `["line_items"]` under a collection that reads
 * `line_items`. Undefined when a collection above it is more than a path.
 */
export function sourceContext(pointer: string, rules: Rules): string[] | undefined {
	let context: string[] = [];
	for (const rule of collectionChain(pointer, rules)) {
		const path = simplePath(rule.expr);
		if (!path) return undefined;
		context = path.absolute ? path.segments : [...context, ...path.segments];
	}
	return context;
}

/** How a rule at `targetPointer` reads the source field at `sourcePointer`. */
export function sourceReference(sourcePointer: string, targetPointer: string, rules: Rules): string {
	const source = fromPointer(sourcePointer);
	const context = sourceContext(targetPointer, rules);
	if (context && context.every((segment, index) => source[index] === segment)) {
		const rest = source.slice(context.length);
		return rest.length > 0 ? pathExpression(rest) : "$";
	}
	return source.length > 0 ? `$$.${pathExpression(source)}` : "$$";
}

// what each rule gives

/** One value a rule gave: `at` is the index of each collection item above it. */
export interface ProbeValue {
	at: number[];
	value: unknown;
	/** False when the rule gave nothing there (JSONata's undefined: the key is left out). */
	defined: boolean;
}

/** A rule's own value: a collection's items, or a field's value. */
function ruleValue(rule: Rule): string {
	return rule.kind === "field" ? `(${rule.expr})` : `[(${rule.expr})]`;
}

/**
 * The expression that gives a rule's values on a source item: its own value
 * when no collection is above it, else `{"i": [(collection).{"v": (rule)}]}`,
 * a level for each collection, as the compiled transform evaluates it.
 */
export function probeExpression(rule: Rule, rules: Rules): string {
	const chain = collectionChain(rule.ptr, rules);
	if (chain.length === 0) return ruleValue(rule);
	return chain.reduceRight(
		(probe, collection) => `{"i": [(${collection.expr}).${probe}]}`,
		`{"v": ${ruleValue(rule)}}`,
	);
}

/** One expression giving every rule's probe, keyed by its pointer. */
export function probesExpression(list: readonly Rule[], rules: Rules): string {
	const entries = list.map((rule) => `${JSON.stringify(rule.ptr)}: ${probeExpression(rule, rules)}`);
	return `{${entries.join(", ")}}`;
}

/** The values in a probe's result, `depth` being how many collections are above the rule. */
export function probeValues(result: unknown, defined: boolean, depth: number): ProbeValue[] {
	if (depth === 0) return [{ at: [], value: defined ? result : null, defined }];
	const values: ProbeValue[] = [];
	const walk = (node: unknown, at: number[], level: number): void => {
		const items = isRecord(node) && Array.isArray(node["i"]) ? node["i"] : [];
		for (const [index, item] of items.entries()) {
			if (level < depth) {
				walk(item, [...at, index], level + 1);
				continue;
			}
			const has = isRecord(item) && "v" in item;
			values.push({ at: [...at, index], value: has ? item["v"] : null, defined: has });
		}
	};
	walk(result, [], 1);
	return values;
}

/** Whether values a rule gave fit the target field (a collection's items are checked by their own rules). */
export function valueCompatibility(node: TreeNode, values: readonly unknown[]): Compatibility {
	if (node.kind === "collection" || values.length === 0) return { status: "ok" };
	if (node.kind === "scalar_collection") {
		const items = inferFromSamples(values.flatMap((value) => (Array.isArray(value) ? value : [value])));
		return items
			? compatibility(items, { types: node.itemTypes ?? [], nullable: false, format: node.format })
			: { status: "ok" };
	}
	const type = inferFromSamples(values);
	return type
		? compatibility(type, { types: node.types, nullable: node.nullable, format: node.format })
		: { status: "ok" };
}

// sources

/** Every value at `pointer` in `item`, with collection items implied (as a source tree's pointers are). */
export function valuesAt(item: unknown, pointer: string): unknown[] {
	let values = [item];
	for (const segment of fromPointer(pointer)) {
		values = values
			.flatMap((value) => (Array.isArray(value) ? value : [value]))
			.filter(isRecord)
			.filter((value) => segment in value)
			.map((value) => value[segment]);
	}
	return values;
}

function isArraySchema(schema: Record<string, unknown>): boolean {
	const type = schema["type"];
	return type === "array" || (Array.isArray(type) && type.includes("array")) || "items" in schema;
}

/** The schema of the property or array item `segment` names in `schema`, looking into its parts. */
function childSchema(schema: unknown, segment: string): unknown {
	if (!isRecord(schema)) return undefined;
	if (isArraySchema(schema) && /^(?:0|[1-9]\d*)$/.test(segment)) return schema["items"] ?? {};
	const properties = schema["properties"];
	if (isRecord(properties) && segment in properties) return properties[segment];
	for (const keyword of ["allOf", "oneOf", "anyOf"]) {
		const parts = schema[keyword];
		for (const part of Array.isArray(parts) ? parts : []) {
			const found = childSchema(part, segment);
			if (found !== undefined) return found;
		}
	}
	return undefined;
}

/**
 * The schema of one item of a response, as an import reads its items: the
 * schema at the Items Pointer, and its items when that is an array (the
 * server's read_items). `{}` when the pointer leads nowhere in the schema.
 */
export function itemsSchema(schema: unknown, itemsPointer: string): unknown {
	let node: unknown = schema;
	try {
		for (const segment of fromPointer(itemsPointer)) node = childSchema(node, segment);
	} catch {
		return {};
	}
	if (!isRecord(node)) return {};
	return isArraySchema(node) ? (node["items"] ?? {}) : node;
}

// counts and findings

function isMapped(pointer: string, rules: Rules): boolean {
	if (rules.has(pointer)) return true;
	for (const other of rules.keys()) if (other.startsWith(`${pointer}/`)) return true;
	return false;
}

/**
 * The required fields of `target` no rule fills: at its root, in the objects
 * rules fill field by field, and in the items of the mapped collections.
 */
export function requiredUnmapped(target: TreeNode, rules: Rules): TreeNode[] {
	const found: TreeNode[] = [];
	const walk = (node: TreeNode): void => {
		for (const child of node.children) {
			if (child.required === "hard" && !isMapped(child.pointer, rules)) found.push(child);
			const kind = rules.get(child.pointer)?.kind;
			const fieldByField = kind === undefined && child.kind === "object" && isMapped(child.pointer, rules);
			if (kind === "collection" || fieldByField) walk(child);
		}
	};
	const rootKind = rules.get(target.pointer)?.kind;
	if (rootKind === undefined || rootKind === "collection") walk(target);
	return found;
}

/** The fields a rule can fill: the mappable nodes, and the root when it is a collection. */
export function targetFields(target: TreeNode): TreeNode[] {
	const root = target.kind === "collection" || target.kind === "scalar_collection" ? [target] : [];
	// the variants of a group can repeat a pointer: one field
	const seen = new Set<string>();
	const fields: TreeNode[] = [];
	for (const node of [...root, ...mappableNodes(target)]) {
		if (seen.has(node.pointer)) continue;
		seen.add(node.pointer);
		fields.push(node);
	}
	return fields;
}

/** How many of the target's fields have a rule, of how many. */
export function mappingCounts(target: TreeNode, rules: Rules): { mapped: number; total: number } {
	const fields = targetFields(target);
	return { mapped: fields.filter((node) => rules.has(node.pointer)).length, total: fields.length };
}

function diagnostic(
	rule: string,
	severity: Severity,
	code: string,
	message: string,
	item?: number,
): Diagnostic {
	const found: Diagnostic = { rule, path: rule, severity, code, message, origin: "client" };
	if (item !== undefined) found.item = item;
	return found;
}

/** The syntax error of an expression, if it has one. */
export function syntaxError(expression: string): EvalError | undefined {
	try {
		jsonata(expression);
		return undefined;
	} catch (error) {
		const fields = isRecord(error) ? error : {};
		return {
			code: typeof fields["code"] === "string" ? fields["code"] : "error",
			message: typeof fields["message"] === "string" ? fields["message"] : String(error),
		};
	}
}

/**
 * What the rules show without a sample, as the server's static checks find it:
 * the rules that don't compile, the expressions that don't parse, the required
 * fields no rule fills, and the rules for a field the target doesn't have.
 */
export function ruleDiagnostics(target: TreeNode, rules: Rules, compiled: Compiled): Diagnostic[] {
	const found = compiled.errors.map((error) => diagnostic(error.rule, "error", error.code, error.message));
	const fields = new Set(targetFields(target).map((node) => node.pointer));
	for (const rule of rules.values()) {
		const error = rule.expr.trim() ? syntaxError(rule.expr) : undefined;
		if (error) found.push(diagnostic(rule.ptr, "error", `jsonata.${error.code}`, error.message));
		if (!fields.has(rule.ptr)) {
			found.push(
				diagnostic(rule.ptr, "warning", "rule-unknown", "The target has no field here: clear the rule"),
			);
		}
	}
	for (const node of requiredUnmapped(target, rules)) {
		found.push(diagnostic(node.pointer, "error", "required-unmapped", "Required, and no rule fills it"));
	}
	return found;
}

/** A rule's results on the sample: its values, and the error it stopped with on each item it failed on. */
export interface RuleResults {
	values: ProbeValue[];
	/** The values by sample item. */
	byItem: ProbeValue[][];
	errors: { item: number; error: EvalError }[];
}

/** What a rule's probe gave on one item: its result, or the error it stopped with. */
export type ProbeAnswer = { ok: true; value: unknown; defined: boolean } | { ok: false; error: EvalError };

/** A rule's answer out of `probesExpression`'s result on an item, when that evaluation succeeded. */
export function answerOf(combined: EvalResponse | undefined, pointer: string): ProbeAnswer | undefined {
	if (!combined?.ok) return undefined;
	const value = isRecord(combined.value) ? combined.value : {};
	return { ok: true, value: value[pointer] ?? null, defined: pointer in value };
}

/** A rule's results from its answers, one per sample item. */
export function ruleResults(rule: Rule, rules: Rules, answers: readonly ProbeAnswer[]): RuleResults {
	const depth = collectionChain(rule.ptr, rules).length;
	const results: RuleResults = { values: [], byItem: [], errors: [] };
	for (const [item, answer] of answers.entries()) {
		if (!answer.ok) {
			results.byItem.push([]);
			results.errors.push({ item, error: answer.error });
			continue;
		}
		const values = probeValues(answer.value, answer.defined, depth);
		results.byItem.push(values);
		results.values.push(...values);
	}
	return results;
}

/** What a rule's results show: the items it failed on, and values that don't fit the field. */
export function resultDiagnostics(
	node: TreeNode | undefined,
	rule: Rule,
	results: RuleResults,
): Diagnostic[] {
	const found = results.errors.map(({ item, error }) =>
		diagnostic(rule.ptr, "error", `eval.${error.code}`, error.message, item),
	);
	if (!node) return found;
	const defined = results.values.filter((value) => value.defined).map((value) => value.value);
	const fit = valueCompatibility(node, defined);
	if (fit.status === "mismatch")
		found.push(diagnostic(rule.ptr, "error", "type-mismatch", `The value ${fit.message}`));
	if (fit.status === "coerced")
		found.push(diagnostic(rule.ptr, "warning", "type-coerced", `The value ${fit.message}`));
	return found;
}

/**
 * A JSON Schema validator for the objects the transform maps to, or undefined
 * when the schema can't be compiled. Formats are left to the server, which
 * knows what Frappe parses; a `$schema` naming OpenAPI's dialect, which ajv
 * doesn't know, is dropped.
 */
export function schemaValidator(schema: unknown): ValidateFunction | undefined {
	if (!isRecord(schema)) return undefined;
	const { $schema: _dialect, ...rest } = schema;
	try {
		return new Ajv2020({ allErrors: true, strict: false, validateFormats: false }).compile(rest);
	} catch {
		return undefined;
	}
}

/**
 * The diagnostics as the editor lists them: one for each rule, path, code and
 * sample item, the first of any the browser and the server both found.
 */
export function withoutRepeats(diagnostics: readonly Diagnostic[]): Diagnostic[] {
	const seen = new Set<string>();
	return diagnostics.filter((found) => {
		const key = JSON.stringify([found.rule, found.path, found.code, found.item ?? null]);
		if (seen.has(key)) return false;
		seen.add(key);
		return true;
	});
}

/** Text to insert into an expression: the caret (or the selection, wrapped) goes between `before` and `after`. */
export interface Snippet {
	before: string;
	after: string;
}

/**
 * `expression` with `snippet` put in place of the text from `start` to `end`,
 * that text wrapped in it (selecting `price` and inserting `$number(…)` gives
 * `$number(price)`), and where the caret goes: inside the snippet's hole, or
 * after what it wrapped.
 */
export function insertSnippet(
	expression: string,
	start: number,
	end: number,
	snippet: Snippet,
): { expression: string; caret: number } {
	const from = Math.max(0, Math.min(start, end, expression.length));
	const to = Math.min(Math.max(start, end), expression.length);
	const wrapped = expression.slice(from, to);
	const caret = from + snippet.before.length + wrapped.length;
	return {
		expression: `${expression.slice(0, from)}${snippet.before}${wrapped}${snippet.after}${expression.slice(to)}`,
		caret,
	};
}

/** The pointers given and every pointer above each: the rows a filtered tree shows. */
export function withAncestors(pointers: Iterable<string>): Set<string> {
	const all = new Set<string>();
	for (const pointer of pointers) {
		for (let current = pointer; !all.has(current); current = parentPointer(current)) {
			all.add(current);
			if (current === "") break;
		}
	}
	return all;
}

/**
 * The row that shows the field at `pointer` (or the nearest field above it) in
 * a tree of `fields` whose open groups are `expanded`: its own row, or that of
 * the closed group it is in. Undefined when no field of the tree holds it.
 */
export function shownRow(
	pointer: string,
	fields: ReadonlySet<string>,
	expanded: ReadonlySet<string>,
): string | undefined {
	let field = pointer;
	while (!fields.has(field)) {
		if (field === "") return undefined;
		field = parentPointer(field);
	}
	const segments = fromPointer(field);
	for (let length = 1; length < segments.length; length++) {
		const group = toPointer(segments.slice(0, length));
		if (fields.has(group) && !expanded.has(group)) return group;
	}
	return field;
}

/**
 * The source fields each rule reads, by the rule's pointer: a wildcard's read
 * stops at the field above it. A rule under a collection that is more than a
 * path reads from items the editor can't place, and is left out.
 */
export function ruleReads(rules: Rules): Map<string, string[]> {
	const found = new Map<string, string[]>();
	for (const rule of rules.values()) {
		const context = sourceContext(rule.ptr, rules);
		if (context === undefined) continue;
		const result = readsOf(rule.expr, { context });
		if (!result.ok) continue;
		const pointers = result.reads.map((read) => {
			const cut = read.segments.findIndex((segment) => segment === "*" || segment === "**");
			return cut === -1 ? read.pointer : toPointer(read.segments.slice(0, cut));
		});
		found.set(rule.ptr, [...new Set(pointers)]);
	}
	return found;
}

/** A line between the trees: from a source row to a target row, for the rules it stands for. */
export interface RuleLink {
	source: string;
	target: string;
	/** A collection rule's line, a path's, or a formula's (the first rule's, when several share it). */
	kind: "path" | "formula" | "collection";
	rules: string[];
}

/**
 * The lines from the row of each field a rule reads to the row of the field it
 * fills, a row being the field's own or that of the closed group holding it
 * (`sourceRow`, `targetRow`: undefined when the field isn't shown).
 */
export function ruleLinks(
	rules: Rules,
	reads: ReadonlyMap<string, readonly string[]>,
	sourceRow: (pointer: string) => string | undefined,
	targetRow: (pointer: string) => string | undefined,
): RuleLink[] {
	const links = new Map<string, RuleLink>();
	for (const rule of rules.values()) {
		const target = targetRow(rule.ptr);
		if (target === undefined) continue;
		let kind: RuleLink["kind"] = simplePath(rule.expr) ? "path" : "formula";
		if (rule.kind === "collection") kind = "collection";
		for (const read of reads.get(rule.ptr) ?? []) {
			const source = sourceRow(read);
			if (source === undefined) continue;
			const key = JSON.stringify([source, target]);
			const known = links.get(key);
			if (known) {
				if (!known.rules.includes(rule.ptr)) known.rules.push(rule.ptr);
			} else links.set(key, { source, target, kind, rules: [rule.ptr] });
		}
	}
	return [...links.values()];
}

/**
 * What the compiled transform's results show, one per sample item: the error
 * an item stopped with (unless a rule's own results already place it), and
 * what the target's schema finds in what it maps to, at `severity`.
 */
export function outputDiagnostics(
	outputs: readonly EvalResponse[],
	validate: ValidateFunction | undefined,
	options: { target: TreeNode; rules: Rules; severity: Severity; placed: readonly Diagnostic[] },
): Diagnostic[] {
	const found: Diagnostic[] = [];
	for (const [item, output] of outputs.entries()) {
		if (!output.ok) {
			const placed = options.placed.some((d) => d.item === item && d.code.startsWith("eval."));
			if (!placed)
				found.push(diagnostic("", "error", `eval.${output.error.code}`, output.error.message, item));
			continue;
		}
		if (!validate || validate(output.value)) continue;
		found.push(
			...fromAjvErrors(validate.errors, {
				item,
				rules: options.rules.keys(),
				tree: options.target,
				severity: options.severity,
			}),
		);
	}
	return found;
}
