/** The most text read for an import, and for the files it refers to, all of them together: api/schema.py's MAX_SOURCE_BYTES. */
export declare const MAX_SOURCE_BYTES: number;
/** The largest spec stored: schema/openapi.py's MAX_SPEC_BYTES. */
export declare const MAX_SPEC_BYTES: number;
/** The API Spec's Source Format options. */
export type SourceFormat = "OpenAPI 3.1" | "OpenAPI 3.0" | "Swagger 2.0";
/** What save_spec takes, besides the title and the Connection. */
export interface PreparedSpec {
    specJson: string;
    sourceFormat: SourceFormat;
    originalVersion: string;
    /** `info.title`, to suggest as the API Spec's title. */
    title: string;
}
/** Why a spec can't be imported: a sentence, and the details behind it. */
export declare class SpecImportError extends Error {
    readonly details: string[];
    constructor(message: string, details?: string[]);
}
export interface PrepareOptions {
    /** The URL the text came from, which relative references are read against. */
    origin?: string;
    /** The text at a URL, or a rejection whose message says why not. */
    fetchText: (url: string) => Promise<string>;
}
export declare function byteLength(text: string): number;
/** The text as an object, from JSON or YAML. */
export declare function parseSpecText(text: string): Record<string, unknown>;
/** Which of the formats the API Spec takes a document is written in, and its exact version. */
export declare function detectFormat(document: Record<string, unknown>): {
    sourceFormat: SourceFormat;
    originalVersion: string;
};
/** The absolute URL of a reference's file, or undefined when it has no base to be read against. */
export declare function referenceUrl(reference: string, source: string): string | undefined;
/** Parse, bundle and upgrade to OpenAPI 3.1: the spec as save_spec takes it. */
export declare function prepareSpec(text: string, options: PrepareOptions): Promise<PreparedSpec>;
