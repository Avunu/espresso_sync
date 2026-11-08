// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useSyncExternalStore } from "react";
import { isAnchorHash, parseRoute, type Route } from "../../../public/js/editor/routes.ts";

function subscribe(onChange: () => void): () => void {
	window.addEventListener("hashchange", onChange);
	return () => window.removeEventListener("hashchange", onChange);
}

/** The last hash that named a route: an in-page anchor in the URL leaves the screen as it was. */
let routeHash = "";

function getHash(): string {
	const hash = window.location.hash;
	if (!isAnchorHash(hash)) routeHash = hash;
	return routeHash;
}

/** The route in the URL's hash, following it as it changes. */
export function useRoute(): Route {
	return parseRoute(useSyncExternalStore(subscribe, getHash));
}
