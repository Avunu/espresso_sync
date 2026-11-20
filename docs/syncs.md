---
title: Connections and syncs
description: An Espresso Sync Connection's server and credentials, its shots, and what a sync does with their Active transforms.
nav_title: Connections and syncs
order: 1
updated: 2026-11-20
---

An **Espresso Sync Connection** is one external API: where it is, how to authenticate, and what to sync with it. Only a System Manager can create, change or run one, in the **Connections** section of the `/espresso_sync` page or on the desk form.

## Fields

| Field                     | Holds                                                                                                                                        |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Enabled                   | Whether the Connection runs on its Sync Frequency.                                                                                           |
| Sync Frequency, Cron Rule | When it runs (see below).                                                                                                                    |
| API Rate Limit            | The most requests a minute; empty for no limit.                                                                                              |
| Server URL                | The API's base URL, as its spec's `servers` give it (`https://api.example.com/v1`): each transform's operation path is appended to it.       |
| Allowed Host              | The one host (`host`, or `host:port`) the credentials are sent to. Filled from the Server URL, whose host it must be.                        |
| Authentication Type       | Header-based: the API Key field is the header's name, the API Secret its value. Basic: the API Key is the user, the API Secret the password. |
| API Key, API Secret       | The credentials. The secret is a Password field: it can be set, replaced or removed, and is never shown.                                     |
| Shots                     | What the Connection syncs (below).                                                                                                           |

An API Spec belongs to a Connection (its **Connection** field), and so do the transforms built on it.

### In the page

**New connection** asks for the name, the Server URL and the credentials, and makes a Connection that is not Enabled and syncs only with Sync now. The rest is on the Connection's **Settings** tab:

- **The secret box is always empty.** Leave it empty to keep the stored secret, type one to replace it, or use **Remove stored secret**. The tab says whether a secret is stored.
- **Enabled** is a switch in the Connection's header and in the list, not a field of Settings: it takes effect at once (see [Pausing a Connection](#pausing-a-connection)).
- **A Cron Rule** shows the next three times it fires, in the site's time. A rule that reads as one and never fires, such as `0 0 30 2 *`, is refused.
- **Settings cannot be saved while the Connection is queued or syncing.**
- **Renaming** is done in the desk: the names of a Connection's API Specs begin with its name.

### Test connection

**Test connection**, in a Connection's header, sends one `GET` to the saved Server URL with the saved credentials and says how it was answered: the host reached, the status, the time taken, and whether the credentials were sent. It uses what is saved, so it is off while Settings has unsaved changes. The credentials go to the Allowed Host only, as in a sync, and neither the response nor the secret comes back to the page. Nothing is written to the Pull Log.

