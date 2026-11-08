// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * Turns an API description as written (JSON or YAML; Swagger 2.0, OpenAPI 3.0 or 3.1)
 * into what an Espresso Sync API Spec stores: one self-contained OpenAPI 3.1 document.
 *
 * Bundle, upgrade, validate, with Scalar's tools: external `$ref`s are fetched and
 * embedded under `x-ext` (internal ones are kept), the document is upgraded to 3.1,
 * then checked as OpenAPI. Every external file is fetched by `fetchText`, which the
 * page routes through the server's fetch_spec_source: the browser never fetches
 * another site itself. The server checks the result again when it is saved.
 */

import { bundleWithDiagnostics, type ReferenceDiagnostic } from "@scalar/json-magic/bundle";
import { fetchUrls } from "@scalar/json-magic/bundle/plugins/browser";
import { normalize, upgrade, validate } from "@scalar/openapi-parser";

/** The most text read for an import: api/schema.py's MAX_SOURCE_BYTES. */
export const MAX_SOURCE_BYTES = 32 * 1024 * 1024;
/** The largest spec stored: schema/openapi.py's MAX_SPEC_BYTES. */
export const MAX_SPEC_BYTES = 10 * 1024 * 1024;
/** The validation errors shown; the rest are counted. */
const SHOWN_ERRORS = 10;
/** External files fetched at once. */
const FETCH_LIMIT = 4;

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
	const result = await bundleWithDiagnostics(document, {
		plugins: [
			fetchUrls({
				limit: FETCH_LIMIT,
				fetch: async (input) => {
					const url = String(input);
					try {
						return new Response(await fetchText(url));
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
	if (!result.complete) {
		throw new SpecImportError(
			"Some references to other files couldn't be resolved:",
			result.diagnostics.map((diagnostic) => describeUnresolved(diagnostic, failures)),
		);
	}
	return result.document as Record<string, unknown>;
}

/** Parse, bundle, upgrade to OpenAPI 3.1 and validate: the spec as save_spec takes it. */
export async function prepareSpec(text: string, options: PrepareOptions): Promise<PreparedSpec> {
	const document = parseSpecText(text);
	const { sourceFormat, originalVersion } = detectFormat(document);
	const bundled = await bundleReferences(document, options);
	const { specification } = upgrade(bundled);
	const specJson = JSON.stringify(specification);
	if (byteLength(specJson) > MAX_SPEC_BYTES) {
		throw new SpecImportError(
			`The spec is larger than ${megabytes(MAX_SPEC_BYTES)} once its references are bundled.`,
		);
	}
	// validate() reads its own copy: given the object, it would fill in a missing info.version.
	const { valid, errors = [] } = await validate(specJson);
	if (!valid) {
		const details = errors.slice(0, SHOWN_ERRORS).map(({ path, message }) => {
			const where = Array.isArray(path) ? `/${path.join("/")}` : path;
			return where ? `${where}: ${message}` : message;
		});
		if (errors.length > SHOWN_ERRORS) details.push(`and ${errors.length - SHOWN_ERRORS} more.`);
		throw new SpecImportError("The spec is not valid OpenAPI 3.1:", details);
	}
	const info = specification?.info;
	return {
		specJson,
		sourceFormat,
		originalVersion,
		title: typeof info?.title === "string" ? info.title : "",
	};
}
