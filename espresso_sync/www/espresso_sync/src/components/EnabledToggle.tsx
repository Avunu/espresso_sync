// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Toggle } from "@carbon/react";

interface EnabledToggleProps {
	/** The id of the switch; its name hangs on it. */
	id: string;
	/** The Connection, which the switch is named after: there is one a row in the list. */
	connection: string;
	enabled: boolean;
	disabled: boolean;
	onToggle: (enabled: boolean) => void;
}

/**
 * Whether a Connection is Enabled, as a switch that says which: "Enabled" or "Paused"
 * beside it. Carbon's own hidden label would stand there whatever the switch is at, so
 * the name is given apart from it.
 */
export function EnabledToggle({ id, connection, enabled, disabled, onToggle }: EnabledToggleProps) {
	return (
		<>
			<span id={`${id}-name`} className="cds--visually-hidden">
				{`${connection} is enabled`}
			</span>
			<Toggle
				id={id}
				size="sm"
				aria-labelledby={`${id}-name`}
				labelA="Paused"
				labelB="Enabled"
				toggled={enabled}
				disabled={disabled}
				onToggle={onToggle}
			/>
		</>
	);
}
