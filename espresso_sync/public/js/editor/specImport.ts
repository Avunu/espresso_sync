// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * Turns an API description as written (JSON or YAML; Swagger 2.0, OpenAPI 3.0 or 3.1)
 * into what an Espresso Sync API Spec stores: one self-contained OpenAPI 3.1 document.
 *
 * Bundle, then upgrade, with Scalar's tools: external `$ref`s are fetched and embedded
 * under `x-ext` (internal ones are kept), and the document is upgraded to 3.1. Every
 * external file is fetched by `fetchText`, which the page routes through the server's
 * fetch_spec_source: the browser never fetches another site itself. save_spec then
 * validates the result as OpenAPI 3.1 and says what is wrong with it.
 */

import { bundleWithDiagnostics, type ReferenceDiagnostic } from "@scalar/json-magic/bundle";
import { fetchUrls } from "@scalar/json-magic/bundle/plugins/browser";
import { getSegmentsFromPath } from "@scalar/json-magic/helpers/get-segments-from-path";
import { getValueByPath } from "@scalar/json-magic/helpers/get-value-by-path";
import { normalize, upgrade } from "@scalar/openapi-parser";

/** The most text read for an import, and for the files it refers to, all of them together: api/schema.py's MAX_SOURCE_BYTES. */
export const MAX_SOURCE_BYTES = 32 * 1024 * 1024;
/** The largest spec stored: schema/openapi.py's MAX_SPEC_BYTES. */
export const MAX_SPEC_BYTES = 10 * 1024 * 1024;
/** External files fetched at once. */
const FETCH_LIMIT = 4;
/** The methods of a Swagger 2.0 Path Item. */
const SWAGGER_METHODS = ["get", "put", "post", "delete", "options", "head", "patch"];

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
export class SpecImportError extends Error {
	readonly details: string[];

	constructor(message: string, details: string[] = []) {
		super(message);
		this.name = "SpecImportError";
		this.details = details;
	}
}

