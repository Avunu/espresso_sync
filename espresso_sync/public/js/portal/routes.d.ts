/**
 * The portal's hash routes, read and written as plain strings: `#/logs`,
 * `#/connections/Shop/shots?page=2`. No React and no `window`, so the page's
 * `route.ts` and the unit tests share one reading of a link.
 */
export declare const SECTIONS: readonly ["overview", "connections", "logs", "transforms", "specs"];
export type Section = (typeof SECTIONS)[number];
/** The tabs of a Connection that have a segment of their own; Activity has none. */
export declare const CONNECTION_TABS: readonly ["shots", "links", "settings"];
export type ConnectionTab = (typeof CONNECTION_TABS)[number];
/** Where the page is: a section, one record in it, a Connection's tab, and the
 * `?key=value` filters of the page. */
export interface Route {
    section: Section;
    name: string | undefined;
    tab: ConnectionTab | undefined;
    query: Readonly<Record<string, string>>;
}
/** What `hrefFor` takes beyond a section and a name. */
export interface HrefOptions {
    tab?: ConnectionTab | undefined;
    query?: Record<string, string | undefined> | undefined;
}
/** `#/specs/Shop%20API` → specs, Shop API; `#/connections/Shop/shots?page=2` →
 * connections, Shop, the shots tab, page 2. Anything else lands on the Overview,
 * so an old or mistyped link still opens the page. */
export declare function parseHash(hash: string): Route;
/** The link to a section, to one record in it, or to a Connection's tab, with
 * the filters that have a value. */
export declare function hrefFor(section: Section, name?: string, options?: HrefOptions): string;
