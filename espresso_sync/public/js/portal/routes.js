// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt
/**
 * The portal's hash routes, read and written as plain strings: `#/logs`,
 * `#/connections/Shop/shots?page=2`. No React and no `window`, so the page's
 * `route.ts` and the unit tests share one reading of a link.
 */
export const SECTIONS = ["overview", "connections", "logs", "transforms", "specs"];
/** The tabs of a Connection that have a segment of their own; Activity has none. */
export const CONNECTION_TABS = ["shots", "links", "settings"];
function isSection(value) {
    return SECTIONS.some((section) => section === value);
}
function isConnectionTab(value) {
    return CONNECTION_TABS.some((tab) => tab === value);
}
function decode(text) {
    try {
        return decodeURIComponent(text);
    }
    catch {
        return undefined; // a mangled `%` escape
    }
}
/** `a=1&b=x%20y` as an object. A pair with a mangled escape or an empty value
 * is dropped, and the last of a repeated key wins. */
function parseQuery(text) {
    const entries = [];
    for (const pair of text.split("&")) {
        const at = pair.indexOf("=");
        if (at < 1)
            continue;
        const key = decode(pair.slice(0, at));
        const value = decode(pair.slice(at + 1).replaceAll("+", " "));
        if (key && value)
            entries.push([key, value]);
    }
    return Object.fromEntries(entries);
}
function formatQuery(query) {
    const pairs = Object.entries(query ?? {})
        .filter((entry) => Boolean(entry[1]))
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    return pairs.length ? `?${pairs.join("&")}` : "";
}
/** `#/specs/Shop%20API` → specs, Shop API; `#/connections/Shop/shots?page=2` →
 * connections, Shop, the shots tab, page 2. Anything else lands on the Overview,
 * so an old or mistyped link still opens the page. */
export function parseHash(hash) {
    const text = hash.replace(/^#\/?/, "");
    const mark = text.indexOf("?");
    const path = mark < 0 ? text : text.slice(0, mark);
    const query = mark < 0 ? {} : parseQuery(text.slice(mark + 1));
    const [section, ...rest] = path.split("/");
    if (!isSection(section))
        return { section: "overview", name: undefined, tab: undefined, query };
    if (section === "connections" && rest.length === 2 && rest[0] && isConnectionTab(rest[1])) {
        return { section, name: decode(rest[0]), tab: rest[1], query };
    }
    // a name written with a bare `/` (an old link) reads as the whole rest
    const name = rest.join("/");
    return { section, name: name ? decode(name) : undefined, tab: undefined, query };
}
/** The link to a section, to one record in it, or to a Connection's tab, with
 * the filters that have a value. */
export function hrefFor(section, name, options) {
    const record = name ? `/${encodeURIComponent(name)}` : "";
    const tab = name && section === "connections" && options?.tab ? `/${options.tab}` : "";
    return `#/${section}${record}${tab}${formatQuery(options?.query)}`;
}
