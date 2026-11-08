---
title: API Specs and schemas
description: Storing an API's OpenAPI description, and the schema endpoints the transform editor reads operations, DocTypes and payload checks from.
nav_title: API Specs
order: 2
updated: 2026-11-08
---

The transform editor maps between an external API and a DocType. It learns the API's side from an **Espresso Sync API Spec**, the API's OpenAPI description, and the DocType's side from the DocType itself. Both are turned into JSON Schema, which the editor shows as trees and checks payloads against.

Only a System Manager can see or change an API Spec or call the endpoints below.

## Espresso Sync API Spec

| Field                | Holds                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------- |
| Title, Connection    | The name is `<Connection> - <Title>`, or the title alone when no Connection is set.                        |
| Source URL           | Where the spec was imported from.                                                                          |
| Source Format        | The format it was written in: OpenAPI 3.1, OpenAPI 3.0 or Swagger 2.0.                                     |
| Original Version     | Its `openapi` or `swagger` version before any upgrade.                                                     |
| Spec                 | The description, always OpenAPI 3.1, bundled: every `$ref` points inside it (`#/...`).                     |
| Spec Hash            | SHA-256 of the spec's canonical JSON. The same spec gives the same hash, whatever its key order.           |
| Operations           | Each operation's method, path, operation id, summary, tags, request media types, responses and parameters. |
| Authentication Hints | What the spec's `securitySchemes` suggest for the Connection's authentication (see below).                 |

Changes are tracked: the form's activity shows each version of the spec.

**Only OpenAPI 3.1 is stored.** The import screen upgrades Swagger 2.0 and OpenAPI 3.0 to 3.1 in the browser and bundles external references before it saves. The server refuses anything else: another version, a spec that does not validate as OpenAPI 3.1, or one with a `$ref` that leaves the document (`other.yaml#/...`, `https://...`, `file:///...`), wherever it is, in an example or a default included. It never opens a file or a URL to resolve a reference.

### Importing a spec

