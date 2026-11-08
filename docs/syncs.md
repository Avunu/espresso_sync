---
title: Connections and syncs
description: An Espresso Sync Connection's server and credentials, its shots, and what a sync does with their Active transforms.
nav_title: Connections and syncs
order: 1
updated: 2026-11-08
---

An **Espresso Sync Connection** is one external API: where it is, how to authenticate, and what to sync with it. Only a System Manager can create, change or run one.

## Fields

| Field                     | Holds                                                                                                                                        |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Enabled                   | Whether the Connection runs on its Sync Frequency.                                                                                           |
| Sync Frequency, Cron Rule | When it runs (see below).                                                                                                                    |
| API Rate Limit            | The most requests a minute; empty for no limit.                                                                                              |
| Server URL                | The API's base URL, as its spec's `servers` give it (`https://api.example.com/v1`): each transform's operation path is appended to it.       |
| Allowed Host              | The one host (`host`, or `host:port`) the credentials are sent to. Filled from the Server URL, whose host it must be.                        |
| Authentication Type       | Header-based: the API Key field is the header's name, the API Secret its value. Basic: the API Key is the user, the API Secret the password. |
| API Key, API Secret       | The credentials. The secret is a Password field.                                                                                             |
| Shots                     | What the Connection syncs (below).                                                                                                           |

An API Spec belongs to a Connection (its **Connection** field), and so do the transforms built on it.

## Shots

Each shot syncs one DocType:

| Field       | Holds                                                                                                                                        |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| DocType     | The DocType synced.                                                                                                                          |
| Import      | Whether the shot imports, with its **Import Transform**.                                                                                     |
| Export      | Whether the shot exports, with its **Export Transform**, and its **Update Transform** when the API updates an object with another operation. |
| Last Import | The start of the last import in which every item imported.                                                                                   |
| Last Export | The newest change exported before the first document that failed.                                                                            |

A shot's transforms must be Active, of its DocType, in the right direction, and on an API Spec of the Connection; the Connection cannot be saved otherwise. A sync checks again, and a transform that is no longer Active is not run: the shot fails, and the failure is logged.

The **Export Transform** sends the documents this Connection has no external ID for yet: a create, such as `POST /tasks`. When the shot has an **Update Transform**, it sends the documents that have one, such as `PUT /tasks/{id}` with Path Parameters `{"id": $syncId("ToDo", name)}`. Without one, the Export Transform sends every document, which suits an API whose one operation creates or updates.

## When syncs run

**Sync Now** on the Connection form runs one at once, and says how many requests, objects or documents failed. An **Enabled** Connection also runs on its **Sync Frequency**:

| Sync Frequency                 | Runs                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------------- |
| Manual                         | only with Sync Now                                                                     |
| Every Minute                   | on every tick of the scheduler (`scheduler_interval`, every 4 minutes unless changed)  |
| Hourly, Daily, Weekly, Monthly | on the scheduler's hourly, daily, weekly and monthly events                            |
| Cron                           | when its **Cron Rule** (for example `*/15 * * * *`) has come round since the last sync |

Each scheduled sync is a background job on the `long` queue. A Connection never syncs twice at once: a sync is not queued while another of the same Connection is queued or running, and Sync Now is refused while one is running. A scheduled sync that fails waits for its next time like one that succeeded.

## An import

For each shot that imports, the import transform's operation is read from the Server URL:

1. **The request.** The path's parameters and the query come from the transform's **Path Parameters** and **Query Parameters**, evaluated on `{"last_import": …}`, when the last complete import began (absent before the first). `{"updated_since": last_import}` reads only what changed since.
2. **The pages.** After each page, **Next Request** is evaluated on `{body, headers, query}` (the page's body and response headers, and the query it was asked with) and gives the next page's query parameters, merged into the last ones: `$count(body.data) > 0 ? {"page": query.page + 1}`. Nothing, or an empty object, ends the import, and so does **Maximum Pages**.
3. **The response.** A status other than 2XX, or a body that is not JSON, fails the request. Unless Runtime Validation is Off, the body is checked against the operation's response schema, and what that finds is logged as warnings: the items are still imported.
4. **The items**, at the **Items Pointer**. For each, **External ID** gives its id and **Modified**, if set, when it last changed. An item no newer than when it was last imported is skipped, and so is one whose Espresso Sync IDs row is **Disabled**.
5. **The mapping.** The transform's **Active JSONata** maps the item. Runtime Validation checks the result against the DocType: Enforce does not save it when there is an error, Warn saves it and logs the findings.
6. **The document.** The one this Connection imported as that id before is updated, or else the document the mapped `name` names, or else a new one is inserted. On an update, each mapped child table is replaced by the mapped rows, or, with **Merge by Key**, rows with the same key are updated, the other mapped rows added, and the rows already there kept. A document that fails to save leaves nothing behind.

## An export

For each shot that exports, the documents of its DocType changed since **Last Export** (every one, the first time, and after the shot changed) are read, the oldest first. A document with **Exclude from Sync** checked is left out.

1. A document whose last change is one this Connection synced is skipped: what an import saved is not sent back, and what was exported is not sent again.
2. The transform's Active JSONata maps the document, as the export's sample shows it: the document with its child tables, without its Sync IDs. Runtime Validation checks the result against the operation's request body (as a request: a `readOnly` property is flagged).
3. It is sent with the operation's method to its path, the Path and Query Parameters evaluated on the document.
4. A create's response gives the new object's id through **External ID**, which is stored on the document's Espresso Sync IDs and committed at once: the object exists in the API, whatever happens to the rest of the sync. A response without one is logged with a warning, as the next export would create the object again.

## Two-way sync

A shot can import and export. Each Espresso Sync IDs row records the document's **Last Synced** time, when this Connection last imported or exported it, and the item's **External Modified**, when it last changed in the API as last imported. An import saves a document and records it as synced, so the export after it skips the document; an export records the document as synced, so it is not sent again until it changes. A change made in the API comes back once, through the import, and is not sent back.

## The Pull Log

Each **Espresso Sync Pull Log** entry is one request, item or document, with its status (Success or Failure), its DocType and document, the **Transform** that ran and the SHA-256 of its Active JSONata, and the **Diagnostics** that explain it. A request's entry holds its URL, method and response; an item's or a document's holds the object (the item imported, or the body exported) and the document (as saved, or as read). Each failure is logged and the sync goes on with the next request, item or document.

**Last Import** moves to the start of the import only when nothing in it failed. **Last Export** moves only as far as the last document exported before the first failure, and back to just below a failed document older than it, so a document that failed is sent again by the next sync. Every request goes through the Connection's rate limit; an API that answers 429 Too Many Requests is waited for, as its `Retry-After` says (up to a minute), and asked again, at most three more times.
