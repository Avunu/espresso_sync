// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Header, HeaderGlobalAction, HeaderGlobalBar, HeaderName, Theme } from "@carbon/react";
import { type CarbonIconType, Home, Renew } from "@carbon/react/icons";

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

/**
 * The toolbar: Carbon's UI Shell header, on the dark g100 theme - light text
 * and icons on a near-black bar, as in IBM's own products - while the page
 * below stays on the light theme set by mountPortal. Fixed at 3rem tall;
 * Carbon's `Content` leaves the room for it.
 */
export function PortalHeader({ name }: { name: string }) {
	return (
		<Theme theme="g100">
			<Header aria-label={name}>
				<HeaderName href="#" prefix="">
					{name}
				</HeaderName>
				<HeaderGlobalBar>
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
			</Header>
		</Theme>
	);
}
