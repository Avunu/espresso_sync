// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { CheckmarkFilled, ErrorFilled, InformationFilled, WarningAltFilled } from "@carbon/react/icons";
import type { Severity } from "../../../../public/js/editor/diagnostics.ts";

/** Carbon's status icon for a finding, in its support colour; "ok" for none. */
export function SeverityIcon({ severity }: { severity: Severity | "ok" }) {
	switch (severity) {
		case "error":
			return <ErrorFilled aria-hidden="true" style={{ fill: "var(--cds-support-error)" }} />;
		case "warning":
			return <WarningAltFilled aria-hidden="true" style={{ fill: "var(--cds-support-warning)" }} />;
		case "info":
			return <InformationFilled aria-hidden="true" style={{ fill: "var(--cds-support-info)" }} />;
		default:
			return <CheckmarkFilled aria-hidden="true" style={{ fill: "var(--cds-support-success)" }} />;
	}
}
