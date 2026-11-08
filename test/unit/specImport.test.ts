// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	detectFormat,
	MAX_SOURCE_BYTES,
	MAX_SPEC_BYTES,
	parseSpecText,
	prepareSpec,
	referenceUrl,
	SpecImportError,
} from "../../espresso_sync/public/js/editor/specImport.ts";

const SWAGGER = `
swagger: "2.0"
info: {title: Pet Shop, version: "1.0"}
host: api.example.com
basePath: /v1
schemes: [https]
paths:
  /pets:
    get:
      produces: [application/json]
      responses:
        "200":
          description: The pets
          schema:
            type: array
            items: {$ref: "schemas/pets.yaml#/Pet"}
`;

const FILES: Record<string, string> = {
	"https://specs.example.com/shop/schemas/pets.yaml": `
Pet:
  type: object
  properties:
    name: {type: string}
    owner: {$ref: "people.yaml#/Person"}
`,
	"https://specs.example.com/shop/schemas/people.yaml": `
Person:
  type: object
  properties:
    name: {type: string}
Unused:
  type: string
`,
};

/** A stand-in for fetch_spec_source: FILES, and the URLs asked for. */
function server(files = FILES) {
	const asked: string[] = [];
	const fetchText = (url: string) => {
		asked.push(url);
		const text = files[url];
		return text === undefined ? Promise.reject(new Error(`${url} answered HTTP 404`)) : Promise.resolve(text);
	};
	return { asked, fetchText };
}

function refsOf(value: unknown, found: string[] = []): string[] {
	if (Array.isArray(value)) for (const item of value) refsOf(item, found);
	else if (typeof value === "object" && value !== null) {
		for (const [key, item] of Object.entries(value)) {
			if (key === "$ref" && typeof item === "string") found.push(item);
			else refsOf(item, found);
		}
	}
	return found;
}

async function rejection(promise: Promise<unknown>): Promise<SpecImportError> {
	try {
		await promise;
	} catch (error) {
		assert.ok(error instanceof SpecImportError, String(error));
		return error;
	}
	assert.fail("expected a SpecImportError");
}

