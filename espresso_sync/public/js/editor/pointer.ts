// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

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
export function escapeSegment(segment: string): string {
	return segment.replaceAll("~", "~0").replaceAll("/", "~1");
}

/** One escaped segment, read back. */
export function unescapeSegment(segment: string): string {
	return segment.replaceAll("~1", "/").replaceAll("~0", "~");
}

/** The pointer of a list of segments: `[]` is `""` (the whole document). */
export function toPointer(segments: readonly string[]): string {
	return segments.map((segment) => `/${escapeSegment(segment)}`).join("");
}

/** The segments of a pointer. Throws on text that is not a pointer. */
export function fromPointer(pointer: string): string[] {
	if (pointer === "") return [];
	if (!pointer.startsWith("/")) throw new SyntaxError(`Not a JSON Pointer: ${JSON.stringify(pointer)}`);
	return pointer.slice(1).split("/").map(unescapeSegment);
}

/** The pointer one level up; the root's parent is the root. */
export function parentPointer(pointer: string): string {
	const cut = pointer.lastIndexOf("/");
	return cut <= 0 ? "" : pointer.slice(0, cut);
}
