// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import { Button, ContainedList, ContainedListItem, DataTableSkeleton, Link, Stack } from "@carbon/react";
import { DateTime } from "../../components/DateTime";
import { DescriptionList } from "../../components/DescriptionList";
import { StatusIndicator } from "../../components/StatusIndicator";
import type { ConnectionDetail, StatusRow } from "../../data/api";
import { hrefFor } from "../../route";
import { FailureGroups } from "../logs/FailureGroups";
import { LogsTable } from "../logs/LogsTable";

interface ActivityTabProps {
	/** The Connection as `get_connection` answered. */
	connection: ConnectionDetail;
	/** Its `list_status` row, once that is read. */
	status: StatusRow | undefined;
	/** The server's time of that row. */
	now: string | undefined;
	/** Whether Test connection reached the API during this visit. */
	tested: boolean;
	/** Whether a test is running. */
	testing: boolean;
	onTest: () => void;
}

interface Step {
	title: string;
	done: boolean;
	/** What to do about it, while it is not done. */
	hint: string;
	action?: ReactNode;
}

const HEADING = {
	margin: 0,
	fontSize: "var(--cds-heading-compact-02-font-size)",
	fontWeight: "var(--cds-heading-compact-02-font-weight)",
	lineHeight: "var(--cds-heading-compact-02-line-height)",
} as const;

/** When the Connection syncs next by itself, in words. */
function nextRun(connection: ConnectionDetail, status: StatusRow | undefined): ReactNode {
	if (!connection.enabled) return "Not while it is paused";
	switch (connection.sync_frequency || "Manual") {
		case "Manual":
			return "Only with Sync now";
		case "Cron":
			return status?.next_run ? <DateTime value={status.next_run} /> : "At the cron rule's next time";
		case "Every Minute":
			return "With the scheduler, every few minutes";
		default:
			return `With the ${(connection.sync_frequency ?? "").toLowerCase()} scheduler`;
	}
}

/**
 * `#/connections/<name>`: what is left to set up, how the last sync went, what is
 * failing, and the Connection's own log. "The last sync" is everything logged since the
 * last attempt: there is no record of a run.
 */
export function ActivityTab({ connection, status, now, tested, testing, onTest }: ActivityTabProps) {
	const { name } = connection;
	const failures = status?.failures_last_run ?? 0;
	// the polled row has the times of a sync that the Connection, read once, does not know of yet
	const lastPull = status ? status.last_pull : connection.last_pull;
	const lastAttempt = status ? status.last_sync_attempt : connection.last_sync_attempt;

	const steps: Step[] = [
		{
			title: "Credentials stored",
			done: connection.has_secret,
			hint: "Store the API's key or password.",
			action: <Link href={hrefFor("connections", name, { tab: "settings" })}>Open settings</Link>,
		},
		{
			title: "API spec imported",
			done: connection.setup.specs > 0,
			hint: "Import the API's OpenAPI description for this connection.",
			action: <Link href={hrefFor("specs")}>API specs</Link>,
		},
		{
			title: "A transform is Active",
			done: connection.setup.active_transforms > 0,
			hint:
				connection.setup.transforms > 0
					? "Its transforms are Drafts: activate the one a shot should use."
					: "Make a transform on one of the spec's operations, and activate it.",
			action: (
				<Link href={hrefFor(connection.setup.transforms > 0 ? "transforms" : "specs")}>Transforms</Link>
			),
		},
		{
			title: "A shot is added",
			done: connection.shots.length > 0,
			hint: "A shot syncs one DocType through its transforms.",
			action: <Link href={hrefFor("connections", name, { tab: "shots" })}>Open shots</Link>,
		},
		{
			title: "Tested",
			// a sync that finished reached the API too
			done: tested || Boolean(lastPull),
			hint: "Send a test request with the stored credentials.",
			action: (
				<Button kind="ghost" size="sm" disabled={testing} onClick={onTest}>
					Test connection
				</Button>
			),
		},
		{
			title: "Enabled",
			done: Boolean(connection.enabled),
			hint: "Turn on Enabled, at the top of the page, for it to sync.",
		},
	];
	const done = steps.filter((step) => step.done).length;

	return (
		<Stack gap={7}>
			{done < steps.length && (
				<ContainedList label={`Set up: ${done} of ${steps.length} done`} kind="on-page">
					{steps.map((step) => (
						<ContainedListItem key={step.title}>
							<div
								style={{
									display: "flex",
									flexWrap: "wrap",
									alignItems: "center",
									justifyContent: "space-between",
									gap: "var(--cds-spacing-05)",
								}}
							>
								<StatusIndicator
									kind={step.done ? "success" : "never"}
									label={step.title}
									reason={step.done ? "Done" : step.hint}
								/>
								{!step.done && step.action}
							</div>
						</ContainedListItem>
					))}
				</ContainedList>
			)}

			<Stack gap={5}>
				<h2 style={HEADING}>Last sync</h2>
				<DescriptionList
					label="Last sync"
					items={[
						["Last sync finished", <DateTime key="finished" value={lastPull} now={now} />],
						["Last attempt", <DateTime key="attempt" value={lastAttempt} now={now} />],
						["Next run", nextRun(connection, status)],
						[
							"Failures in the last sync",
							failures > 0 ? (
								<Link
									key="failures"
									href={hrefFor("logs", undefined, {
										query: { connection: name, status: "Failure", since: "attempt" },
									})}
								>
									{failures}
								</Link>
							) : (
								failures
							),
						],
						["Synced in the last sync", status?.successes_last_run ?? 0],
					]}
				/>
			</Stack>

			<FailureGroups connection={name} />

			<Stack gap={5}>
				<h2 style={HEADING}>Log entries</h2>
				{/* The table's own Status filter starts at the failures when the last sync had some,
				    so it waits for the status to say whether it had. */}
				{status ? (
					<LogsTable
						fixed={{ connection: name }}
						showConnection={false}
						query={failures > 0 ? { status: "Failure" } : {}}
					/>
				) : (
					<DataTableSkeleton columnCount={6} rowCount={5} showHeader={false} showToolbar={false} />
				)}
			</Stack>
		</Stack>
	);
}