describe("detectFormat", () => {
	it("knows the three formats an API Spec takes", () => {
		assert.deepEqual(detectFormat({ swagger: "2.0" }), {
			sourceFormat: "Swagger 2.0",
			originalVersion: "2.0",
		});
		assert.deepEqual(detectFormat({ openapi: "3.0.3" }), {
			sourceFormat: "OpenAPI 3.0",
			originalVersion: "3.0.3",
		});
		assert.deepEqual(detectFormat({ openapi: "3.1.1" }), {
			sourceFormat: "OpenAPI 3.1",
			originalVersion: "3.1.1",
		});
	});

	it("refuses another version, or no version, saying which", () => {
		assert.throws(() => detectFormat({ openapi: "3.2.0" }), /Version 3\.2\.0 isn't one that can be imported/);
		assert.throws(() => detectFormat({ swagger: "1.2" }), /Version 1\.2/);
		assert.throws(() => detectFormat({ info: {} }), /no `openapi` or `swagger` version/);
	});
});

describe("parseSpecText", () => {
	it("reads JSON and YAML, a byte order mark included", () => {
		assert.deepEqual(parseSpecText('﻿{"openapi": "3.1.0"}'), { openapi: "3.1.0" });
		assert.deepEqual(parseSpecText("openapi: 3.1.0\ninfo:\n  title: Shop\n"), {
			openapi: "3.1.0",
			info: { title: "Shop" },
		});
	});

	it("says why it can't", () => {
		assert.throws(() => parseSpecText(""), /not a JSON or YAML object/);
		assert.throws(() => parseSpecText('{"openapi": '), /not a JSON or YAML object/);
		assert.throws(() => parseSpecText("- just\n- a list"), /not a JSON or YAML object/);
		assert.throws(() => parseSpecText("openapi: [3.1"), /not valid YAML/);
	});

	it("refuses more text than the server reads", () => {
		assert.throws(() => parseSpecText(`#${"x".repeat(MAX_SOURCE_BYTES)}`), /larger than 32 MB/);
	});
});

describe("referenceUrl", () => {
	it("reads a reference's file against where it was found", () => {
		assert.equal(
			referenceUrl("b.yaml#/X", "https://a.example/specs/a.yaml"),
			"https://a.example/specs/b.yaml",
		);
		assert.equal(referenceUrl("https://c.example/c.json#/X", "/"), "https://c.example/c.json");
		assert.equal(referenceUrl("b.yaml#/X", "/"), undefined);
	});
});

describe("prepareSpec", () => {
	it("bundles every external file through fetchText and upgrades Swagger 2.0 to OpenAPI 3.1", async () => {
		const { asked, fetchText } = server();
		const prepared = await prepareSpec(SWAGGER, {
			origin: "https://specs.example.com/shop/openapi.yaml",
			fetchText,
		});
		assert.deepEqual([...asked].sort(), Object.keys(FILES).sort());
		assert.equal(prepared.sourceFormat, "Swagger 2.0");
		assert.equal(prepared.originalVersion, "2.0");
		assert.equal(prepared.title, "Pet Shop");

		const spec = JSON.parse(prepared.specJson);
		assert.match(spec.openapi, /^3\.1\./);
		assert.deepEqual(spec.servers, [{ url: "https://api.example.com/v1" }]);
		const refs = refsOf(spec);
		assert.ok(refs.length > 0);
		for (const ref of refs) assert.match(ref, /^#\/x-ext\//);
		// tree-shaken: only what is referred to is embedded
		assert.doesNotMatch(prepared.specJson, /Unused/);
		const schema = spec.paths["/pets"].get.responses["200"].content["application/json"].schema;
		assert.equal(schema.type, "array");
	});

	it("upgrades OpenAPI 3.0, `nullable` included, and keeps internal references", async () => {
		const prepared = await prepareSpec(
			JSON.stringify({
				openapi: "3.0.3",
				info: { title: "Shop", version: "2" },
				paths: {
					"/tasks": {
						get: {
							responses: {
								"200": {
									description: "Tasks",
									content: { "application/json": { schema: { $ref: "#/components/schemas/Task" } } },
								},
							},
						},
					},
				},
				components: {
					schemas: { Task: { type: "object", properties: { due: { type: "string", nullable: true } } } },
				},
			}),
			server({}),
		);
		const spec = JSON.parse(prepared.specJson);
		assert.equal(prepared.sourceFormat, "OpenAPI 3.0");
		assert.equal(prepared.originalVersion, "3.0.3");
		assert.deepEqual(spec.components.schemas.Task.properties.due.type, ["string", "null"]);
		assert.equal(
			spec.paths["/tasks"].get.responses["200"].content["application/json"].schema.$ref,
			"#/components/schemas/Task",
		);
	});

	it("says which references failed, with the server's reason", async () => {
		const missing = { ...FILES };
		delete missing["https://specs.example.com/shop/schemas/people.yaml"];
		const error = await rejection(
			prepareSpec(SWAGGER, { origin: "https://specs.example.com/shop/openapi.yaml", ...server(missing) }),
		);
		assert.match(error.message, /couldn't be resolved/);
		assert.equal(error.details.length, 1);
		assert.match(error.details[0] ?? "", /people\.yaml#\/Person .*answered HTTP 404/);
	});

	it("explains that a pasted spec's relative references need its URL", async () => {
		const { asked, fetchText } = server();
		const error = await rejection(prepareSpec(SWAGGER, { fetchText }));
		assert.deepEqual(asked, []);
		assert.match(
			error.details[0] ?? "",
			/schemas\/pets\.yaml#\/Pet \(at \/paths\/~1pets\/.*imported from its URL/,
		);
	});

	it("upgrades a Swagger 2.0 path item, parameter and response from other files", async () => {
		const files: Record<string, string> = {
			"https://specs.example.com/shop/paths/pets.yaml": `
parameters: [{$ref: "../parameters.yaml#/shop"}]
get:
  produces: [application/json]
  parameters: [{name: limit, in: query, type: integer}]
  responses:
    "200": {$ref: "../responses.yaml#/Pets"}
post:
  consumes: [application/json]
  parameters: [{name: pet, in: body, required: true, schema: {$ref: "../schemas/pets.yaml#/Pet"}}]
  responses:
    "201": {description: Made}
`,
			"https://specs.example.com/shop/parameters.yaml": `shop: {name: shop, in: header, type: string}`,
			"https://specs.example.com/shop/responses.yaml": `
Pets:
  description: The pets
  schema: {type: array, items: {$ref: "schemas/pets.yaml#/Pet"}}
`,
			...FILES,
		};
		const prepared = await prepareSpec(
			`
swagger: "2.0"
info: {title: Pet Shop, version: "1.0"}
host: api.example.com
paths:
  /pets: {$ref: "paths/pets.yaml"}
`,
			{ origin: "https://specs.example.com/shop/openapi.yaml", ...server(files) },
		);
		const pets = JSON.parse(prepared.specJson).paths["/pets"];
		assert.deepEqual(pets.parameters, [{ name: "shop", in: "header", schema: { type: "string" } }]);
		assert.deepEqual(pets.get.parameters, [{ name: "limit", in: "query", schema: { type: "integer" } }]);
		assert.equal(pets.get.responses["200"].content["application/json"].schema.type, "array");
		assert.match(pets.post.requestBody.content["application/json"].schema.$ref, /^#\/x-ext\//);
		assert.equal(pets.post.parameters, undefined);
	});

	it("stops fetching once the files referred to pass the limit", async () => {
		const large = `Big: {type: string, description: "${"x".repeat(MAX_SOURCE_BYTES / 2)}"}`;
		const refs = Array.from(
			{ length: 8 },
			(_, n) => `  F${n}: {$ref: "https://specs.example.com/${n}.yaml#/Big"}`,
		);
		const files = Object.fromEntries(
			Array.from({ length: 8 }, (_, n) => [`https://specs.example.com/${n}.yaml`, large]),
		);
		const { asked, fetchText } = server(files);
		const text = `openapi: 3.1.0\ninfo: {title: Big, version: "1"}\npaths: {}\ncomponents:\n schemas:\n${refs.join("\n")}\n`;
		const error = await rejection(prepareSpec(text, { fetchText }));
		assert.match(error.message, /files the spec refers to are larger than 32 MB in all/);
		assert.ok(asked.length < 8, `fetched ${asked.length}`);
	});

	it("refuses a spec that refers to itself through a YAML alias", async () => {
		const error = await rejection(
			prepareSpec(
				"openapi: 3.1.0\ninfo: {title: Loop, version: '1'}\npaths: {}\nx-loop: &loop {self: *loop}\n",
				server(),
			),
		);
		assert.match(error.message, /refers to itself through a YAML alias/);
	});

	it("refuses a spec larger than the server stores", async () => {
		const huge = {
			openapi: "3.1.0",
			info: { title: "Huge", version: "1", description: "x".repeat(MAX_SPEC_BYTES) },
		};
		const error = await rejection(prepareSpec(JSON.stringify({ ...huge, paths: {} }), server()));
		assert.match(error.message, /larger than 10 MB/);
	});
});
