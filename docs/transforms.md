---
title: Transforms
description: An Espresso Sync Transform maps an API operation's objects to a DocType's documents, or documents to an operation's request body, with JSONata rules.
nav_title: Transforms
order: 3
updated: 2026-11-08
---

An **Espresso Sync Transform** maps one way between a DocType and one operation of an [API Spec](api-specs.md): an **Import** maps the objects of the operation's response to documents of the DocType, an **Export** maps documents of the DocType to the operation's request body. The DocType is always one side.

Only a System Manager can see or change a Transform or call the endpoints below.

## Fields

| Field                             | Holds                                                                                                                                                       |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Title                             | The name.                                                                                                                                                   |
| Direction                         | Import or Export. It cannot be changed once saved.                                                                                                          |
| Status                            | Draft or Active. Only an Active transform runs. It is set by activating the transform, and back to Draft by a change to what a sync reads (below).          |
| DocType                           | The DocType of the documents (not a child table or a Single).                                                                                               |
| API Spec, Method, Path            | The operation, as the spec has it (`GET`, `/orders/{id}`).                                                                                                  |
| Items Pointer                     | Import: where the items are in the response, a JSON Pointer such as `/data`. Empty: the response is the item, or the list of items.                         |
| Path Parameters, Query Parameters | JSONata giving an object: `{"id": $syncId("Customer", customer)}`. An import's are evaluated on `{last_import}`, an export's on the document.               |
| Next Request, Maximum Pages       | Import: JSONata evaluated on the last page (`{body, headers, query}`) that gives the next page's query parameters, and how many pages a sync reads at most. |
| External ID                       | JSONata giving the object's id in the API: on the item for an import, which needs one, and on a create's response for an export.                            |
| Modified                          | Import: JSONata giving when the item last changed: an item no newer than when it was last imported is skipped.                                              |
| Runtime Validation                | Enforce, Warn or Off: whether a mapped object that fails the target's schema is still saved or sent when a sync runs.                                       |
| Child Tables, Child Table Keys    | Import: on an update, Replace sets each mapped child table to the mapped rows; Merge by Key matches rows by a JSONata key per table.                        |
| Rules                             | The rules (below).                                                                                                                                          |
| Compiled JSONata, Active JSONata  | The rules as one expression, and that expression as it was when the transform was activated: what runs.                                                     |
| Sample                            | Source items the transform is checked and dry-run on.                                                                                                       |
| Diagnostics                       | What the last save found.                                                                                                                                   |

The Connection a transform runs against is its API Spec's. The Connection's **Server URL** (`https://api.example.com/v1`) is the base the operation's path is appended to. A shot of that Connection runs the transform once it is Active: see [Connections and syncs](syncs.md) for what a sync does with it.

## Rules

