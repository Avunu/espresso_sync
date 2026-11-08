<!-- Copyright (c) 2026, Avunu LLC and contributors
For license information, please see license.txt-->

<!-- frappe-nix:begin header -->

<div align="center">

<img src="espresso_sync/public/images/espresso_sync-logo.svg" width="80" alt="">

# Espresso Sync

Two-way REST API sync: JSONata transforms checked against OpenAPI and DocTypes

[![CI](https://github.com/Avunu/espresso_sync/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Avunu/espresso_sync/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Avunu/espresso_sync)](https://github.com/Avunu/espresso_sync/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](license.txt)
[![Frappe v16](https://img.shields.io/badge/Frappe-v16-blue)](https://github.com/frappe/frappe/tree/version-16)
[![Documentation](https://img.shields.io/badge/docs-docs.avunu.net-blue)](https://docs.avunu.net/espresso-sync/)

</div>

<!-- frappe-nix:end header -->

## Overview

Espresso Sync moves documents between a Frappe site and external REST APIs, in either direction, using the APIs' own OpenAPI descriptions.

- An **Espresso Sync Connection** holds an API's Server URL and credentials. Its **shots** each sync one DocType.
- An **Espresso Sync API Spec** holds the API's OpenAPI 3.1 description: its operations and their request and response schemas.
- An **Espresso Sync Transform** maps one operation's response to a DocType's documents (an import), or documents to one operation's request body (an export), with [JSONata](https://docs.jsonata.org/) rules keyed by the target field. It is checked against both schemas, dry-run on a sample with nothing kept, and activated before a shot can run it.

A sync reads an import's pages, maps each item and inserts or updates its document; an export maps each changed document and sends it. Imported objects are matched to documents through the **Espresso Sync IDs** the app adds to each synced DocType, which also keep a two-way sync from sending a change back where it came from. Every request, object and document is recorded in an **Espresso Sync Pull Log**, with its diagnostics and its credentials redacted.

Syncs run on demand, with **Sync Now** on the Connection form, and on each enabled Connection's **Sync Frequency** (hourly, daily, a cron rule, …) as background jobs. Only a System Manager can configure or run any of it. See the [documentation](docs/README.md).

System Managers work on transforms in the `/espresso_sync` page, opened from the apps screen: it imports an API's OpenAPI description, lists its operations, starts a transform on one, and edits the transform's rules in the **transform editor**, with each rule previewed on sample items and checked against both schemas as it is typed.

<!-- frappe-nix:begin compatibility -->

## Compatibility

| Frappe | Branch       |
| ------ | ------------ |
| v16    | `version-16` |

<!-- frappe-nix:end compatibility -->

<!-- frappe-nix:begin installation -->

## Installation

```bash
bench get-app https://github.com/Avunu/espresso_sync --branch version-16
bench --site <site> install-app espresso_sync
```

<!-- frappe-nix:end installation -->

<!-- frappe-nix:begin support -->

## Support

- Documentation: [docs.avunu.net/espresso-sync/](https://docs.avunu.net/espresso-sync/)
- Bug reports and questions: [GitHub issues](https://github.com/Avunu/espresso_sync/issues)
- E-mail: <mail@avu.nu>

<!-- frappe-nix:end support -->

<!-- frappe-nix:begin development -->

## Development

```bash
nix develop        # or: direnv allow
prek install       # the git hooks CI runs
frappe-test        # the tests, the way CI runs them
```

The managed files, checks and release flow are described in the [app standards documentation](https://docs.avunu.net/frappe-nix/docs/app-standards/).

<!-- frappe-nix:end development -->

<!-- frappe-nix:begin license -->

## License

MIT, Copyright (c) 2023–present Avunu LLC → [license.txt](license.txt)

<!-- frappe-nix:end license -->
