// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { CSSProperties } from "react";
import {
	Button,
	ClickableTile,
	DataTable,
	DataTableSkeleton,
	IconButton,
	InlineNotification,
	Link,
	OverflowMenu,
	OverflowMenuItem,
	Stack,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableHeader,
	TableRow,
} from "@carbon/react";
import { Add, Connect, Renew } from "@carbon/react/icons";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { describeSchedule } from "../../../../public/js/portal/datetime.ts";
import {
	deriveHealth,
	type Health,
	needsAttention,
	severityRank,
} from "../../../../public/js/portal/health.ts";
import { DateTime } from "../components/DateTime";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusIndicator } from "../components/StatusIndicator";
import { type ActivityDay, METHODS, type StatusRow } from "../data/api";
import { useConnectionStatus } from "../data/useConnectionStatus";
import { type SyncActions, useSyncActions } from "../data/useSyncActions";
import { getErrorMessage } from "../portal/useBackendCall";
import { hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { FailureGroups } from "./logs/FailureGroups";

const HEALTH_HEADERS = [
	{ key: "name", header: "Connection" },
	{ key: "health", header: "Health" },
	{ key: "last_pull", header: "Last sync" },
	{ key: "schedule", header: "Schedule" },
	{ key: "failures", header: "Failures" },
	{ key: "actions", header: "Actions" },
];

const ACTIVITY_HEADERS = [
	{ key: "date", header: "Day" },
	{ key: "imported", header: "Imported" },
	{ key: "exported", header: "Exported" },
	{ key: "failed", header: "Failed" },
];

/** How many days of activity the page asks for. */
const ACTIVITY_DAYS = 7;

const TILE_LABEL: CSSProperties = {
	color: "var(--cds-text-secondary)",
	fontSize: "var(--cds-label-01-font-size)",
	lineHeight: "var(--cds-label-01-line-height)",
	marginBlockEnd: "var(--cds-spacing-03)",
};
const ROW_ACTIONS: CSSProperties = { display: "flex", justifyContent: "flex-end", alignItems: "center" };

/** A Connection's failures of its last sync, in the Sync log. */
function failuresHref(connection: string): string {
	return hrefFor("logs", undefined, { query: { connection, status: "Failure", since: "attempt" } });
}

interface CountTileProps {
	label: string;
	value: number;
	href: string;
}

/** One figure of the page's top row, opening the list it counts. */
function CountTile({ label, value, href }: CountTileProps) {
	return (
		<ClickableTile href={href}>
			<div style={TILE_LABEL}>{label}</div>
			<div className="es-tile-value">{value}</div>
		</ClickableTile>
	);
}

/** A Connection with the health derived from it, which the table sorts and shows by. */
interface HealthRecord {
	row: StatusRow;
	health: Health;
}

interface HealthCellProps {
	record: HealthRecord;
	column: string;
	now: string;
	actions: SyncActions;
}

function HealthCell({ record, column, now, actions }: HealthCellProps) {
	const { row, health } = record;
	switch (column) {
		case "name":
			return (
				<Link href={hrefFor("connections", row.name)} className="es-long-name">
					{row.name}
				</Link>
			);
		case "health":
			return <StatusIndicator kind={health.kind} label={health.label} reason={health.reason ?? undefined} />;
		case "last_pull":
			return <DateTime value={row.last_pull} now={now} />;
		case "schedule":
			return <>{describeSchedule(row.sync_frequency, row.cron_rule)}</>;
		case "failures":
			return row.failures_last_run > 0 ? (
				<Link href={failuresHref(row.name)}>{row.failures_last_run}</Link>
			) : (
				<>0</>
			);
		case "actions": {
			const busy = actions.busy.size > 0;
			return (
				<div style={ROW_ACTIONS}>
					<IconButton
						kind="ghost"
						size="sm"
						align="left"
						label={`Sync ${row.name} now`}
						disabled={!row.enabled || row.state !== "idle" || busy}
						onClick={() => void actions.syncNow(row.name)}
					>
						<Renew />
					</IconButton>
					<OverflowMenu
						aria-label={`Actions for ${row.name}`}
						iconDescription={`Actions for ${row.name}`}
						size="sm"
						flipped
					>
						<OverflowMenuItem itemText="View failures" href={failuresHref(row.name)} />
						<OverflowMenuItem
							itemText={row.enabled ? "Pause" : "Resume"}
							disabled={busy}
							onClick={() => void actions.setEnabled(row.name, !row.enabled)}
						/>
						<OverflowMenuItem itemText="Open" href={hrefFor("connections", row.name)} />
					</OverflowMenu>
				</div>
			);
		}
		default:
			return null;
	}
}

interface HealthTableProps {
	records: HealthRecord[];
	now: string;
	actions: SyncActions;
}

/** The Connections, the ones worth a look first. */
function HealthTable({ records, now, actions }: HealthTableProps) {
	const byId = new Map(records.map((record) => [record.row.name, record]));
	const rows = records.map(({ row }) => ({ id: row.name, name: row.name }));
	return (
		<DataTable rows={rows} headers={HEALTH_HEADERS} size="md">
			{({
				rows: tableRows,
				headers,
				getTableProps,
				getTableContainerProps,
				getHeaderProps,
				getRowProps,
				getCellProps,
			}) => (
				<TableContainer title="Connections" {...getTableContainerProps()}>
					<Table {...getTableProps()} aria-label="Connections">
						<TableHead>
							<TableRow>
								{headers.map((header) => {
									const { key, ...headerProps } = getHeaderProps({ header });
									return (
										<TableHeader key={key} {...headerProps} isSortable={false}>
											{header.key === "actions" ? (
												<span className="cds--visually-hidden">{header.header}</span>
											) : (
												header.header
											)}
										</TableHeader>
									);
								})}
							</TableRow>
						</TableHead>
						<TableBody>
							{tableRows.map((tableRow) => {
								const record = byId.get(tableRow.id);
								const { key, ...rowProps } = getRowProps({ row: tableRow });
								return (
									<TableRow key={key} {...rowProps}>
										{tableRow.cells.map((cell) => {
											const { key: cellKey, ...cellProps } = getCellProps({ cell });
											return (
												<TableCell key={cellKey} {...cellProps}>
													{record && (
														<HealthCell
															record={record}
															column={cell.info.header}
															now={now}
															actions={actions}
														/>
													)}
												</TableCell>
											);
										})}
									</TableRow>
								);
							})}
						</TableBody>
					</Table>
				</TableContainer>
			)}
		</DataTable>
	);
}

interface ActivityCountProps {
	value: number;
	/** The Sync log, narrowed to what the count is of. */
	href: string;
}

function ActivityCount({ value, href }: ActivityCountProps) {
	return value > 0 ? <Link href={href}>{value}</Link> : <>0</>;
}

/** The Sync log of one day, narrowed further by `query`. */
function dayHref(date: string, query: Record<string, string>): string {
	return hrefFor("logs", undefined, { query: { ...query, since: date } });
}

interface ActivityCellProps {
	day: ActivityDay;
	column: string;
	today: boolean;
}

function ActivityCell({ day, column, today }: ActivityCellProps) {
	switch (column) {
		case "date":
			return <>{today ? `${day.date} (today)` : day.date}</>;
		case "imported":
			return (
				<ActivityCount
					value={day.imported}
					href={dayHref(day.date, { status: "Success", direction: "Import", docs: "1" })}
				/>
			);
		case "exported":
			return (
				<ActivityCount
					value={day.exported}
					href={dayHref(day.date, { status: "Success", direction: "Export", docs: "1" })}
				/>
			);
		case "failed":
			return <ActivityCount value={day.failed} href={dayHref(day.date, { status: "Failure" })} />;
		default:
			return null;
	}
}

/** What every Connection synced on each of the last days, today first. */
function Activity() {
	const { data, error, isLoading } = useFrappeGetCall<FrappeResponse<ActivityDay[]>>(METHODS.activity, {
		days: ACTIVITY_DAYS,
	});
	useSessionRead(data, error);

	if (isLoading) {
		return (
			<DataTableSkeleton
				headers={ACTIVITY_HEADERS}
				columnCount={ACTIVITY_HEADERS.length}
				rowCount={ACTIVITY_DAYS}
				showToolbar={false}
				size="sm"
			/>
		);
	}
	if (error) {
		return (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The activity couldn't be loaded."
				subtitle={getErrorMessage(error, "Reload the page to try again.")}
			/>
		);
	}

	// the server answers oldest first, and its last day is today: here today is first
	const days = [...(data?.message ?? [])].sort((a, b) => b.date.localeCompare(a.date));
	const byId = new Map(days.map((day) => [day.date, day]));
	const rows = days.map((day) => ({ id: day.date, date: day.date }));
	return (
		<DataTable rows={rows} headers={ACTIVITY_HEADERS} size="sm">
			{({
				rows: tableRows,
				headers,
				getTableProps,
				getTableContainerProps,
				getHeaderProps,
				getRowProps,
				getCellProps,
			}) => (
				<TableContainer
					title={`Last ${ACTIVITY_DAYS} days`}
					description="Documents imported and exported, and log entries that failed."
					{...getTableContainerProps()}
				>
					<Table {...getTableProps()} aria-label={`Last ${ACTIVITY_DAYS} days`}>
						<TableHead>
							<TableRow>
								{headers.map((header) => {
									const { key, ...headerProps } = getHeaderProps({ header });
									return (
										<TableHeader key={key} {...headerProps} isSortable={false}>
											{header.header}
										</TableHeader>
									);
								})}
							</TableRow>
						</TableHead>
						<TableBody>
							{tableRows.map((tableRow, index) => {
								const day = byId.get(tableRow.id);
								const { key, ...rowProps } = getRowProps({ row: tableRow });
								return (
									<TableRow key={key} {...rowProps}>
										{tableRow.cells.map((cell) => {
											const { key: cellKey, ...cellProps } = getCellProps({ cell });
											return (
												<TableCell key={cellKey} {...cellProps}>
													{day && <ActivityCell day={day} column={cell.info.header} today={index === 0} />}
												</TableCell>
											);
										})}
									</TableRow>
								);
							})}
						</TableBody>
					</Table>
				</TableContainer>
			)}
		</DataTable>
	);
}

/** `#/overview`, and where the page opens: how the Connections are doing, what is
 * failing, and what was synced lately. */
export function Overview() {
	const { rows, now, error, isLoading, mutate } = useConnectionStatus();
	const actions = useSyncActions(mutate);

	let body;
	if (now === undefined) {
		// a poll that fails later keeps what is shown: only the first load has nothing to show
		body =
			isLoading || !error ? (
				<DataTableSkeleton
					headers={HEALTH_HEADERS}
					columnCount={HEALTH_HEADERS.length}
					rowCount={3}
					showToolbar={false}
				/>
			) : (
				<InlineNotification
					kind="error"
					lowContrast
					hideCloseButton
					title="The connections couldn't be loaded."
					subtitle={getErrorMessage(error, "Reload the page to try again.")}
				/>
			);
	} else if (rows.length === 0) {
		body = (
			<EmptyState
				icon={Connect}
				title="No connections yet."
				action={
					<Button
						kind="primary"
						href={hrefFor("connections", undefined, { query: { new: "1" } })}
						renderIcon={Add}
					>
						New connection
					</Button>
				}
			>
				A connection holds an API's address and credentials, and the shots that sync its DocTypes.
			</EmptyState>
		);
	} else {
		const records = rows
			.map((row) => ({ row, health: deriveHealth(row, now) }))
			.sort(
				(a, b) =>
					severityRank(a.health.kind) - severityRank(b.health.kind) || a.row.name.localeCompare(b.row.name),
			);
		const sum = (count: (row: StatusRow) => number) => rows.reduce((total, row) => total + count(row), 0);
		body = (
			<>
				<div className="es-tile-row">
					<CountTile
						label="Need attention"
						value={rows.filter((row) => needsAttention(row, now)).length}
						href={hrefFor("connections", undefined, { query: { health: "attention" } })}
					/>
					<CountTile
						label="Syncing now"
						value={rows.filter((row) => row.state !== "idle").length}
						href={hrefFor("connections")}
					/>
					<CountTile
						label="Failures, last 24 hours"
						value={sum((row) => row.failures_24h)}
						href={hrefFor("logs", undefined, { query: { status: "Failure", since: "24h" } })}
					/>
					<CountTile
						label="Synced, last 24 hours"
						value={sum((row) => row.successes_24h)}
						href={hrefFor("logs", undefined, { query: { status: "Success", since: "24h", docs: "1" } })}
					/>
				</div>
				<HealthTable records={records} now={now} actions={actions} />
				<FailureGroups />
				<Activity />
			</>
		);
	}

	return (
		<>
			<PageHeader breadcrumb={[]} title="Overview" />
			<Stack gap={7}>{body}</Stack>
		</>
	);
}
