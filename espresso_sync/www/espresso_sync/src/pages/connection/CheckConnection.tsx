// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useCallback, useState } from "react";
import { ActionableNotification, InlineLoading } from "@carbon/react";
import { formatDuration } from "../../../../../public/js/portal/datetime.ts";
import { type CheckResult, METHODS } from "../../data/api";
import { useBackendCall } from "../../portal/useBackendCall";

export interface ConnectionCheck {
	/** Send the test request. */
	run: () => void;
	busy: boolean;
	/** How the last test of this visit was answered. */
	result: CheckResult | null;
	/** Put the answer away. */
	clear: () => void;
}

/**
 * Test connection: one GET to the saved Server URL with the saved credentials, which the
 * server sends to the Allowed Host only. The answer says how the API replied, never with
 * what. A test that couldn't be made at all (too many in a minute) is a toast.
 */
export function useConnectionCheck(connection: string): ConnectionCheck {
	const { call, loading } = useBackendCall<CheckResult>(
		METHODS.checkConnection,
		"The connection couldn't be tested.",
	);
	const [result, setResult] = useState<CheckResult | null>(null);

	const run = useCallback(() => {
		setResult(null);
		void call({ connection }).then((answer) => {
			if (answer.ok) setResult(answer.data);
		});
	}, [call, connection]);
	const clear = useCallback(() => setResult(null), []);

	return { run, busy: loading, result, clear };
}

type Kind = "success" | "warning" | "error";

/** Carbon's own default is "alertdialog", which is for a notice that takes the focus. */
const ROLE = "status";

/** The answer in words: what kind of news it is, the news, and the detail. */
function describe(result: CheckResult): [kind: Kind, title: string, subtitle: string] {
	const { host, verdict } = result;
	const sent = result.credentials_sent ? "credentials sent" : "no credentials sent";
	const answered = [result.status, result.reason].filter(Boolean).join(" ");
	const detail = `${answered} in ${formatDuration(result.elapsed_ms)}, ${sent}.`;
	switch (verdict) {
		case "ok":
			return ["success", `Reached ${host}:`, detail];
		case "auth":
			return [
				"error",
				`${host} refused the request:`,
				result.credentials_sent
					? `${detail} Check the credentials in the settings.`
					: `${detail} Store credentials in the settings, and check that the Allowed Host is ${host}.`,
			];
		case "reachable":
			return [
				"warning",
				`Reached ${host}, which answered with an error:`,
				`${detail} The server is there. The Server URL alone may not be something it answers.`,
			];
		case "error":
			return ["error", `${host} failed:`, `${detail} The API itself has a problem.`];
		default: {
			// nothing got there, so nothing is said of credentials: none arrived
			const why = result.error ?? "No answer";
			return ["error", `${host || "The server"} couldn't be reached:`, /[.!?]$/.test(why) ? why : `${why}.`];
		}
	}
}

interface CheckConnectionProps {
	check: ConnectionCheck;
	/** Whether "Test again" can be pressed: not while the settings have unsaved changes. */
	canRetry: boolean;
}

/** How Test connection went, under the page's header: nothing until it is pressed. */
export function CheckConnection({ check, canRetry }: CheckConnectionProps) {
	if (check.busy) return <InlineLoading status="active" description="Testing the connection…" />;
	if (!check.result) return null;
	const [kind, title, subtitle] = describe(check.result);
	return (
		<ActionableNotification
			inline
			lowContrast
			// it is news, not a question: the keyboard stays on Test connection
			hasFocus={false}
			role={ROLE}
			aria-label="Test connection"
			kind={kind}
			title={title}
			subtitle={subtitle}
			{...(canRetry ? { actionButtonLabel: "Test again", onActionButtonClick: check.run } : {})}
			onClose={() => {
				check.clear();
				return false;
			}}
			style={{ maxInlineSize: "none" }}
		/>
	);
}
