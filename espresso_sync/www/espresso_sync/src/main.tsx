// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// The page's entry: Vite builds it to espresso-sync.bundle.<hash>.js (vite.config.ts), which
// index.html loads with bundled_asset().

// IBM Plex, self-hosted: the weights Carbon's type styles use.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/400-italic.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./styles.scss";
import { App } from "./App";
import { mountPortal } from "./portal/mount";

mountPortal(<App />);
