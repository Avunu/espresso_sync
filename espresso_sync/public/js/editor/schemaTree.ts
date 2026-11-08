// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * One tree model for both ends of a transform.
 *
 * The source or target of a transform is either an OpenAPI operation's
 * request or response body (plain JSON Schema in the OAS 3.1 dialect, from the
 * server's get_operation_schema) or a DocType (the JSON Schema of
 * doctype_json_schema, whose contract is in the server's schema module). The
 * editor draws both the same way, so each adapter here turns its schema into
 * the same `TreeNode`s:
 *
 * - `allOf` parts are merged into one node.
 * - `oneOf` / `anyOf` become a variant group, except where the variants only
 *   differ by `null` (a nullable value) or are all scalars (a union type).
 * - A `$ref` back into a schema already being expanded, or the server's
 *   `{"x-cycle": "<ref>"}` marker, becomes a `cycle` node instead of recursing.
 * - An array of scalars is a `scalar_collection`; an array of objects is a
 *   `collection` whose children are the item's fields.
 * - An object with no declared properties (a dictionary) is a `map` leaf.
 * - Requiredness has tiers: `hard` (the write fails without it), `server`
 *   (Frappe fills it in: a warning when unmapped) or none. A DocType's
 *   schema has tiers in its insert mode only.
 * - A DocType's `doctype` property (every mode has it, the DocType's name as
 *   its `const`) is left out of the tree. Its read mode's standard fields
 *   (`name`, `modified`, …) are read-only fields like any other; a Check is
 *   one field of types `integer` and `boolean`.
 *
 * Pointers follow pointer.ts, with collection items implied, so a node's
 * pointer is exactly the `ptr` a rule for it is keyed by.
 */

import { fromPointer, toPointer } from "./pointer.ts";
import { jsonType } from "./typeInfer.ts";

export type NodeKind = "object" | "collection" | "scalar_collection" | "field" | "map" | "variants" | "cycle";

export type RequiredTier = "hard" | "server" | null;

/** What doctype_json_schema says about a DocType field (its `x-frappe`). */
export interface FrappeFieldInfo {
	fieldtype: string | undefined;
	options: string | undefined;
	/** The DocType a Link points to. */
	link: string | undefined;
	/** For a Dynamic Link: the field that holds the DocType. */
	dynamicLink: string | undefined;
	custom: boolean;
}

export interface Variant {
	label: string;
	node: TreeNode;
}

export interface TreeNode {
	/** The property name; `""` for the root. */
	key: string;
	pointer: string;
	kind: NodeKind;
	/** The JSON types the value may have (`[]`: anything). A collection's is `["array"]`. */
	types: string[];
	nullable: boolean;
	required: RequiredTier;
	readOnly: boolean;
	title?: string;
	description?: string;
	format?: string;
	enum?: unknown[];
	/** Object and collection: the fields (for a collection, of each item). */
	children: TreeNode[];
	/** Whether an object (or a collection's items) takes keys beyond `children`. */
	open: boolean;
	/** A variant group: the shapes the value (or each item) may take. */
	variants?: Variant[];
	variantMode?: "oneOf" | "anyOf";
	/** A scalar collection's item types, or a map's value types. */
	itemTypes?: string[];
	/** A cycle node: the schema it would have expanded again. */
	cycle?: string;
	frappe?: FrappeFieldInfo;
}

type Schema = Record<string, unknown>;

const SCALAR_TYPES = new Set(["string", "number", "integer", "boolean", "null"]);
const MAX_DEPTH = 64;

interface BuildContext {
	/** The document `$ref`s resolve against (the whole OpenAPI document, or the schema itself). */
	root: unknown;
	/** The `$ref`s being expanded on the way down, to catch recursion. */
	refs: readonly string[];
	doctype: boolean;
	depth: number;
}

