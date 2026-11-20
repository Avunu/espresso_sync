// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect, useState } from "react";
import {
	Header,
	HeaderGlobalAction,
	HeaderGlobalBar,
	HeaderMenuButton,
	HeaderMenuItem,
	HeaderName,
	HeaderNavigation,
	HeaderSideNavItems,
	SideNav,
	SideNavItems,
	SkipToContent,
	Theme,
} from "@carbon/react";
import { type CarbonIconType, Home, Renew, WarningAltFilled } from "@carbon/react/icons";
import { plural } from "../../../../public/js/portal/datetime.ts";
import { needsAttention } from "../../../../public/js/portal/health.ts";
import { useConnectionStatus } from "../data/useConnectionStatus";
import { hrefFor, navigate, type Section } from "../route";

/** The id of the page's `Content`, where "Skip to main content" puts the keyboard. */
export const MAIN = "main-content";

/** The page's sections, in the order the header lists them. */
export const SECTION_LABELS: [section: Section, label: string][] = [
	["overview", "Overview"],
	["connections", "Connections"],
	["logs", "Sync log"],
	["transforms", "Transforms"],
	["specs", "API specs"],
];

interface UtilityAction {
	label: string;
	icon: CarbonIconType;
	onClick: () => void;
}

/**
 * The actions at the far end of the toolbar. The last one leaves the page:
 * everyone who can open it is a System Manager, so it goes back to the desk.
 */
const UTILITY_ACTIONS: UtilityAction[] = [
	{ label: "Reload page", icon: Renew, onClick: () => window.location.reload() },
	{ label: "Back to the desk", icon: Home, onClick: () => window.location.assign("/desk") },
];

interface PortalHeaderProps {
	/** The product's name, which links to the Overview. */
	name: string;
	/** The section the page is in: its link is the current one. */
	section: Section;
}

/** How many Connections are failing or overdue, from the status every page polls. */
function useAttentionCount(): number {
	const { rows, now } = useConnectionStatus();
	if (!now) return 0;
	return rows.filter((row) => needsAttention(row, now)).length;
}

/**
 * The toolbar: Carbon's UI Shell header, on the dark g100 theme - light text
 * and icons on a near-black bar, as in IBM's own products - while the page
 * below stays on the light theme set by mountPortal. Fixed at 3rem tall;
 * Carbon's `Content` leaves the room for it. It holds the page's five sections,
 * and a warning while any Connection needs a look.
 */
export function PortalHeader({ name, section }: PortalHeaderProps) {
	const attention = useAttentionCount();
	// The narrow window's menu. Carbon's HeaderContainer would hold this, but it hands out
	// only a toggle, and two of the ways to close a menu can come from one click.
	const [menuOpen, setMenuOpen] = useState(false);
	const closeMenu = () => setMenuOpen(false);
	useEffect(() => {
		if (!menuOpen) return undefined;
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") setMenuOpen(false);
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [menuOpen]);
	const links = (onClick?: () => void) =>
		SECTION_LABELS.map(([to, label]) => (
			<HeaderMenuItem
				key={to}
				href={hrefFor(to)}
				isCurrentPage={to === section}
				{...(onClick ? { onClick } : {})}
			>
				{label}
			</HeaderMenuItem>
		));
	return (
		<Theme theme="g100">
			<Header aria-label={name}>
				<SkipToContent
					href={`#${MAIN}`}
					// the hash is the route: the link moves the keyboard and leaves the hash alone
					onClick={(event) => {
						event.preventDefault();
						document.getElementById(MAIN)?.focus();
					}}
				/>
				{/* Carbon shows it below its `lg` breakpoint, where the links above don't fit */}
				<HeaderMenuButton
					aria-label={menuOpen ? "Close menu" : "Open menu"}
					aria-expanded={menuOpen}
					isActive={menuOpen}
					onClick={() => setMenuOpen((open) => !open)}
				/>
				<HeaderName href={hrefFor("overview")} prefix="">
					{name}
				</HeaderName>
				<HeaderNavigation aria-label={name}>{links()}</HeaderNavigation>
				<HeaderGlobalBar>
					{attention > 0 && (
						<HeaderGlobalAction
							aria-label={`${plural(attention, "connection needs", "connections need")} attention`}
							onClick={() => navigate(hrefFor("connections", undefined, { query: { health: "attention" } }))}
						>
							<WarningAltFilled size={20} style={{ fill: "var(--cds-support-warning)" }} />
						</HeaderGlobalAction>
					)}
					{UTILITY_ACTIONS.map(({ label, icon: Icon, onClick }, index) => (
						<HeaderGlobalAction
							key={label}
							aria-label={label}
							onClick={onClick}
							// A tooltip centered under the last icon would hang off the
							// edge of the screen.
							tooltipAlignment={index === UTILITY_ACTIONS.length - 1 ? "end" : "center"}
						>
							<Icon size={20} />
						</HeaderGlobalAction>
					))}
				</HeaderGlobalBar>
				{/* The same links for a narrow window: an overlay, never a column beside the page. */}
				<SideNav
					aria-label={`${name} menu`}
					expanded={menuOpen}
					isPersistent={false}
					onOverlayClick={closeMenu}
				>
					<SideNavItems>
						{/* a link taken closes the menu: the page changes under it, not away from it */}
						<HeaderSideNavItems>{links(closeMenu)}</HeaderSideNavItems>
					</SideNavItems>
				</SideNav>
			</Header>
		</Theme>
	);
}
