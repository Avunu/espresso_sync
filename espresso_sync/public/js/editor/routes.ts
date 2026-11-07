// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * The page's routes, kept in the URL's hash so the server only ever serves
 * /espresso_sync and a reload (or a shared link) lands on the same screen:
 *
 * - `#/`: the Connections, and the specs and transforms built on them;
 * - `#/specs/<name>`: one API spec;
 * - `#/transforms/<name>`: one transform, in the editor.
 */

export type Route =
	| { page: "home" }
	| { page: "spec"; name: string }
	| { page: "transform"; name: string }
	| { page: "not-found"; hash: string };

function decode(segment: string): string | undefined {
	try {
		return decodeURIComponent(segment);
	} catch {
		return undefined;
	}
}

/** The route a `location.hash` names. */
export function parseRoute(hash: string): Route {
	const path = hash.replace(/^#/, "").replace(/^\/+/, "").replace(/\/+$/, "");
	if (path === "") return { page: "home" };
	const [section, rawName, ...rest] = path.split("/");
	const name = rawName === undefined || rawName === "" ? undefined : decode(rawName);
	if (name !== undefined && rest.length === 0) {
		if (section === "specs") return { page: "spec", name };
		if (section === "transforms") return { page: "transform", name };
	}
	return { page: "not-found", hash };
}

/** The hash for a route: `href(parseRoute(h))` gives back the canonical form of `h`. */
export function href(route: Route): string {
	switch (route.page) {
		case "home":
			return "#/";
		case "spec":
			return `#/specs/${encodeURIComponent(route.name)}`;
		case "transform":
			return `#/transforms/${encodeURIComponent(route.name)}`;
		case "not-found":
			return route.hash;
	}
}

/** The desk form of a document, where a Connection's credentials are edited. */
export function deskFormUrl(doctype: string, name?: string): string {
	const slug = doctype.toLowerCase().replaceAll(" ", "-");
	return `/desk/${slug}/${name === undefined ? "new" : encodeURIComponent(name)}`;
}
