---
title: Espresso Sync
description: Two-way sync between Frappe documents and external REST APIs.
nav_title: Overview
order: 0
updated: 2026-11-07
---

Espresso Sync moves documents between a Frappe site and external REST APIs, in either direction. It runs on Frappe v16 and needs no other Frappe app.

## How it fits together

- An **Espresso Sync Connection** holds an API's domain, base path, credentials (Basic or a header) and an optional rate limit. Only a System Manager can create, change or run one.
- Each of its **shots** ties one DocType to one endpoint. A shot imports, exports, or both, and has a map for each direction.
- Imported objects are matched to documents through the **Espresso Sync IDs** table the app adds, on a **Sync** tab, to each DocType a shot names. A document's **Exclude from Sync** box keeps it out of exports.
- Every request is recorded in an **Espresso Sync Pull Log**, with its response, and so is every object imported or document exported, with its **Diagnostics**. Credentials are redacted before the log is saved. Log Settings deletes entries older than 30 days; change the period there.

## When syncs run

**Sync Now** on the Connection form runs one at once. An **Enabled** Connection also runs on its **Sync Frequency**:

| Sync Frequency                 | Runs                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------------- |
| Manual                         | only with Sync Now                                                                     |
| Every Minute                   | on every tick of the scheduler (`scheduler_interval`, every 4 minutes unless changed)  |
| Hourly, Daily, Weekly, Monthly | on the scheduler's hourly, daily, weekly and monthly events                            |
| Cron                           | when its **Cron Rule** (for example `*/15 * * * *`) has come round since the last sync |

Each scheduled sync is a background job on the `long` queue. A Connection never syncs twice at once: a sync is not queued while another of the same Connection is queued or running, and Sync Now is refused while one is running. A scheduled sync that fails waits for its next time like one that succeeded.

## What a sync does

- An API that answers 429 Too Many Requests is waited for, as its `Retry-After` says (up to a minute), and asked again, at most three more times.
- A request that fails, an object that cannot be imported, or a document that cannot be exported is logged as a failure in the Pull Log, and the sync goes on with the next one.
- An imported object that matches a document this Connection imported before (by its external ID, within the shot's DocType) updates and saves that document.
- **Last Export** moves only as far as the last document exported before the first failure, and back to just below a failed document older than it (a shot that changed exports every document), so a failed document is sent again by the next sync. **Last Import** moves only when every object imported.

## Maps

A map is a JSON object whose keys are the target's fields and whose values are [JSONata](https://docs.jsonata.org/) expressions over the source object, with a few tags for lookups in the site. See [Object maps](object-mapping.md).

## Status

This map format is being replaced by a schema-aware transform editor driven by the APIs' OpenAPI descriptions. Until then the app is not published to the Frappe marketplace.
