/**
 * JSON Pointers (RFC 6901) the way the transform editor uses them.
 *
 * A rule is keyed by the pointer of the target field it fills, with the items
 * of a collection implied rather than indexed: `/lines/qty` is the `qty` of
 * every line. Source reads (reads.ts), schema tree nodes (schemaTree.ts) and
 * diagnostics (diagnostics.ts) use the same form, so they can be compared as
 * plain strings.
 */
/** One segment, escaped: `~` becomes `~0` and `/` becomes `~1`. */
export declare function escapeSegment(segment: string): string;
/** One escaped segment, read back. */
export declare function unescapeSegment(segment: string): string;
/** The pointer of a list of segments: `[]` is `""` (the whole document). */
export declare function toPointer(segments: readonly string[]): string;
/** The segments of a pointer. Throws on text that is not a pointer. */
export declare function fromPointer(pointer: string): string[];
/** The pointer one level up; the root's parent is the root. */
export declare function parentPointer(pointer: string): string;
