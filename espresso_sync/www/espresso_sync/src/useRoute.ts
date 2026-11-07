// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useSyncExternalStore } from "react";
import { parseRoute, type Route } from "../../../public/js/editor/routes.ts";

function subscribe(onChange: () => void): () => void {
	window.addEventListener("hashchange", onChange);
	return () => window.removeEventListener("hashchange", onChange);
}

function getHash(): string {
	return window.location.hash;
}

/** The route in the URL's hash, following it as it changes. */
export function useRoute(): Route {
	return parseRoute(useSyncExternalStore(subscribe, getHash));
}
