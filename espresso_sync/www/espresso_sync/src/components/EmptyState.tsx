// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import type { CarbonIconType } from "@carbon/react/icons";

interface EmptyStateProps {
	icon?: CarbonIconType;
	/** What is missing, as a sentence: "No connections yet." */
	title: string;
	/** What that means, or how to get some. */
	children?: ReactNode;
	/** The button that gets some. */
	action?: ReactNode;
}

/** What a list shows in place of its rows when it has none. */
export function EmptyState({ icon: Icon, title, children, action }: EmptyStateProps) {
	return (
		<div className="es-empty-state">
			{Icon && <Icon size={32} aria-hidden="true" className="es-empty-state-icon" />}
			<h2 className="es-empty-state-title">{title}</h2>
			{children && <div>{children}</div>}
			{action && <div className="es-empty-state-action">{action}</div>}
		</div>
	);
}
