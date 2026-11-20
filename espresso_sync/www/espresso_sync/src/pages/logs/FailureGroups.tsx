// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import {
	DataTable,
	InlineNotification,
	Link,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableHeader,
	TableRow,
} from "@carbon/react";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { plural } from "../../../../../public/js/portal/datetime.ts";
import { ERROR_HINTS } from "../../../../../public/js/portal/logs.ts";
import { DateTime } from "../../components/DateTime";
import { type FailureGroup, type FailureGroups as FailureGroupsAnswer, METHODS } from "../../data/api";
import { useConnectionStatus } from "../../data/useConnectionStatus";
import { getErrorMessage } from "../../portal/useBackendCall";
import { hrefFor } from "../../route";
import { useSessionRead } from "../../useSessionRead";

export interface FailureGroupsProps {
	/** Only this Connection's failures; every Connection's without it. */
	connection?: string | undefined;
}

/** The failures are asked for again this often: a sync that ran since changes them. */
const REFRESH_MS = 30_000;

/** The Sync log narrowed to the entries of a group. */
function entriesHref(group: FailureGroup): string {
	return hrefFor("logs", undefined, {
		query: {
			connection: group.connection,
			status: "Failure",
			since: "attempt",
			direction: group.direction ?? undefined,
			doctype: group.doctype ?? undefined,
			transform: group.transform ?? undefined,
			code: group.code,
		},
	});
}

interface GroupCellProps {
	group: FailureGroup;
	column: string;
	now: string | undefined;
}

function GroupCell({ group, column, now }: GroupCellProps) {
	switch (column) {
		case "error": {
			const hint = ERROR_HINTS[group.code];
			return (
				<span style={{ display: "inline-block", minInlineSize: "16rem", overflowWrap: "break-word" }}>
					<code>{group.code}</code> {group.message}
					{hint && <span style={{ display: "block", color: "var(--cds-text-secondary)" }}>{hint}</span>}
				</span>
			);
		}
		case "connection":
			return (
				<Link href={hrefFor("connections", group.connection)} className="es-long-name">
					{group.connection}
				</Link>
			);
		case "doctype":
			return <>{group.doctype || "—"}</>;
		case "transform":
			if (!group.transform) return <>—</>;
			return (
				<Link href={hrefFor("transforms", group.transform)} className="es-long-name">
					{group.transform}
				</Link>
			);
		case "entries":
			return (
				<Link href={entriesHref(group)} style={{ whiteSpace: "nowrap" }}>
					{plural(group.count, "entry", "entries")}
				</Link>
			);
		case "latest":
			return (
				<Link href={hrefFor("logs", group.latest_log)}>
					<DateTime value={group.latest} now={now} />
				</Link>
			);
		default:
			return null;
	}
}

/** "What is failing": the failures of the last sync, grouped by error. It renders
 * nothing when there are none. */
export function FailureGroups({ connection }: FailureGroupsProps) {
	const { data, error } = useFrappeGetCall<FrappeResponse<FailureGroupsAnswer>>(
		METHODS.failureGroups,
		connection ? { connection } : undefined,
		undefined,
		{ refreshInterval: REFRESH_MS, refreshWhenHidden: false },
	);
	useSessionRead(data, error);
	// only for the server's time, which "5 minutes ago" is counted from
	const { now } = useConnectionStatus(connection);

	const answer = data?.message;
	if (!answer) {
		// nothing while it loads: the page it is part of has its own skeleton
		if (!error) return null;
		return (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="What is failing couldn't be loaded."
				subtitle={getErrorMessage(error, "Reload the page to try again.")}
			/>
		);
	}
	if (answer.groups.length === 0) return null;

	const headers = [
		{ key: "error", header: "Error" },
		// one Connection's failures need no column to say whose they are
		...(connection ? [] : [{ key: "connection", header: "Connection" }]),
		{ key: "doctype", header: "DocType" },
		{ key: "transform", header: "Transform" },
		{ key: "entries", header: "Entries" },
		{ key: "latest", header: "Latest" },
	];
	const rows = answer.groups.map((_group, index) => ({ id: String(index) }));
	const description = answer.truncated
		? "The failures of the last sync, by what went wrong. There are more than were read: only the newest are counted."
		: "The failures of the last sync, by what went wrong. The next sync tries each again.";

	return (
		<DataTable rows={rows} headers={headers} size="md">
			{({
				rows: tableRows,
				headers: tableHeaders,
				getTableProps,
				getTableContainerProps,
				getHeaderProps,
				getRowProps,
				getCellProps,
			}) => (
				<TableContainer title="What is failing" description={description} {...getTableContainerProps()}>
					<Table {...getTableProps()} aria-label="What is failing">
						<TableHead>
							<TableRow>
								{tableHeaders.map((header) => {
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
							{tableRows.map((tableRow) => {
								const group = answer.groups[Number(tableRow.id)];
								if (!group) return null;
								const { key, ...rowProps } = getRowProps({ row: tableRow });
								return (
									<TableRow key={key} {...rowProps}>
										{tableRow.cells.map((cell) => {
											const { key: cellKey, ...cellProps } = getCellProps({ cell });
											return (
												<TableCell key={cellKey} {...cellProps}>
													<GroupCell group={group} column={cell.info.header} now={now} />
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