function isSchema(value: unknown): value is Schema {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asSchema(value: unknown): Schema {
	// `true` and `{}` accept anything; `false` accepts nothing, which the editor can only show as anything.
	return isSchema(value) ? value : {};
}

function stringOf(value: unknown): string | undefined {
	return typeof value === "string" ? value : undefined;
}

function schemaList(value: unknown): Schema[] {
	return Array.isArray(value) ? value.map(asSchema) : [];
}

function stringList(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Resolve a local `$ref` (`#/components/schemas/Order`) against the root document. */
function resolveRef(root: unknown, ref: string): Schema | undefined {
	if (ref !== "#" && !ref.startsWith("#/")) return undefined;
	let node: unknown = root;
	for (const segment of fromPointer(decodeURIComponent(ref.slice(1)))) {
		if (!isSchema(node) && !Array.isArray(node)) return undefined;
		node = (node as Record<string, unknown>)[segment];
	}
	return isSchema(node) ? node : undefined;
}

/** The declared JSON types, `nullable` (OAS 3.0) folded in as `"null"`. */
function declaredTypes(schema: Schema): string[] {
	const type = schema["type"];
	const types = typeof type === "string" ? [type] : stringList(type);
	if (schema["nullable"] === true && types.length > 0 && !types.includes("null")) types.push("null");
	return types;
}

/** The types a schema implies when it doesn't say: by its keywords, or by its enum/const values. */
function impliedTypes(schema: Schema): string[] {
	const declared = declaredTypes(schema);
	if (declared.length > 0) return declared;
	if (isSchema(schema["properties"]) || "additionalProperties" in schema || "patternProperties" in schema) {
		return ["object"];
	}
	if ("items" in schema || "prefixItems" in schema) return ["array"];
	const values = Array.isArray(schema["enum"]) ? schema["enum"] : "const" in schema ? [schema["const"]] : [];
	return [...new Set(values.map(jsonType))];
}

function intersectTypes(a: string[], b: string[]): string[] {
	if (a.length === 0) return b;
	if (b.length === 0) return a;
	const both = a.filter((type) => b.includes(type) || (type === "integer" && b.includes("number")));
	for (const type of b)
		if (type === "integer" && a.includes("number") && !both.includes(type)) both.push(type);
	return both;
}

/** Follow `$ref`s at the top of a schema, keeping any keywords written beside the `$ref` (OAS 3.1). */
function deref(schema: Schema, ctx: BuildContext): { schema: Schema; ref?: string; cycle?: string } {
	let current = schema;
	const seen: string[] = [];
	for (let ref = stringOf(current["$ref"]); ref !== undefined; ref = stringOf(current["$ref"])) {
		if (ctx.refs.includes(ref) || seen.includes(ref)) return { schema: current, cycle: ref };
		const target = resolveRef(ctx.root, ref);
		seen.push(ref);
		const { $ref: _ref, ...siblings } = current;
		current = target ? { ...target, ...siblings } : siblings;
	}
	const ref = seen.at(-1);
	return ref === undefined ? { schema: current } : { schema: current, ref };
}

/** Merge the parts of an `allOf` (and the schema it sits in) into one schema. */
function mergeAllOf(schema: Schema, ctx: BuildContext): Schema {
	const parts = schemaList(schema["allOf"]);
	if (parts.length === 0) return schema;
	const { allOf: _allOf, ...outer } = schema;
	let merged: Schema = {};
	for (const part of [...parts.map((p) => mergeAllOf(deref(p, ctx).schema, ctx)), outer]) {
		merged = mergeTwo(merged, part);
	}
	return merged;
}

function mergeTwo(a: Schema, b: Schema): Schema {
	const merged: Schema = { ...a, ...b };
	const types = intersectTypes(declaredTypes(a), declaredTypes(b));
	if (types.length > 0) merged["type"] = types.length === 1 ? types[0] : types;
	delete merged["nullable"];
	const propsA = asSchema(a["properties"]);
	const propsB = asSchema(b["properties"]);
	if ("properties" in a || "properties" in b) {
		const properties: Schema = { ...propsA };
		for (const [key, value] of Object.entries(propsB)) {
			properties[key] = key in propsA ? { allOf: [propsA[key], value] } : value;
		}
		merged["properties"] = properties;
	}
	const required = [...new Set([...stringList(a["required"]), ...stringList(b["required"])])];
	if (required.length > 0) merged["required"] = required;
	// Either side closing the object closes the merge.
	if (a["additionalProperties"] === false || b["additionalProperties"] === false) {
		merged["additionalProperties"] = false;
	}
	return merged;
}

function isNullSchema(schema: Schema): boolean {
	const types = declaredTypes(schema);
	return (types.length === 1 && types[0] === "null") || ("const" in schema && schema["const"] === null);
}

function frappeInfo(schema: Schema): FrappeFieldInfo | undefined {
	const meta = schema["x-frappe"];
	if (!isSchema(meta)) return undefined;
	return {
		fieldtype: stringOf(meta["fieldtype"]),
		options: stringOf(meta["options"]),
		link: stringOf(meta["link"]),
		dynamicLink: stringOf(meta["dynamic_link"]),
		custom: meta["custom"] === true,
	};
}

function requiredTier(schema: Schema, inParentRequired: boolean, ctx: BuildContext): RequiredTier {
	const meta = schema["x-frappe"];
	if (ctx.doctype && isSchema(meta) && "required" in meta) {
		const tier = meta["required"];
		return tier === "hard" || tier === "server" ? tier : null;
	}
	return inParentRequired ? "hard" : null;
}

function baseNode(
	key: string,
	segments: readonly string[],
	schema: Schema,
	required: RequiredTier,
): TreeNode {
	const types = impliedTypes(schema);
	const meta = schema["x-frappe"];
	const node: TreeNode = {
		key,
		pointer: toPointer(segments),
		kind: "field",
		types: types.filter((type) => type !== "null"),
		nullable: types.includes("null"),
		required,
		readOnly: schema["readOnly"] === true || (isSchema(meta) && meta["read_only"] === true),
		children: [],
		open: false,
	};
	const title = stringOf(schema["title"]);
	const description = stringOf(schema["description"]);
	const format = stringOf(schema["format"]);
	if (title !== undefined) node.title = title;
	if (description !== undefined) node.description = description;
	if (format !== undefined) node.format = format;
	if (Array.isArray(schema["enum"])) node.enum = schema["enum"];
	else if ("const" in schema) node.enum = [schema["const"]];
	const frappe = frappeInfo(schema);
	if (frappe) node.frappe = frappe;
	return node;
}

function variantLabel(schema: Schema, ref: string | undefined, index: number): string {
	const title = stringOf(schema["title"]);
	if (title) return title;
	if (ref) return ref.slice(ref.lastIndexOf("/") + 1);
	return `Option ${index + 1}`;
}

/** Build the node for `schema` at `segments` (array items share their array's segments). */
function build(
	raw: unknown,
	key: string,
	segments: readonly string[],
	inParentRequired: boolean,
	ctx: BuildContext,
): TreeNode {
	const marker = isSchema(raw) ? stringOf(raw["x-cycle"]) : undefined;
	const resolved = deref(asSchema(raw), ctx);
	const cycle = marker ?? resolved.cycle;
	if (cycle !== undefined || ctx.depth > MAX_DEPTH) {
		const node = baseNode(
			key,
			segments,
			resolved.schema,
			requiredTier(resolved.schema, inParentRequired, ctx),
		);
		node.kind = "cycle";
		node.cycle = cycle ?? "(too deep)";
		return node;
	}
	const inner: BuildContext = {
		...ctx,
		refs: resolved.ref === undefined ? ctx.refs : [...ctx.refs, resolved.ref],
		depth: ctx.depth + 1,
	};
	let schema = mergeAllOf(resolved.schema, inner);

	// oneOf / anyOf: nullable, a union of scalars, a single shape, or a variant group.
	const mode = "oneOf" in schema ? "oneOf" : "anyOf" in schema ? "anyOf" : undefined;
	let options: { schema: Schema; ref: string | undefined }[] = [];
	let nullable = false;
	if (mode) {
		const { [mode]: list, ...rest } = schema;
		const all = schemaList(list).map((option) => {
			const d = deref(option, inner);
			return { schema: mergeAllOf(d.schema, inner), ref: d.ref ?? d.cycle };
		});
		nullable = all.some((option) => isNullSchema(option.schema));
		options = all.filter((option) => !isNullSchema(option.schema));
		schema = rest;
		const scalars = options.every((option) => impliedTypes(option.schema).every((t) => SCALAR_TYPES.has(t)));
		if (options.length === 1 || (options.length > 1 && scalars)) {
			// Fold the option(s) into the schema: a nullable value, or one scalar field of several types.
			const types = [...new Set(options.flatMap((option) => impliedTypes(option.schema)))];
			// The field takes a fixed set of values only when every option does: one
			// unconstrained option (any integer, any string) accepts values no enum lists.
			const allowed = options.map((option) =>
				Array.isArray(option.schema["enum"])
					? option.schema["enum"]
					: "const" in option.schema
						? [option.schema["const"]]
						: undefined,
			);
			const only = options.length === 1 ? options[0] : undefined;
			schema = only ? mergeTwo(only.schema, rest) : { ...rest };
			if (!only && types.length > 0) schema["type"] = types;
			if (!only && allowed.every((values) => values !== undefined)) schema["enum"] = allowed.flat();
			options = [];
		}
	}

	const required = requiredTier(schema, inParentRequired, ctx);
	const node = baseNode(key, segments, schema, required);
	if (nullable) node.nullable = true;
	const types = node.types;

	if (options.length > 1 && mode) {
		node.variants = options.map((option, index) => {
			const refs = option.ref === undefined ? inner.refs : [...inner.refs, option.ref];
			return {
				label: variantLabel(option.schema, option.ref, index),
				node: build(option.schema, key, segments, inParentRequired, { ...inner, refs }),
			};
		});
		node.variantMode = mode;
		node.kind = isSchema(schema["properties"]) ? "object" : "variants";
		if (node.kind === "object") fillObject(node, schema, segments, inner);
		return node;
	}

	if (types.length === 1 && types[0] === "array") {
		return fillArray(node, schema, key, segments, inParentRequired, inner);
	}
	if (types.length === 1 && types[0] === "object") {
		fillObject(node, schema, segments, inner);
		return node;
	}
	return node;
}

function fillObject(node: TreeNode, schema: Schema, segments: readonly string[], ctx: BuildContext): void {
	const properties = schema["properties"];
	const additional = schema["additionalProperties"];
	const open = additional !== false;
	if (!isSchema(properties) || Object.keys(properties).length === 0) {
		if (node.kind === "variants") return;
		// A dictionary (or a free-form object): one leaf, mapped as a whole.
		node.kind = "map";
		node.open = open;
		const values = isSchema(additional) ? impliedTypes(deref(additional, ctx).schema) : [];
		node.itemTypes = values;
		return;
	}
	if (node.kind !== "variants") node.kind = "object";
	node.open = open && "additionalProperties" in schema;
	const required = new Set(stringList(schema["required"]));
	node.children = Object.entries(properties)
		// A document's `doctype` names its DocType: the sync sets it, no rule reads or fills it.
		.filter(([name]) => !(ctx.doctype && name === "doctype"))
		.map(([name, child]) => build(child, name, [...segments, name], required.has(name), ctx));
}

function fillArray(
	node: TreeNode,
	schema: Schema,
	key: string,
	segments: readonly string[],
	inParentRequired: boolean,
	ctx: BuildContext,
): TreeNode {
	const items = "items" in schema ? schema["items"] : schemaList(schema["prefixItems"])[0];
	const item = build(items ?? {}, key, segments, inParentRequired, ctx);
	// An array described only on its items (`items: {$ref, description}`) shows the items' words.
	if (node.title === undefined && item.title !== undefined) node.title = item.title;
	if (node.description === undefined && item.description !== undefined) node.description = item.description;
	switch (item.kind) {
		case "object":
		case "variants":
		case "cycle":
			node.kind = "collection";
			node.children = item.children;
			node.open = item.open;
			if (item.variants) node.variants = item.variants;
			if (item.variantMode) node.variantMode = item.variantMode;
			if (item.cycle !== undefined) node.cycle = item.cycle;
			return node;
		case "field":
		case "map":
			node.kind = "scalar_collection";
			node.itemTypes = item.kind === "map" ? ["object"] : item.types;
			if (item.enum) node.enum = item.enum;
			if (item.format !== undefined) node.format = item.format;
			return node;
		default:
			// An array of arrays: one leaf, mapped as a whole.
			node.kind = "field";
			return node;
	}
}

export interface OpenApiOptions {
	/** The whole OpenAPI document, for `$ref`s the schema still carries (`#/components/schemas/…`). */
	document?: unknown;
}

/** The tree of an OpenAPI operation's body schema (OAS 3.1, or 3.0's `nullable`). */
export function fromOpenApiSchema(schema: unknown, options: OpenApiOptions = {}): TreeNode {
	const ctx: BuildContext = { root: options.document ?? schema, refs: [], doctype: false, depth: 0 };
	return build(schema, "", [], false, ctx);
}

/** The tree of a DocType, from doctype_json_schema (child tables are collections). */
export function fromDocTypeSchema(schema: unknown): TreeNode {
	const ctx: BuildContext = { root: schema, refs: [], doctype: true, depth: 0 };
	return build(schema, "", [], false, ctx);
}

/** Every node under (and including) `root`, depth first; a variant's nodes come after their group. */
export function* walkTree(root: TreeNode): Generator<TreeNode> {
	yield root;
	for (const child of root.children) yield* walkTree(child);
	for (const variant of root.variants ?? []) {
		for (const child of variant.node.children) yield* walkTree(child);
	}
}

/** The node at a pointer (the first one, if variants repeat it). */
export function findNode(root: TreeNode, pointer: string): TreeNode | undefined {
	for (const node of walkTree(root)) if (node.pointer === pointer) return node;
	return undefined;
}

/** The kind of rule that fills a node, or undefined for a node a rule can't target. */
export function ruleKind(node: TreeNode): "field" | "collection" | "scalar_collection" | undefined {
	switch (node.kind) {
		case "field":
		case "map":
			return "field";
		case "collection":
			return "collection";
		case "scalar_collection":
			return "scalar_collection";
		default:
			return undefined;
	}
}

/** The nodes a rule can fill: leaves, scalar collections and collections (not the root). */
export function mappableNodes(root: TreeNode): TreeNode[] {
	return [...walkTree(root)].filter((node) => node !== root && ruleKind(node) !== undefined);
}
