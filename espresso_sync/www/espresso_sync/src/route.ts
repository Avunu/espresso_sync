// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect, useState } from "react";

export const SECTIONS = ["connections", "specs", "transforms"] as const;
export type Section = (typeof SECTIONS)[number];

/** Where the page is: a section, and for `#/specs/<name>`, one record in it. */
export interface Route {
	section: Section;
	name: string | undefined;
}

function isSection(value: string | undefined): value is Section {
	return SECTIONS.some((section) => section === value);
}

function decode(text: string): string | undefined {
	try {
		return decodeURIComponent(text);
	} catch {
		return undefined; // a mangled `%` escape
	}
}

/** `#/specs/Shop%20API` → specs, Shop API. Anything else lands on the
 * Connections, so an old or mistyped link still opens the page. */
export function parseHash(hash: string): Route {
	const [section, ...rest] = hash.replace(/^#\/?/, "").split("/");
	if (!isSection(section)) return { section: "connections", name: undefined };
	const name = rest.join("/");
	return { section, name: name ? decode(name) : undefined };
}

export function hrefFor(section: Section, name?: string): string {
	return name ? `#/${section}/${encodeURIComponent(name)}` : `#/${section}`;
}

/** The desk form of a document, where a Connection's credentials are edited. */
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