| Answer                     | Means                                                                                                       |
| -------------------------- | ----------------------------------------------------------------------------------------------------------- |
| a status below 400         | The API was reached and accepted the request.                                                               |
| 401 or 403                 | The API was reached and refused the credentials.                                                            |
| another 4XX                | The API was reached. The Server URL itself may not be something it answers a `GET` on.                      |
| 5XX                        | The API was reached and failed.                                                                             |
| no status, with the reason | The API was not reached: the host, the network, or [where requests may go](api-specs.md#where-requests-go). |

At most 10 tests a minute are sent.

### Deleting a Connection

**Delete**, in the page, asks for the Connection's name to be typed and then deletes the Connection, every Pull Log entry of it, and its documents' Espresso Sync IDs rows. The synced documents stay, and so does their Sync tab. It is refused while the Connection is queued or syncing, and while it has API Specs: delete those, and their transforms, first. The desk's delete removes neither the log entries nor the rows, and Frappe refuses it while any of them names the Connection.

## Shots

Each shot syncs one DocType:

| Field       | Holds                                                                                                                                                                                                                     |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DocType     | The DocType synced.                                                                                                                                                                                                       |
| Import      | Whether the shot imports, with its **Import Transform**.                                                                                                                                                                  |
| Export      | Whether the shot exports, with its **Export Transform**, its **Update Transform** when the API updates an object with another operation, and its **Follow-up Transform** for what the API sets with a request of its own. |
| Last Import | The start of the last import in which every item imported.                                                                                                                                                                |
| Last Export | The newest change exported before the first document that failed.                                                                                                                                                         |

In the page, a Connection's **Shots** tab adds, edits, reorders and removes its shots, and offers the transforms on the Connection's API Specs for each. A shot's DocType is chosen when it is added and does not change after. Shots cannot be changed while the Connection is queued or syncing.

A shot's transforms must be Active, of its DocType, in the right direction, and on an API Spec of the Connection; the Connection cannot be saved otherwise. A sync checks again, and a transform that is no longer so is not run: the shot fails, and the failure is logged.

The **Export Transform** sends the documents this Connection has no external ID for yet: a create, such as `POST /tasks`. When the shot has an **Update Transform**, it sends the documents that have one, such as `PUT /tasks/{id}` with Path Parameters `{"id": $syncId("ToDo", name)}`. Without one, the Export Transform sends every document, which suits an API whose one operation creates or updates.

A **Follow-up Transform** sends a second request for each document the shot sent, for what the API sets with an operation of its own: a task put under another with `POST /tasks/{id}/links`, with Path Parameters `{"id": $syncId("ToDo", parent)}` and a body that holds the id of the task just sent. It is an Export transform like the others, evaluated on the document, and it can also read `$response`: the answer to the request just sent (a create's or an update's), as JSON. That is how it learns what only the answer holds, such as the id the API gave a new object, and it can skip itself with **Skip When** when the answer shows the relation is already there (`$response.parent = parentId`). See [An export](#an-export).

## When syncs run

**Sync now**, on a Connection in the page, or **Sync Now** on the desk form, queues one at once; the Sync log shows how it went. The page refuses it for a Connection that is not Enabled, whose sync would do nothing. **Resync everything**, in the Connection's actions in the page, or **Resync** on the desk form, first resets every shot's Last Import and Last Export, so that the sync reads and sends everything again (what is already synced is skipped, as in any sync): for after a change to what a sync skips (see [Choosing what syncs](#choosing-what-syncs)). It is refused while the Connection is syncing, and a Connection that is not Enabled is only reset. An **Enabled** Connection also runs on its **Sync Frequency**:

| Sync Frequency                 | Runs                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------------- |
| Manual                         | only with Sync Now                                                                     |
| Every Minute                   | on every tick of the scheduler (`scheduler_interval`, every 4 minutes unless changed)  |
| Hourly, Daily, Weekly, Monthly | on the scheduler's hourly, daily, weekly and monthly events                            |
| Cron                           | when its **Cron Rule** (for example `*/15 * * * *`) has come round since the last sync |

Each sync, scheduled or Sync Now, is the same background job on the `long` queue, and runs as Administrator, whoever queued it: what it reads and exports does not depend on who clicked Sync Now. A Connection never syncs twice at once: a sync is not queued while another of the same Connection is queued or running. A scheduled sync that fails waits for its next time like one that succeeded.

### Health

The page gives each Connection one health, from what it logged since its last sync began. The first line that applies names it:

| Health        | When                                                                                                                                                                       |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Syncing       | A sync of it is running.                                                                                                                                                   |
| Queued        | A sync of it waits for a worker.                                                                                                                                           |
| Paused        | It is not Enabled.                                                                                                                                                         |
| Failing       | A shot's transform is missing, not Active, or not of the shot's DocType, direction or Connection; or the last sync did not finish; or it logged failures and nothing else. |
| Some failures | The last sync logged failures, and synced other things.                                                                                                                    |
| Overdue       | Its Sync Frequency should have run it by now: is the scheduler running?                                                                                                    |
| Never synced  | It has not synced yet.                                                                                                                                                     |
| Healthy       | None of the above.                                                                                                                                                         |

Failing, Some failures and Overdue are what the page counts as needing attention. A Connection is Overdue when its last sync began more than 15 minutes ago for Every Minute, 2 hours for Hourly, 48 hours for Daily, 14 days for Weekly and 62 days for Monthly, or when its Cron Rule's time passed more than 15 minutes ago. The page asks again every 30 seconds, and every 5 while a Connection is queued or syncing.

### Sync now is the retry

There is no retry of one entry, and no sync of one shot. A sync takes up what the last one left: an import that had a failure reads again from its Last Import, and an export sends again each document from the first that failed (see [The Pull Log](#the-pull-log)). So after fixing what a failure names, **Sync now** tries it again, and so does the next scheduled sync.

### After a shot or the Connection is saved

A shot exports only the documents changed since its Last Export, unless the shot was saved since the Connection last synced. Saving the Connection saves its shots, so after a change to Settings or to any shot, the next sync reads every document of each exporting shot again. Documents whose last change was already synced are skipped, so nothing is sent twice; the sync only takes longer.

### Pausing a Connection

Turning **Enabled** off pauses a Connection: it is left out of the schedule, and Sync now is refused. A sync that is running finishes. Pausing does not check the Connection, so one that cannot be saved (a shot's transform went back to Draft) can still be paused. Turning Enabled on saves the Connection, so everything is checked, and it is refused until the shots are right.

### Resetting one shot

**Reset last import** and **Reset last export**, on a shot in the Shots tab, clear that one date, so the shot's next sync reads or sends everything again, as Resync everything does for every shot. Nothing is queued: run Sync now after, or wait for the schedule. Like Resync, a reset is refused while the Connection is syncing.

## An import

For each shot that imports, the import transform's operation is read from the Server URL:

1. **The request.** The path's parameters and the query come from the transform's **Path Parameters** and **Query Parameters**, evaluated on `{"last_import": …}`, when the last complete import began (absent before the first). `{"updated_since": last_import}` reads only what changed since.
2. **The pages.** After each page, **Next Request** is evaluated on `{body, headers, query}` (the page's body and response headers, and the query it was asked with) and gives the next page's query parameters, merged into the last ones: `$count(body.data) > 0 ? {"page": query.page + 1}`. Nothing, an empty object, or one whose values are all `null` (`{"cursor": body.next}` when `next` is `null`) ends the import. An import that reads **Maximum Pages** while Next Request still gives another page fails, so Last Import stays where it was and the next import reads the pages left.
3. **The response.** A status other than 2XX, or a body that is not JSON, fails the request. Unless Runtime Validation is Off, the body is checked against the operation's response schema, and what that finds is logged as warnings: the items are still imported.
4. **The items**, at the **Items Pointer**. For each, **Skip When**, if the transform has one, is evaluated first: an item it gives true for is skipped. Then **External ID** gives its id and **Modified**, if set, when it last changed. An item no newer than when it was last imported or exported is skipped, and so is one whose Espresso Sync IDs row is **Disabled**. When the shot also exports, a document changed here since it was last synced is not overwritten: the export sends the change. When the item is newer in the API too, the import of it fails as a `conflict`, and the export overwrites the API's change.
5. **The mapping.** The transform's **Active JSONata** maps the item. Runtime Validation checks the result against the DocType: Enforce does not save it when there is an error, Warn saves it and logs the findings.
6. **The document.** The one this Connection imported as that id before is updated, or else the document the mapped `name` names, or else a new one is inserted. On an update, each mapped child table is replaced by the mapped rows, or, with **Merge by Key**, rows with the same key are updated, the other mapped rows added, and the rows already there kept. A document that fails to save leaves nothing behind. What the import saved is not sent back by the next export: its Sync ID row records the document as synced. With **Export What It Saves** set on the import transform, the next export sends it: for an import that only links documents to the API's items (mapping `name` to the document the item belongs to, found with `$localName` on another Connection, say), and has none of the API's data to give them.

## An export

For each shot that exports, the documents of its DocType changed since **Last Export** (every one, the first time, and after the shot changed) are read, the oldest first. A document with **Exclude from Sync** checked is left out.

1. A document whose last change is one this Connection synced is skipped: what an import saved is not sent back, and what was exported is not sent again. So is one that **Skip When** gives true for, of the transform that would send it: the Export Transform for a document with no external ID yet, the Update Transform for one with.
2. The transform's Active JSONata maps the document, as the export's sample shows it: the document with its child tables, without its Sync IDs. Runtime Validation checks the result against the operation's request body (as a request: a `readOnly` property is flagged).
3. It is sent with the operation's method to its path, the Path and Query Parameters evaluated on the document.
4. A create's response gives the new object's id through **External ID**, which is stored on the document's Espresso Sync IDs and committed at once: the object exists in the API, whatever happens to the rest of the sync. A response without one is logged with a warning, as the next export would create the object again.
5. When the shot also imports, the import transform's **Modified**, evaluated on the response of a create or an update, gives when the object changed in the API, recorded as its **External Modified**: the next import does not read back what was exported.
6. With a **Follow-up Transform**, a document that was sent (steps 2 to 5) is not synced yet: its follow-up request goes once every document has been sent, in the same order, so a document that points to another finds the other's id even when it changed first. The follow-up is mapped, validated and sent as in steps 2 and 3, on the same document, with `$response` the answer to the request that was just sent. A document its **Skip When** gives true for is synced without one, and is not logged. When the follow-up fails, the failure is logged, and the document stays unsynced: Last Export stays below it, and the next export sends it again, as an update (a create stored its id at step 4), and its follow-up after it. A follow-up that cannot be built for want of an id (a Path Parameter that gives nothing, because the document it points to has none) fails the same way, and goes when that document has one.

A document whose last change was synced is not sent again, so a Follow-up Transform added to a shot goes only for the documents that change after it. To send it for the others, clear the **Last Synced** of their Espresso Sync IDs row (**Sync again next time**, in the Connection's [Linked documents](#linked-documents) tab, or the row on the document's Sync tab), and Resync.

## Two-way sync

A shot can import and export: in each sync, the import runs first. Each Espresso Sync IDs row records the document's **Last Synced** time, when this Connection last imported or exported it, and the item's **External Modified**, when it last changed in the API as last imported or exported. An import saves a document and records it as synced, so the export after it skips the document; an export records the document as synced, so it is not sent again until it changes, and, through the import transform's Modified on the response, records the object's change in the API, so the import does not read it back. A change made in the API comes back once, through the import, and is not sent back. A change made here is never overwritten by the import before the export sends it; when the item changed in the API too, the change made here wins, and the conflict is logged. Without a Modified, an import cannot tell a changed item from an unchanged one: it reads every item again, and skips those changed here.

## Choosing what syncs

A shot syncs every document of its DocType, and an import every item the API gives. **Skip When** narrows that: a JSONata expression on each item an import reads, or each document an export would send. When it gives true, as JSONata's `$boolean` reads it, the item or document is skipped as if it were not there: nothing is saved, sent or logged, and an export counts it as done, so Last Export moves past it. An error in it fails that item or document alone, as any mapping error does. An import evaluates it on the API's item, before anything else, so it reads the API's own fields; an export evaluates it on the document, as the transform that would send it has it.

Nothing at all does not skip, and neither does `$not` of nothing (JSONata's `$not(undefined)` is undefined): to test for what is missing, use `$exists`.

For example, to sync a Task only when its Project has been given an id by hand:

1. Add a shot for Project with **Import** and **Export** both off, and save the Connection while it is Enabled: the shot syncs nothing, and gives Project the **Sync** tab, with its Espresso Sync IDs.
2. On each Project to sync, add a row to Espresso Sync IDs: this Connection, and the **External ID** the API knows the project by. In the page, that is **Link a document** in the Connection's Linked documents tab; in the desk, the Project's Sync tab.
3. On the export transforms (a create and an update), Path Parameters can use `$syncId("Project", project)`, and **Skip When** is `$not($exists($syncId("Project", project)))`: a task with no project is skipped too. On the import transform, which reads the API's items, Skip When asks the item's own field for the project, for example `$not($exists($localName("Project", repository)))` when the item names its repository: `$localName` gives the name of the Project with that External ID.

A document or item that is skipped is done as far as Last Export goes, and, for an import whose request reads only what changed since `last_import` (as `{"updated_since": last_import}` does), as far as Last Import goes. So when something Skip When reads changes elsewhere (the Project's id is added), what it skipped is not read again until it changes: run **Resync**. An import whose request does not read `last_import` reads every item each sync, and needs no Resync.

A document that was synced and is now skipped is left as it is, and an import of its item is no longer kept from it by a change made here: nothing will send that change. Disabling a Project's Espresso Sync IDs row does not change what `$syncId` gives, so it does not skip the Project's tasks: delete the row.

## Linked documents

A Connection's **Linked documents** tab lists the Espresso Sync IDs rows of that Connection, across every DocType: each document, its External ID, when it was last synced and when the API last changed it. It can be searched by document or External ID and narrowed to one DocType, or to the documents that are not syncing. The same rows are on each document's **Sync** tab in the desk.

| In the page          | Does                                                                                                                                                                          | In the desk, on the document's Sync tab |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Link a document      | Adds a row: a document of one of the Connection's shot DocTypes, and its External ID. A document has one row on a Connection, and an External ID one document of its DocType. | Add a row                               |
| Edit external ID     | Changes the id the API knows the document by. An empty one is refused while the document syncs.                                                                               | Edit **External ID**                    |
| The Sync switch      | Off keeps the document out of this Connection's imports and exports. The row stays. A row without an External ID cannot be switched on: give it one first.                    | The row's **Disabled** box              |
| Sync again next time | Clears Last Synced and External Modified, so the next sync takes the document as changed on both sides.                                                                       | Clear the two dates                     |
| Remove link          | Deletes the row. The document and the API's object stay, and the next sync may create one of them again.                                                                      | Delete the row                          |

A change made in the page writes the row alone: the document is not saved, so its Modified does not move and the change is not itself exported. A change made in the desk saves the document. Both need write permission on the document as well as on the Connection.

## The Pull Log

Each **Espresso Sync Pull Log** entry is one request, item or document, with its status (Success or Failure), its DocType and document, the **Transform** that ran and the SHA-256 of what ran (its Active JSONata and the fields a sync reads), and the **Diagnostics** that explain it. A request's entry holds its URL, method and response; an item's or a document's holds the object (the item imported, or the body exported) and the document (as saved, or as read). Each failure is logged and the sync goes on with the next request, item or document.

In the page, the **Sync log** section lists the entries, newest first, by Connection, status, direction, DocType, period and document; a Connection's own tab shows its entries, and **What is failing** groups the failures of each Connection's last sync by error, transform and DocType. An entry opens to its diagnostics, the API object, the document, the response and the traceback, with a hint for the commonest errors. The desk's Espresso Sync Pull Log list has the same entries.

Entries are deleted after 30 days. **Log retention**, in the Sync log's menu, changes that, from 1 day to 3650: it sets the Espresso Sync Pull Log row of Frappe's **Log Settings**, where it can be changed too. **Clear entries** deletes entries at once: those the current filters show, all of one Connection, or, with `all` typed, every entry. It can delete by status, direction, DocType and transform; with a period, a document or an error code among the filters, it offers only all of the Connection or every entry. Only entries are deleted, never a document or a link.

**Last Import** moves to the start of the import only when nothing in it failed. **Last Export** moves only as far as the last document exported before the first failure, and back to just below a failed document older than it, so a document that failed is sent again by the next sync. Every request goes through the Connection's rate limit; an API that answers 429 Too Many Requests is waited for, as its `Retry-After` says (up to a minute), and asked again, at most three more times.
