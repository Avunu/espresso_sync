/**
 * JSON-Schema-ish types inferred from values.
 *
 * Two uses in the editor: a pasted or fetched sample with no schema of its
 * own still gets a source tree (infer from the sample, then `toJsonSchema` and
 * schemaTree.ts), and a rule's preview shows what type its expression actually
 * produced across the sample's items (`inferType`), next to the type the
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
export declare function jsonType(value: unknown): string;
/** The string format a value looks like: what Frappe's Date, Datetime and Time fields hold. */
export declare function stringFormat(value: string): string | undefined;
/** The type of one value. */
export declare function inferType(value: unknown): InferredType;
/** One type covering both: types unioned, keys required only where both had them. */
export declare function mergeTypes(a: InferredType, b: InferredType): InferredType;
/** The type of several samples together (each one a value of the same field or document). */
export declare function inferFromSamples(values: Iterable<unknown>): InferredType | undefined;
/** A JSON Schema (draft 2020-12 keywords) for an inferred type, for schemaTree.ts. */
export declare function toJsonSchema(type: InferredType): Record<string, unknown>;
/** A short label: `string`, `integer | null`, `array<object>`. */
export declare function describeType(type: InferredType): string;
export interface Expected {
    /** The JSON types the target accepts (`[]`: anything). */
    types: readonly string[];
    nullable: boolean;
    format?: string | undefined;
}
export type Compatibility = {
    status: "ok";
} | {
    status: "coerced";
    message: string;
} | {
    status: "mismatch";
    message: string;
};
/**
 * Whether values of the inferred type fit a target that wants `expected`.
 * `coerced` is what Frappe converts on save (a number into a Data field, `true`
 * into a Check), which the editor shows as a warning; `mismatch` is what it
 * rejects or mangles.
 */
export declare function compatibility(actual: InferredType, expected: Expected): Compatibility;
