// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Header, HeaderGlobalAction, HeaderGlobalBar, HeaderName, SkipToContent, Theme } from "@carbon/react";
import { type CarbonIconType, Home, Renew } from "@carbon/react/icons";

interface UtilityAction {
	label: string;
	icon: CarbonIconType;
	onClick: () => void;
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
				<SkipToContent href="#main-content" />
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
