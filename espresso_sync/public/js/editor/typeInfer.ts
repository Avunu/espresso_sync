// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * JSON-Schema-ish types inferred from values.
 *
 * Two uses in the editor: a pasted or fetched sample with no schema of its
 * own still gets a source tree (infer from the sample, then `toJsonSchema` and
 * schemaTree.ts), and a rule's preview shows what type its expression actually
 * produced across the sample's items (`inferResult`), next to the type the
 * target field wants (`compatibility`).
 */

export interface InferredType {
	/** The JSON types seen, sorted; `integer` is folded into `number` when both occur. */
	types: string[];
	/** `date`, `date-time` or `time`, when every string seen has that shape. */
	format?: string;
	/** Objects: each key's type, over every object seen. */
	properties?: Record<string, InferredType>;
	/** Objects: the keys every object seen had. */
	required?: string[];
	/** Arrays: the type of their items, all arrays together. */
	items?: InferredType;
	/** A whole number beyond ±2^53 was seen: JSON parsing has already rounded it. */
	unsafeInteger?: boolean;
	/** How many values were merged into this. */
	count: number;
}

/** The JSON type of a value: `integer` for whole numbers, `undefined` and `function` as JavaScript has them. */
export function jsonType(value: unknown): string {
	if (value === null) return "null";
	if (Array.isArray(value)) return "array";
	if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
	return typeof value;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$/;
const TIME = /^\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

/** The string format a value looks like: what Frappe's Date, Datetime and Time fields hold. */
export function stringFormat(value: string): string | undefined {
	if (DATE.test(value)) return "date";
	if (DATE_TIME.test(value)) return "date-time";
	if (TIME.test(value)) return "time";
	return undefined;
}

function normaliseTypes(types: Iterable<string>): string[] {
	const set = new Set(types);
	if (set.has("integer") && set.has("number")) set.delete("integer");
	return [...set].sort();
}

/** The type of one value. */
export function inferType(value: unknown): InferredType {
	const type = jsonType(value);
	const inferred: InferredType = { types: [type], count: 1 };
	if (type === "integer" && !Number.isSafeInteger(value)) inferred.unsafeInteger = true;
	if (typeof value === "string") {
		const format = stringFormat(value);
		if (format) inferred.format = format;
	}
	if (Array.isArray(value)) {
		const items = value.map(inferType);
		const merged = items.reduce<InferredType | undefined>(
			(acc, item) => (acc ? mergeTypes(acc, item) : item),
			undefined,
		);
		if (merged) inferred.items = merged;
		if (merged?.unsafeInteger) inferred.unsafeInteger = true;
	} else if (type === "object") {
		const record = value as Record<string, unknown>;
		const properties: Record<string, InferredType> = {};
		for (const [key, child] of Object.entries(record)) {
			if (child === undefined) continue;
			const childType = inferType(child);
			properties[key] = childType;
			if (childType.unsafeInteger) inferred.unsafeInteger = true;
		}
		inferred.properties = properties;
		inferred.required = Object.keys(properties).sort();
	}
	return inferred;
}

/** One type covering both: types unioned, keys required only where both had them. */
export function mergeTypes(a: InferredType, b: InferredType): InferredType {
	const merged: InferredType = { types: normaliseTypes([...a.types, ...b.types]), count: a.count + b.count };
	const aStrings = a.types.includes("string");
	const bStrings = b.types.includes("string");
	if (aStrings && bStrings) {
		if (a.format !== undefined && a.format === b.format) merged.format = a.format;
	} else if (aStrings || bStrings) {
		const format = aStrings ? a.format : b.format;
		if (format !== undefined) merged.format = format;
	}
	if (a.unsafeInteger || b.unsafeInteger) merged.unsafeInteger = true;
	if (a.items && b.items) merged.items = mergeTypes(a.items, b.items);
	else if (a.items ?? b.items) merged.items = (a.items ?? b.items) as InferredType;
	if (a.properties || b.properties) {
		const properties: Record<string, InferredType> = { ...a.properties };
		for (const [key, type] of Object.entries(b.properties ?? {})) {
			const existing = properties[key];
			properties[key] = existing ? mergeTypes(existing, type) : type;
		}
		merged.properties = properties;
		// A key is required only when every object on both sides had it.
		const aRequired = a.properties ? new Set(a.required) : undefined;
		const bRequired = b.properties ? new Set(b.required) : undefined;
		merged.required = Object.keys(properties)
			.filter((key) => (aRequired ? aRequired.has(key) : true) && (bRequired ? bRequired.has(key) : true))
			.sort();
	}
	return merged;
}

/** The type of several samples together (each one a value of the same field or document). */
export function inferFromSamples(values: Iterable<unknown>): InferredType | undefined {
	let merged: InferredType | undefined;
	for (const value of values) {
		const type = inferType(value);
		merged = merged ? mergeTypes(merged, type) : type;
	}
	return merged;
}

/**
 * The type of what a JSONata expression returned. Nothing (`undefined`) counts
 * as the type `undefined`, so a rule that yields nothing for some items shows as
 * `string | undefined`. A sequence is an array, as it is once serialised.
 */
export function inferResult(result: unknown): InferredType {
	return inferType(result);
}

/** A JSON Schema (draft 2020-12 keywords) for an inferred type, for schemaTree.ts. */
export function toJsonSchema(type: InferredType): Record<string, unknown> {
	const types = type.types.filter((t) => t !== "undefined" && t !== "function");
	const schema: Record<string, unknown> = {};
	if (types.length === 1) schema["type"] = types[0];
	else if (types.length > 1) schema["type"] = types;
	if (type.format !== undefined) schema["format"] = type.format;
	if (type.properties) {
		const properties: Record<string, unknown> = {};
		for (const [key, child] of Object.entries(type.properties)) properties[key] = toJsonSchema(child);
		schema["properties"] = properties;
		if (type.required && type.required.length > 0) schema["required"] = type.required;
	}
	if (type.items) schema["items"] = toJsonSchema(type.items);
	return schema;
}

/** A short label: `string`, `integer | null`, `array<object>`. */
export function describeType(type: InferredType): string {
	return type.types
		.map((t) => (t === "array" && type.items ? `array<${describeType(type.items)}>` : t))
		.join(" | ");
}

export interface Expected {
	/** The JSON types the target accepts (`[]`: anything). */
	types: readonly string[];
	nullable: boolean;
	format?: string | undefined;
}

export type Compatibility =
	| { status: "ok" }
	| { status: "coerced"; message: string }
	| { status: "mismatch"; message: string };

/**
 * Whether values of the inferred type fit a target that wants `expected`.
 * `coerced` is what Frappe converts on save (a number into a Data field, `true`
 * into a Check), which the editor shows as a warning; `mismatch` is what it
 * rejects or mangles.
 */
export function compatibility(actual: InferredType, expected: Expected): Compatibility {
	if (expected.types.length === 0) return { status: "ok" };
	const accepts = new Set(expected.types);
	if (accepts.has("number")) accepts.add("integer");
	let coerced: string | undefined;
	for (const type of actual.types) {
		if (type === "undefined") continue;
		if (type === "null") {
			if (!expected.nullable) coerced ??= "can be null, which leaves the field empty";
			continue;
		}
		if (accepts.has(type)) continue;
		if (accepts.has("string") && (type === "number" || type === "integer" || type === "boolean")) {
			coerced ??= `is a ${type}, saved as text`;
			continue;
		}
		if (accepts.has("integer") && type === "boolean") {
			coerced ??= "is a boolean, saved as 0 or 1";
			continue;
		}
		if ((accepts.has("number") || accepts.has("integer")) && type === "string") {
			coerced ??= "is text, converted to a number (it must be numeric)";
			continue;
		}
		return {
			status: "mismatch",
			message: `is ${describeType(actual)}, but the field wants ${expected.types.join(" | ")}`,
		};
	}
	if (
		expected.format !== undefined &&
		actual.types.includes("string") &&
		actual.format !== undefined &&
		actual.format !== expected.format
	) {
		coerced ??= `looks like a ${actual.format}, but the field wants a ${expected.format}`;
	}
	return coerced === undefined ? { status: "ok" } : { status: "coerced", message: coerced };
}
