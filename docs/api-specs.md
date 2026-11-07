---
title: API Specs and schemas
description: Storing an API's OpenAPI description, and the schema endpoints the transform editor reads operations, DocTypes and payload checks from.
nav_title: API Specs
order: 2
updated: 2026-11-07
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

**Only OpenAPI 3.1 is stored.** The import screen upgrades Swagger 2.0 and OpenAPI 3.0 to 3.1 in the browser and bundles external references before it saves. The server refuses anything else: another version, a spec that does not validate as OpenAPI 3.1, or one with a `$ref` that leaves the document (`other.yaml#/...`, `https://...`, `file:///...`). It never opens a file or a URL to resolve a reference.

YAML is read the way OpenAPI means it: dates such as `2026-01-01` stay strings, only `true` and `false` are booleans (`on`, `off`, `yes` and `no` are strings), and keys such as `200:` become the string `"200"`.

### Authentication hints

| Security scheme      | Suggestion                                                               |
| -------------------- | ------------------------------------------------------------------------ |
| `apiKey` in a header | Header-based, the scheme's header name as API Key, the key as API Secret |
| `http` `basic`       | Basic, the user as API Key, the password as API Secret                   |
| `http` `bearer`      | Header-based, `Authorization` as API Key, `Bearer <token>` as API Secret |
| anything else        | none: set the Connection's authentication by hand                        |

A hint is never applied by itself: credentials stay in the Connection form.

## Where requests go

Every request the app sends (a sync, a sample, a spec fetched for import) is checked first:

- Only `http` and `https` URLs, without `user:password@` in them.
- The host must resolve to public addresses only. Loopback, private, link-local (the cloud metadata address `169.254.169.254` among them), shared and reserved ranges are refused, and so is a host with any such address. The connection is then made to the address that was checked.
- At most 5 redirects, each checked the same way.
- A response body of at most 20 MiB (10 MiB for a spec), arriving within 2 minutes.

An API on a private network can be opened in the site config, by range:

```json
{ "espresso_sync_private_networks": ["10.1.2.0/24"] }
```

The cloud metadata addresses stay refused whatever it says.

**Credentials go to one host only**, the Connection's **Allowed Host** (`host`, or `host:port`). It is filled from the API Domain when left empty. A request to any other host, a shot that overrides the API Domain or a redirect included, is sent without the credentials, and its Pull Log entry carries a `credentials-withheld` warning.

## Endpoints

All are under `/api/method/espresso_sync.api.schema.<name>`.

| Endpoint               | Arguments                                                                                                     | Returns                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `fetch_spec_source`    | `url`, optional `connection` (POST)                                                                           | `{url, status, content_type, text}`: the text at the URL, fetched under the checks above |
| `save_spec`            | `spec_json`, `title`, optional `connection`, `source_url`, `source_format`, `original_version`, `name` (POST) | `{name, spec_hash, changed, operations, auth_hints}`                                     |
| `list_operations`      | `spec` (an API Spec name)                                                                                     | the Operations summary                                                                   |
| `get_operation_schema` | `spec`, `method`, `path`, `part` (`response` or `requestBody`), optional `status`                             | `{schema, media_type, status, parameters}`                                               |
| `get_doctype_schema`   | `doctype`, `mode` (`read`, `insert` or `update`)                                                              | the DocType's JSON Schema                                                                |
| `validate_payload`     | `payload`, and either `spec`, `method`, `path`, `part`, `status` or `doctype`, `mode` (POST)                  | a list of diagnostics                                                                    |

`fetch_spec_source` with a `connection` sends that Connection's credentials when the URL's host is its Allowed Host. `save_spec` with a `name` updates that API Spec. `get_doctype_schema` also needs read permission on the DocType.

### An operation's schema

`get_operation_schema` picks the JSON media type (`application/json`, then any `+json`) and, for a response, the lowest 2XX status unless one is given. The schema is plain JSON Schema (the OpenAPI 3.1 dialect) with every internal `$ref` replaced by what it points at. A reference met again inside its own expansion, as in a tree of categories, becomes `{"x-cycle": "#/components/schemas/Category"}`.

### A DocType's schema

`get_doctype_schema` returns JSON Schema draft 2020-12, built from the DocType's meta, Custom Fields included:

- `read` is a document as read, with its standard fields (`name`, `owner`, `creation`, `modified`, and so on). `insert` is a new document: its hard-required fields are `required`. `update` requires nothing.
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
| not an option of a Select, too long, not a date | error    | `schema-...`     |
| a number given as a string (`"12"`)             | warning  | `numeric-string` |
| a Check given 2                                 | warning  | `check-number`   |
| a key that is not a field                       | warning  | `unknown-field`  |
| a mandatory field Frappe fills in, not given    | warning  | `server-filled`  |
| a Check given `true` or `false`                 | info     | `check-boolean`  |

An empty optional value (`null`, `""`) is not reported.
