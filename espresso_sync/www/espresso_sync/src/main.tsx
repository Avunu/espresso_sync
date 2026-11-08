// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// The page's entry: Frappe's esbuild builds it through public/js/espresso-sync.bundle.js,
// which index.html loads with include_script().
import { App } from "./App";
import { mountPortal } from "./portal/mount";

mountPortal(<App />);
