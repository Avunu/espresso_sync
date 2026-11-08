// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Header, HeaderGlobalAction, HeaderGlobalBar, HeaderName, SkipToContent, Theme } from "@carbon/react";
import { type CarbonIconType, Home, Renew } from "@carbon/react/icons";
import type { MouseEvent } from "react";

/** The id of App's `<main>`, which the skip link focuses. */
export const MAIN_CONTENT_ID = "main-content";

interface UtilityAction {
	label: string;
	icon: CarbonIconType;
	onClick: () => void;
}

/**
 * Carbon's skip link is a plain `<a href="#main-content">`: followed, it would
 * put `#main-content` in the URL in place of the route (a reload or a shared
 * link would then lose the screen; useRoute only keeps it for this page view).
 * It moves focus to the page's main region instead (App gives it tabIndex -1),
 * leaving the hash alone.
 */
function skipToMain(event: MouseEvent<HTMLAnchorElement>): void {
	event.preventDefault();
	document.getElementById(MAIN_CONTENT_ID)?.focus();
}

/**
 * The actions at the far end of the toolbar. The page is for System Managers,
 * who all have the desk, so the last one goes back to it.
 */
const UTILITY_ACTIONS: UtilityAction[] = [
	{ label: "Reload page", icon: Renew, onClick: () => window.location.reload() },
	{ label: "Back to the desk", icon: Home, onClick: () => window.location.assign("/desk") },
];

/**
 * The toolbar: Carbon's UI Shell header, always on the dark g100 theme (light
 * text and icons on a near-black bar, as in IBM's own products) whatever theme
 * the page below follows. Fixed at 3rem tall, so the page leaves 3rem at the top.
 */
export function PortalHeader() {
	const user = window.portal_boot?.full_name ?? window.portal_boot?.user;
	return (
		<Theme theme="g100">
			<Header aria-label="Espresso Sync">
				<SkipToContent href={`#${MAIN_CONTENT_ID}`} onClick={skipToMain} />
				<HeaderName href="#/" prefix="">
					Espresso Sync
				</HeaderName>
				<HeaderGlobalBar>
					{user && <span className="es-header-user">{user}</span>}
					{UTILITY_ACTIONS.map(({ label, icon: Icon, onClick }, index) => (
						<HeaderGlobalAction
							key={label}
							aria-label={label}
							onClick={onClick}
							// A tooltip centred under the last icon would hang off the screen.
							tooltipAlignment={index === UTILITY_ACTIONS.length - 1 ? "end" : "center"}
						>
							<Icon size={20} />
						</HeaderGlobalAction>
					))}
				</HeaderGlobalBar>
			</Header>
		</Theme>
	);
}
