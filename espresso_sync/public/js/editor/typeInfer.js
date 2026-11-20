// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
/** The JSON type of a value: `integer` for whole numbers, `undefined` and `function` as JavaScript has them. */
export function jsonType(value) {
    if (value === null)
        return "null";
    if (Array.isArray(value))
        return "array";
    if (typeof value === "number")
        return Number.isInteger(value) ? "integer" : "number";
    return typeof value;
}
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$/;
const TIME = /^\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;
/** The string format a value looks like: what Frappe's Date, Datetime and Time fields hold. */
export function stringFormat(value) {
    if (DATE.test(value))
        return "date";
    if (DATE_TIME.test(value))
        return "date-time";
    if (TIME.test(value))
        return "time";
    return undefined;
}
function normaliseTypes(types) {
    const set = new Set(types);
    if (set.has("integer") && set.has("number"))
        set.delete("integer");
    return [...set].sort();
}
/** The type of one value. */
export function inferType(value) {
    const type = jsonType(value);
    const inferred = { types: [type], count: 1 };
    if (type === "integer" && !Number.isSafeInteger(value))
        inferred.unsafeInteger = true;
    if (typeof value === "string") {
        const format = stringFormat(value);
        if (format)
            inferred.format = format;
    }
    if (Array.isArray(value)) {
        const items = value.map(inferType);
        const merged = items.reduce((acc, item) => (acc ? mergeTypes(acc, item) : item), undefined);
        if (merged)
            inferred.items = merged;
        if (merged?.unsafeInteger)
            inferred.unsafeInteger = true;
    }
    else if (type === "object") {
        const record = value;
        const properties = {};
        for (const [key, child] of Object.entries(record)) {
            if (child === undefined)
                continue;
            const childType = inferType(child);
            properties[key] = childType;
            if (childType.unsafeInteger)
                inferred.unsafeInteger = true;
        }
        inferred.properties = properties;
        inferred.required = Object.keys(properties).sort();
    }
    return inferred;
}
/** One type covering both: types unioned, keys required only where both had them. */
export function mergeTypes(a, b) {
    const merged = { types: normaliseTypes([...a.types, ...b.types]), count: a.count + b.count };
    const aStrings = a.types.includes("string");
    const bStrings = b.types.includes("string");
    if (aStrings && bStrings) {
        if (a.format !== undefined && a.format === b.format)
            merged.format = a.format;
    }
    else if (aStrings || bStrings) {
        const format = aStrings ? a.format : b.format;
        if (format !== undefined)
            merged.format = format;
    }
    if (a.unsafeInteger || b.unsafeInteger)
        merged.unsafeInteger = true;
    if (a.items && b.items)
        merged.items = mergeTypes(a.items, b.items);
    else if (a.items ?? b.items)
        merged.items = (a.items ?? b.items);
    if (a.properties || b.properties) {
        const properties = { ...a.properties };
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
export function inferFromSamples(values) {
    let merged;
    for (const value of values) {
        const type = inferType(value);
        merged = merged ? mergeTypes(merged, type) : type;
    }
    return merged;
}
/** A JSON Schema (draft 2020-12 keywords) for an inferred type, for schemaTree.ts. */
export function toJsonSchema(type) {
    const types = type.types.filter((t) => t !== "undefined" && t !== "function");
    const schema = {};
    if (types.length === 1)
        schema["type"] = types[0];
    else if (types.length > 1)
        schema["type"] = types;
    if (type.format !== undefined)
        schema["format"] = type.format;
    if (type.properties) {
        const properties = {};
        for (const [key, child] of Object.entries(type.properties))
            properties[key] = toJsonSchema(child);
        schema["properties"] = properties;
        if (type.required && type.required.length > 0)
            schema["required"] = type.required;
    }
    if (type.items)
        schema["items"] = toJsonSchema(type.items);
    return schema;
}
/** A short label: `string`, `integer | null`, `array<object>`. */
export function describeType(type) {
    return type.types
        .map((t) => (t === "array" && type.items ? `array<${describeType(type.items)}>` : t))
        .join(" | ");
}
/**
 * Whether values of the inferred type fit a target that wants `expected`.
 * `coerced` is what Frappe converts on save (a number into a Data field, `true`
 * into a Check), which the editor shows as a warning; `mismatch` is what it
 * rejects or mangles.
 */
export function compatibility(actual, expected) {
    if (expected.types.length === 0)
        return { status: "ok" };
    const accepts = new Set(expected.types);
    if (accepts.has("number"))
        accepts.add("integer");
    let coerced;
    for (const type of actual.types) {
        if (type === "undefined")
            continue;
        if (type === "null") {
            if (!expected.nullable)
                coerced ??= "can be null, which leaves the field empty";
            continue;
        }
        if (accepts.has(type))
            continue;
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
    if (expected.format !== undefined &&
        actual.types.includes("string") &&
        actual.format !== undefined &&
        actual.format !== expected.format) {
        coerced ??= `looks like a ${actual.format}, but the field wants a ${expected.format}`;
    }
    return coerced === undefined ? { status: "ok" } : { status: "coerced", message: coerced };
}
