---
title: Espresso Sync
description: Two-way sync between Frappe documents and external REST APIs, mapped with JSONata transforms built on the APIs' OpenAPI descriptions.
nav_title: Overview
order: 0
updated: 2026-11-08
---

Espresso Sync moves documents between a Frappe site and external REST APIs, in either direction. It runs on Frappe v16 and needs no other Frappe app.

## How it fits together

- An **Espresso Sync Connection** holds an API's **Server URL**, its credentials (Basic, or a header such as `X-Api-Key` or `Authorization: Bearer …`), an optional rate limit, and the **Allowed Host**, the one host its credentials are sent to. Its **shots** say what it syncs. See [Connections and syncs](syncs.md).
- An **Espresso Sync API Spec** holds the API's OpenAPI 3.1 description: its operations, and the JSON Schema of each request and response body. See [API Specs and schemas](api-specs.md).
- An **Espresso Sync Transform** maps one operation of an API Spec to a DocType (an import), or a DocType to one operation (an export), with [JSONata](https://docs.jsonata.org/) rules keyed by the target field's JSON Pointer. It is checked against both schemas, dry-run on a sample, and activated before it runs. See [Transforms](transforms.md).
- A **shot** of a Connection syncs one DocType: it imports with an Active import transform, exports with an Active export transform, or both.
- Imported objects are matched to documents through the **Espresso Sync IDs** table the app adds, on a **Sync** tab, to each DocType a shot names. A document's **Exclude from Sync** box keeps it out of exports.
- Every request, object and document a sync handles is recorded in an **Espresso Sync Pull Log**, with its diagnostics and the hash of the JSONata that ran. Credentials are redacted before the log is saved. Log Settings deletes entries older than 30 days; change the period there.

The ERP is always one side: a transform maps between a DocType and an API operation, never between two APIs.

## Validation, from the cheapest

1. **On every save of a transform**: its rules compile, each expression parses, and every required field of the target has a rule.
2. **On the sample** (`validate_transform`): each sample item is mapped, the result checked against the target's schema (the DocType's, with Frappe's own coercions as warnings, or the request body's), and an import's Links checked to exist, as the user may read them.
3. **The dry run**: an import's sample documents are inserted with every hook Frappe runs, then rolled back.
4. **Activation** is refused while any of these finds an error, or when the API Spec's operation or the DocType changed since the transform was saved.
5. **When a sync runs**, each mapped object is checked again, as the transform's **Runtime Validation** says: Enforce (the default) does not save or send one with an error, Warn logs what it found, Off checks nothing.

## Security

- **System Managers only.** Connections, API Specs, Transforms and the Pull Log are for System Managers, and so are every endpoint and the `/espresso_sync` page. A share can let someone else read one, but nothing more: saving a Connection, an API Spec or a Transform, and Sync Now, check the role, not just the document's permission.
- **Credentials stay in the desk.** The API Secret is a Password field, read only to send a request. It is never put in a page, an endpoint's answer or the Pull Log.
- **Credentials go to one host.** The Server URL's host must be the Allowed Host, and a request carries the credentials only to that host and port, redirects included; an https request redirected to http drops them.
- **Requests go to public addresses only**, through Frappe's guarded session, with caps on redirects, size and time. See [Where requests go](api-specs.md#where-requests-go).
- **Expressions are sandboxed.** JSONata cannot reach the server. The functions the app adds read the site as the user the transform runs as, through Frappe's permission checks, and every evaluation stops after 5 seconds.
- **The Pull Log is redacted**: header values and JSON keys that look like credentials, URL user-info and secret query parameters, and every literal occurrence of the Connection's secret, before an entry is saved.

## The /espresso_sync page

The portal page at `/espresso_sync`, which the **Espresso Sync** tile on the apps screen opens, lists the Connections, the API Specs and the transforms, imports specs, starts a Draft transform on an operation, and edits a transform's rules in the [transform editor](transforms.md#the-editor). The tile and the page are for System Managers only. The app is not published to the Frappe marketplace yet.
