// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { CSSProperties } from "react";
import { InlineLoading } from "@carbon/react";
import {
	type CarbonIconType,
	CheckmarkFilled,
	CircleDash,
	ErrorFilled,
	PauseOutlineFilled,
	Pending,
	UnknownFilled,
	WarningAltFilled,
} from "@carbon/react/icons";
import type { HealthKind } from "../../../../public/js/portal/health.ts";

export type StatusKind = HealthKind | "success" | "failure";

interface StatusIndicatorProps {
	/** A Connection's health, or a log entry's outcome. */
	kind: StatusKind;
	/** The status in words: it is never told by the icon or its colour alone. */
	label: string;
	/** Why, on a second line. */
	reason?: string | undefined;
}

/** The icon of each status but "running", which turns, and its Carbon colour token. */
const ICONS: Record<Exclude<StatusKind, "running">, [CarbonIconType, string]> = {
	healthy: [CheckmarkFilled, "--cds-support-success"],
	success: [CheckmarkFilled, "--cds-support-success"],
	failing: [ErrorFilled, "--cds-support-error"],
	failure: [ErrorFilled, "--cds-support-error"],
	warning: [WarningAltFilled, "--cds-support-warning"],
	queued: [Pending, "--cds-icon-secondary"],
	paused: [PauseOutlineFilled, "--cds-icon-secondary"],
	never: [CircleDash, "--cds-icon-secondary"],
	unknown: [UnknownFilled, "--cds-icon-secondary"],
};

const ROW: CSSProperties = {
	display: "inline-flex",
	alignItems: "center",
	gap: "var(--cds-spacing-03)",
	whiteSpace: "nowrap",
};
const REASON: CSSProperties = {
	color: "var(--cds-text-secondary)",
	fontSize: "var(--cds-label-01-font-size)",
	lineHeight: "var(--cds-label-01-line-height)",
};

/** A status as Carbon shows one: an icon in its support colour beside the words. */
export function StatusIndicator({ kind, label, reason }: StatusIndicatorProps) {
	let status;
	if (kind === "running") {
		status = <InlineLoading status="active" description={label} style={{ minBlockSize: 0 }} />;
	} else {
		const [Icon, color] = ICONS[kind];
		status = (
			<span style={ROW}>
				<Icon aria-hidden="true" style={{ flexShrink: 0, fill: `var(${color})` }} />
				<span>{label}</span>
			</span>
		);
	}
	if (!reason) return status;
	return (
		<span style={{ display: "inline-flex", flexDirection: "column", gap: "var(--cds-spacing-01)" }}>
			{status}
			<span style={REASON}>{reason}</span>
		</span>
	);
}