The `/espresso_sync` page's **API specs** screen imports a spec from a URL, a JSON or YAML file, or pasted text, and re-imports one over its stored spec, saying whether it changed. In the browser, with [Scalar's OpenAPI parser](https://github.com/scalar/scalar/tree/main/packages/openapi-parser), it:

1. reads the text, at most 32 MiB;
2. fetches the files the spec's `$ref`s point to, at most 32 MiB of them in all, and embeds them under `x-ext`, keeping the internal references, so the spec refers only to itself;
3. upgrades Swagger 2.0 and OpenAPI 3.0 to OpenAPI 3.1;
4. saves the result, at most 10 MiB, with `save_spec`, which validates it as OpenAPI 3.1 and lists what is wrong with it.

The browser fetches nothing from another site: the spec's URL and every file it refers to go through `fetch_spec_source`, under the checks in [Where requests go](#where-requests-go), with the chosen Connection's credentials when the URL is on its Allowed Host. A pasted or uploaded spec can only refer to absolute URLs: a relative reference (`schemas/pet.yaml`) needs the spec's own URL to be read against, so import such a spec from its URL. The files a spec refers to are upgraded with it. A Swagger 2.0 path item, parameter or response from another file is copied in where it is used, and the schemas it refers to stay under `x-ext`. Only `x-nullable` in a Swagger 2.0 schema from another file is left as written, so that schema does not take `null`.

From a spec's operations, **New transform** makes a Draft transform on one: an import or an export, and the DocType on the other side, one of those you can read.

YAML is read as openapi-spec-validator reads it, dates such as `2026-01-01` staying strings, except that only `true` and `false` are booleans, as in JSON and YAML 1.2: `on`, `off`, `yes` and `no` stay strings. Keys such as `200:` become the string `"200"`.

### Authentication hints

| Security scheme      | Suggestion                                                               |
| -------------------- | ------------------------------------------------------------------------ |
| `apiKey` in a header | Header-based, the scheme's header name as API Key, the key as API Secret |
| `http` `basic`       | Basic, the user as API Key, the password as API Secret                   |
| `http` `bearer`      | Header-based, `Authorization` as API Key, `Bearer <token>` as API Secret |
| anything else        | none: set the Connection's authentication by hand                        |

A hint is never applied by itself: credentials stay in the Connection form.

## Where requests go

Every request the app sends (a sync, a sample, a spec fetched for import) goes through Frappe's guarded request session, the one Frappe's own safe requests use:

- Only `http` and `https` URLs, and no proxy.
- The host must resolve to public addresses only. Loopback, private, link-local (the cloud metadata address `169.254.169.254` among them), shared and reserved ranges are refused, and so is a host with any such address. The address connected to is checked again, so a DNS answer that changes in between is refused too.
- At most 5 redirects, each checked the same way.
- A response body of at most 20 MiB (32 MiB for a spec fetched for the import screen, which saves it minified: a stored spec is at most 10 MiB), all of it arrived within 2 minutes of the request, however slowly it trickles in. The status line and headers are not under that limit: each read of them waits at most 60 seconds, and the whole is bounded by the web worker's or the background job's timeout.

An API on a private network cannot be reached.

**Credentials go to one host only**, the Connection's **Allowed Host** (`host`, or `host:port`), on that port: `host` alone means the scheme's default port (443 for https, 80 for http). It is filled from the Server URL when left empty, and the Server URL's host must be it. A request to any other host or port, a redirect included, is sent without the credentials. The host is read from the URL as the request connects to it, so a URL such as `http://other.example\@api.example/` (which some parsers read as `api.example`) does not carry them to `other.example`. A redirect from https to http never carries them.

## Endpoints

All are under `/api/method/espresso_sync.api.schema.<name>`.

| Endpoint               | Arguments                                                                                                     | Returns                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `fetch_spec_source`    | `url`, optional `connection` (POST)                                                                           | `{url, status, content_type, text}`: the text at the URL, fetched under the checks above |
| `save_spec`            | `spec_json`, `title`, optional `connection`, `source_url`, `source_format`, `original_version`, `name` (POST) | `{name, spec_hash, changed, operations, auth_hints}`                                     |
| `list_operations`      | `spec` (an API Spec name)                                                                                     | the Operations summary                                                                   |
| `get_operation_schema` | `spec`, `method`, `path`, `part` (`response` or `requestBody`), optional `status`                             | `{schema, media_type, status, parameters}`                                               |
| `list_doctypes`        |                                                                                                               | the DocTypes a transform can map: those you can read, but child tables and Singles       |
| `get_doctype_schema`   | `doctype`, `mode` (`read`, `insert` or `update`)                                                              | the DocType's JSON Schema                                                                |
| `validate_payload`     | `payload`, and either `spec`, `method`, `path`, `part`, `status` or `doctype`, `mode` (POST)                  | a list of diagnostics                                                                    |

`fetch_spec_source` with a `connection` sends that Connection's credentials when the URL's host is its Allowed Host. `save_spec` with a `name` updates that API Spec. `get_doctype_schema` also needs read permission on the DocType.

### An operation's schema

`get_operation_schema` picks the JSON media type (`application/json`, then any `+json`) and, for a response, the lowest 2XX status unless one is given. The schema is plain JSON Schema (the OpenAPI 3.1 dialect) with every internal `$ref` replaced by what it points at. A reference met again inside its own expansion, as in a tree of categories, becomes `{"x-cycle": "#/components/schemas/Category"}`.

### A DocType's schema

`get_doctype_schema` returns JSON Schema draft 2020-12, built from the DocType's meta, Custom Fields included:

- `read` is a document as read, with its standard fields (`name`, `owner`, `creation`, `modified`, and so on). `insert` is a new document: its hard-required fields are `required`. `update` requires nothing.
- Every mode takes `doctype`, as Frappe gives and takes a document, and only as the DocType's own name (the child DocType's in a row). Keys that start with `__`, such as `__unsaved`, are ignored, and so are the app's own `espresso_sync_ids` and `exclude_from_sync`, which a document read from the site has.
- Layout fields, virtual fields, and the app's own `espresso_sync_ids` and `exclude_from_sync` are left out.
- Each property has an `x-frappe` object: `fieldtype`, the raw `options`, `link` (a Link's DocType), `dynamic_link` (the field naming a Dynamic Link's DocType), `required`, `read_only` and `custom`. A child table is an array whose `items` is the child DocType's schema.
- `required` is `"hard"` for a field an insert must give (mandatory, with no default, no fetch and not set by the naming series), `"server"` for a mandatory field Frappe fills in, and `null` otherwise. Only `insert` sets it.
- A Check takes 0, 1, `true` or `false`.

### Diagnostics

`validate_payload` returns a list of `{rule, path, severity, code, message, origin}`, where `path` is the JSON Pointer of the value in the payload and `origin` is `openapi` or `doctype`.

Against an operation, a value the schema does not allow is an error. A failed `format` is a warning, and so is a `readOnly` property in a request body or a `writeOnly` one in a response.

Against a DocType, the check follows what Frappe does with the value:

| Value                                           | Severity | Code             |
| ----------------------------------------------- | -------- | ---------------- |
| missing or empty hard-required field            | error    | `required`       |
| mandatory field set empty in an update          | error    | `required`       |
| not an option of a Select, too long, not a date | error    | `schema-...`     |
| a number given as a string (`"12"`)             | warning  | `numeric-string` |
| a Check given 2                                 | warning  | `check-number`   |
| a key that is not a field                       | warning  | `unknown-field`  |
| a mandatory field Frappe fills in, not given    | warning  | `server-filled`  |
| a Check given `true` or `false`                 | info     | `check-boolean`  |

Empty is what Frappe takes as missing: `null`, `[]`, or text with nothing in it but spaces and HTML tags. An update fills nothing in, so a mandatory field it sets empty is refused, whatever its default (but for `null` in a child row, which a new row fills with the default). An empty optional value is not reported.