export interface PrepareOptions {
	/** The URL the text came from, which relative references are read against. */
	origin?: string;
	/** The text at a URL, or a rejection whose message says why not. */
	fetchText: (url: string) => Promise<string>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function byteLength(text: string): number {
	return new TextEncoder().encode(text).length;
}

function megabytes(bytes: number): string {
	return `${bytes / (1024 * 1024)} MB`;
}

/** The text as an object, from JSON or YAML. */
export function parseSpecText(text: string): Record<string, unknown> {
	if (byteLength(text) > MAX_SOURCE_BYTES) {
		throw new SpecImportError(`The text is larger than ${megabytes(MAX_SOURCE_BYTES)}.`);
	}
	let value: unknown;
	try {
		value = normalize(text);
	} catch (error) {
		throw new SpecImportError("The text is not valid YAML.", [String((error as Error).message)]);
	}
	if (!isRecord(value)) throw new SpecImportError("The text is not a JSON or YAML object.");
	return value;
}

/** Which of the formats the API Spec takes a document is written in, and its exact version. */
export function detectFormat(document: Record<string, unknown>): {
	sourceFormat: SourceFormat;
	originalVersion: string;
} {
	const { swagger, openapi } = document;
	if (swagger === "2.0") return { sourceFormat: "Swagger 2.0", originalVersion: "2.0" };
	if (typeof openapi === "string") {
		if (/^3\.0\.\d+$/.test(openapi)) return { sourceFormat: "OpenAPI 3.0", originalVersion: openapi };
		if (/^3\.1\.\d+$/.test(openapi)) return { sourceFormat: "OpenAPI 3.1", originalVersion: openapi };
	}
	const version = typeof openapi === "string" ? openapi : typeof swagger === "string" ? swagger : undefined;
	throw new SpecImportError(
		version
			? `Version ${version} isn't one that can be imported: Swagger 2.0, OpenAPI 3.0 and OpenAPI 3.1 can.`
			: "This isn't an OpenAPI or Swagger description: it has no `openapi` or `swagger` version.",
	);
}

/** The absolute URL of a reference's file, or undefined when it has no base to be read against. */
export function referenceUrl(reference: string, source: string): string | undefined {
	const file = reference.split("#")[0] ?? "";
	try {
		return new URL(file, source).href;
	} catch {
		try {
			return new URL(file).href;
		} catch {
			return undefined;
		}
	}
}

function describeUnresolved(diagnostic: ReferenceDiagnostic, failures: Map<string, string>): string {
	const where = diagnostic.pointer.replace(/^#/, "").replace(/\/\$ref$/, "") || "/";
	if (diagnostic.kind === "missing-target") return `${diagnostic.reference} (at ${where}): nothing is there.`;
	const url = referenceUrl(diagnostic.reference, diagnostic.source);
	if (!url || !/^https?:/.test(url)) {
		return `${diagnostic.reference} (at ${where}): a file next to the spec, which can only be found when the spec is imported from its URL.`;
	}
	return `${diagnostic.reference} (at ${where}): ${failures.get(url) ?? `${url} is not JSON or YAML.`}`;
}

/** Embeds every external reference, fetching each file through `fetchText`. */
async function bundleReferences(
	document: Record<string, unknown>,
	{ origin, fetchText }: PrepareOptions,
): Promise<Record<string, unknown>> {
	const failures = new Map<string, string>();
	let bytes = 0;
	const tooLarge = `The files the spec refers to are larger than ${megabytes(MAX_SOURCE_BYTES)} in all.`;
	const result = await bundleWithDiagnostics(document, {
		plugins: [
			fetchUrls({
				limit: FETCH_LIMIT,
				fetch: async (input) => {
					const url = String(input);
					try {
						// past the limit, nothing more is fetched
						if (bytes > MAX_SOURCE_BYTES) throw new Error(tooLarge);
						const text = await fetchText(url);
						bytes += byteLength(text);
						if (bytes > MAX_SOURCE_BYTES) throw new Error(tooLarge);
						return new Response(text);
					} catch (error) {
						failures.set(url, error instanceof Error ? error.message : String(error));
						throw error;
					}
				},
			}),
		],
		treeShake: true,
		...(origin === undefined ? {} : { origin }),
	});
	if (bytes > MAX_SOURCE_BYTES) throw new SpecImportError(tooLarge);
	if (!result.complete) {
		throw new SpecImportError(
			"Some references to other files couldn't be resolved:",
			result.diagnostics.map((diagnostic) => describeUnresolved(diagnostic, failures)),
		);
	}
	return result.document as Record<string, unknown>;
}

/**
 * Swagger 2.0's path items, parameters and responses from other files, copied in where
 * they are used. Scalar's upgrade converts these only where Swagger 2.0 puts them, not
 * under `x-ext`, where bundling leaves them; the schemas they refer to stay there.
 */
function inlineSwaggerObjects(document: Record<string, unknown>): void {
	const inline = (node: unknown): unknown => {
		let value = node;
		const seen = new Set<string>();
		while (isRecord(value) && typeof value["$ref"] === "string" && value["$ref"].startsWith("#/x-ext/")) {
			const ref = value["$ref"];
			const target: unknown = getValueByPath(document, getSegmentsFromPath(ref.slice(1))).value;
			if (target === undefined || seen.has(ref)) break;
			seen.add(ref);
			value = target;
		}
		return value === node ? node : structuredClone(value);
	};
	const inlineEach = (holder: unknown, key: string) => {
		if (!isRecord(holder)) return;
		const items = holder[key];
		if (Array.isArray(items)) holder[key] = items.map(inline);
		else if (isRecord(items)) for (const [name, item] of Object.entries(items)) items[name] = inline(item);
	};
	inlineEach(document, "parameters");
	inlineEach(document, "responses");
	inlineEach(document, "paths");
	for (const pathItem of Object.values(isRecord(document["paths"]) ? document["paths"] : {})) {
		inlineEach(pathItem, "parameters");
		for (const method of SWAGGER_METHODS) {
			const operation = isRecord(pathItem) ? pathItem[method] : undefined;
			inlineEach(operation, "parameters");
			inlineEach(operation, "responses");
		}
	}
}

/** The spec as JSON text, or why it can't be. */
function toJson(specification: unknown): string {
	try {
		return JSON.stringify(specification);
	} catch (error) {
		throw new SpecImportError(
			error instanceof TypeError
				? "The spec refers to itself through a YAML alias, which JSON can't hold."
				: // a RangeError: longer than a string can be
					`The spec is larger than ${megabytes(MAX_SPEC_BYTES)} once its references are bundled.`,
		);
	}
}

/** Parse, bundle and upgrade to OpenAPI 3.1: the spec as save_spec takes it. */
export async function prepareSpec(text: string, options: PrepareOptions): Promise<PreparedSpec> {
	const document = parseSpecText(text);
	const { sourceFormat, originalVersion } = detectFormat(document);
	const bundled = await bundleReferences(document, options);
	if (sourceFormat === "Swagger 2.0") inlineSwaggerObjects(bundled);
	const { specification } = upgrade(bundled);
	const specJson = toJson(specification);
	if (byteLength(specJson) > MAX_SPEC_BYTES) {
		throw new SpecImportError(
			`The spec is larger than ${megabytes(MAX_SPEC_BYTES)} once its references are bundled.`,
		);
	}
	const info = specification?.info;
	return {
		specJson,
		sourceFormat,
		originalVersion,
		title: typeof info?.title === "string" ? info.title : "",
	};
}
