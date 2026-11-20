// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect, useState } from "react";
import { hrefFor, parseHash, type Route } from "../../../public/js/portal/routes.ts";

// The routes themselves are read and written in public/js/portal/routes.ts, which the
// unit tests share: this file adds what needs the window.
export * from "../../../public/js/portal/routes.ts";

/** The desk form of a document: where a Connection is renamed, and a synced document opens. */
export function deskFormUrl(doctype: string, name?: string): string {
	const slug = doctype.toLowerCase().replaceAll(" ", "-");
	return `/desk/${slug}/${name === undefined ? "new" : encodeURIComponent(name)}`;
}

/** The current route, following the URL hash. Links are plain `href="#/..."`
 * anchors, so Back, bookmarks and shared links all work with no router. */
export function useRoute(): Route {
	const [route, setRoute] = useState(() => parseHash(window.location.hash));
	useEffect(() => {
		const onChange = () => setRoute(parseHash(window.location.hash));
		window.addEventListener("hashchange", onChange);
		return () => window.removeEventListener("hashchange", onChange);
	}, []);
	return route;
}

/**
 * Put `query` in place of the current route's: a page's filters, its page number. The
 * section, the record and the tab stay, and so does the history entry, so Back leaves
 * the page instead of undoing one filter at a time. A key with no value is dropped.
 */
export function replaceQuery(query: Record<string, string | undefined>): void {
	const { section, name, tab } = parseHash(window.location.hash);
	const href = hrefFor(section, name, { tab, query });
	if (href === window.location.hash) return;
	window.history.replaceState(window.history.state, "", href);
	// replaceState fires no event of its own, and useRoute() listens for this one
	window.dispatchEvent(new HashChangeEvent("hashchange"));
}

/**
 * Go to one of the page's own `#/` links from a control that cannot be an anchor (a
 * header action, a menu item). It goes as a click on a link, so whatever guards the
 * page's links (see useUnsavedGuard) guards this too.
 */
export function navigate(href: string): void {
	const link = document.createElement("a");
	link.href = href;
	link.hidden = true;
	document.body.append(link);
	link.click();
	link.remove();
}