A rule fills the target field at its JSON Pointer with the value of its [JSONata](https://docs.jsonata.org/) expression, evaluated on the source item:

```json
[
	{ "ptr": "/customer_name", "kind": "field", "expr": "name" },
	{ "ptr": "/items", "kind": "collection", "expr": "line_items" },
	{ "ptr": "/items/item_code", "kind": "field", "expr": "sku" },
	{ "ptr": "/tags", "kind": "scalar_collection", "expr": "labels.name" }
]
```

- A `field` rule gives a value. A key whose expression gives nothing (JSONata's undefined) is left out; `null` is kept.
- A `collection` rule gives the items of an array of objects. The rules under its pointer (`/items/item_code`) fill each object, evaluated on its item.
- A `scalar_collection` rule gives the values of an array of plain values.
- Under a collection's pointer, items are implied, never indexed: `/items/item_code` is the `item_code` of every item. A key with `/` or `~` in it is written `~1` and `~0`, as in any JSON Pointer.

The rules compile to one expression, which is what runs:

```
{
	"customer_name": (name),
	"items": [(line_items).{
		"item_code": (sku)
	}],
	"tags": [(labels.name)]
}
```

A collection is always an array, of one item or none too. The editor compiles in the browser and the server compiles on save, to the same text, byte for byte.

## Functions

Besides JSONata's own, an expression can call:

| Function                              | Gives                                                                                    |
| ------------------------------------- | ---------------------------------------------------------------------------------------- |
| `$syncId(doctype, name)`              | the document's id in the Connection's API (its Espresso Sync IDs row)                    |
| `$localName(doctype, id)`             | the name of the document with that id in the Connection's API                            |
| `$getValue(doctype, name, fieldname)` | a field of a document; for a Single, give its DocType as the name                        |
| `$frappeDate(value)`                  | a date as Frappe stores it, `2026-01-15`                                                 |
| `$frappeDatetime(value)`              | a datetime as Frappe stores it, converted to the system time zone when the value has one |
| `$frappeCheck(value)`                 | 0 or 1, from a boolean, a number or `"true"`, `"false"`, `"1"`, `"0"`                    |

They read the site as the user the transform runs as (in a sync, Administrator; in the editor's checks and dry run, the System Manager using it): a document that user may not read is not found, and a DocType they may not read is an error.

Every evaluation stops after 5 seconds or 200 levels of recursion, with JSONata's D1012 or D1011 error. That is checked between the steps of an evaluation, so regular expressions run on [RE2](https://github.com/google/re2/wiki/Syntax), in time linear in their input: a backreference or a lookaround, which RE2 does not support, is a syntax error.

## Checks

Each diagnostic is `{rule, path, severity, code, message, origin, item}`: `rule` is the pointer of the rule it is about (of the field, for a required one no rule fills) or the name of the field holding the expression, `path` is where in the mapped object (with array indexes), and `item` is the sample item it came from. `origin` is `server`.

On every save:

- the rules compile: a pointer that is not one (or holds a lone surrogate), two rules for one field, a rule under a `field` or `scalar_collection` rule, an empty expression, one of ASCII whitespace only (`compile.*` errors);
- every expression parses (`jsonata.<code>` errors);
- every required field of the target has a rule: the DocType's hard-required fields, including those of a mapped child table, or the request body's required properties (`required-unmapped` errors);
- an import has an External ID (a `required` error on `external_id_expr`): without one, each sync would import every item again.

`validate_transform` also maps the sample:

- an item whose rules fail to evaluate (`eval.<code>`);
- what an item maps to, against the target's schema, as [`validate_payload`](api-specs.md#diagnostics) checks it: the DocType's as an insert, or the request body's;
- an import's Links and Dynamic Links, looked up together for each DocType: a document that does not exist or that the user may not read (`link-missing`), a DocType that does not exist (`link-doctype`), one the user may not read (`link-unreadable`).

The **dry run** maps the sample and, for an import, inserts each document with every hook Frappe runs, then rolls it back: nothing is kept in the database. A commit while it runs is refused, and jobs (however a hook or a Server Script enqueues them), realtime events and emails are not sent. What a hook does outside the database is not undone: one that changes the database's tables still commits, as the database does for such a change, and one that makes an HTTP request makes it. An export's dry run sends nothing.

## Activation

Activating a transform freezes its compiled rules as **Active JSONata**, what a sync runs, and sets it Active. A Draft transform never runs, and a shot cannot link one. It is refused while any check (the dry run aside) finds an error, a required field no rule fills among them, and when the API Spec's operation or the DocType changed since the transform was saved: open it, check it and save it again.

A later change to the rules (or the sample) does not change what runs until the transform is activated again. A change to anything else a sync reads (DocType, API Spec, Method, Path, Items Pointer, Path and Query Parameters, Next Request, Maximum Pages, External ID, Modified, Runtime Validation, Child Tables and their keys) makes the transform a Draft again: it stops running until it is activated with the change, and the checks run on it. That is also how an Active transform goes back to Draft.

## The editor

The `/espresso_sync` page's **transform editor** (`/espresso_sync#/transforms/<name>`) shows the two sides of a transform as trees: the source on the left (an item of the operation's response, after the Items Pointer, for an import; a document of the DocType for an export) and the target on the right (a new document of the DocType; the operation's request body). A line joins each source field a rule reads to the field the rule fills. Groups below the top level start closed; a filter, and **Required only**, **Mapped only** and **Read by a rule only**, narrow the trees. The row height is kept in the browser.

Everything works from the keyboard: Tab moves between the controls and into a tree, the arrow keys move within it and open groups, and Enter or Space selects a field. To map a field, select a source field, then a target field: the rule reads the source field as it must where it runs (`sku` on a line item, `$$.currency` for the source item's own field from inside a collection). Selecting only a target field opens its rule: its expression, the source fields and functions to insert at the caret (wrapping what is selected), what it gives on each sample item, and its diagnostics.

The rules are evaluated in the browser as they are typed, in a Web Worker that stops a runaway expression, on up to 50 sample items. The app's functions are answered by the server (`resolve_functions`), so the preview gives what a dry run gives. The browser's own checks (the rules that don't compile or parse, the required fields no rule fills, values of the wrong type, the target's schema) are listed with the server's, which **Save** runs, as **Validate** does. A DocType's schema findings are only warnings in the browser: the server knows which values Frappe converts.

The sample is pasted, or fetched 20 items at a time (`fetch_sample`), and saved with the rules; a pasted sample is saved as written, so whole numbers past 2^53, which the browser rounds, stay exact on the server. The **Settings** tab edits the fields a sync reads besides the rules (Items Pointer, parameters, Next Request, External ID, Modified, Runtime Validation, Child Tables), saved with them. **Dry run** compares each item's result with the preview, and **Activate** activates the saved transform: both, and Validate, wait until the changes are saved. As in the desk, Save and Activate are refused when someone else saved the transform since the editor read it (reload to get their version), and Save with no changes saves it as it is, which checks it against the API Spec and the DocType again. The preview runs with the server's limits (5 s, a depth of 200) and refuses the regular expressions the server's RE2 refuses (a lookaround, a backreference).

## Endpoints

All are under `/api/method/espresso_sync.api.transform.<name>`.

| Endpoint             | Arguments                                             | Returns                                                                                        |
| -------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `validate_transform` | `name`                                                | the diagnostics; nothing is written                                                            |
| `dry_run`            | `name` (POST)                                         | for each sample item, `{item, output, name, diagnostics}`                                      |
| `activate_transform` | `name`, `modified` (POST)                             | `{name, status, active_compiled, modified}`                                                    |
| `resolve_functions`  | `calls`, optional `transform` (POST)                  | for each `{function, args}` call (`"getValue"`, without the `$`), `{value}` or `{error, code}` |
| `fetch_sample`       | `name`, optional `start`, `limit` (at most 50) (POST) | `{items, more}`                                                                                |

`fetch_sample` reads an import's items from the operation on the Connection's Server URL, with the Connection's credentials (sent to its Allowed Host only), after the Items Pointer; an export's are documents of the DocType, newest first. It stores nothing.
