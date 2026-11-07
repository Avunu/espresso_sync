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
- Every request is recorded in an **Espresso Sync Pull Log**: the URL, the request, the response and the document. Credentials are redacted before the log is saved.

Syncs run on demand, with **Sync Now** on the Connection form. The **Sync Frequency** setting is kept but not acted on: scheduled syncs return in a later release.

## Maps

A map is a JSON object whose keys are the target's fields and whose values are [JSONata](https://docs.jsonata.org/) expressions over the source object, with a few tags for lookups in the site. See [Object maps](object-mapping.md).

## Status

This map format is being replaced by a schema-aware transform editor driven by the APIs' OpenAPI descriptions. Until then the app is not published to the Frappe marketplace.
