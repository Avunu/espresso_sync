// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import {
	Button,
	DataTable,
	DataTableSkeleton,
	InlineNotification,
	Link,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableHeader,
	TableRow,
	TableToolbar,
	TableToolbarContent,
	Tag,
} from "@carbon/react";
import { Add, Launch } from "@carbon/react/icons";
import { useFrappeGetDocList } from "frappe-react-sdk";
import { getErrorMessage } from "../portal/useBackendCall";
import { deskFormUrl, hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";

const CONNECTION = "Espresso Sync Connection";

/** The list's columns: what identifies a Connection and how it runs, never its credentials. */
interface ConnectionRow {
	name: string;
	server_url: string | null;
	enabled: 0 | 1;
	sync_frequency: string | null;
	last_pull: string | null;
}

const HEADERS = [
	{ key: "name", header: "Connection" },
	{ key: "server_url", header: "Server URL" },
	{ key: "enabled", header: "Status" },
	{ key: "sync_frequency", header: "Runs" },
	{ key: "last_pull", header: "Last sync" },
];

const DESCRIPTION =
	"Each Connection holds an API's address and credentials, which are edited in the desk, and the shots that sync its DocTypes through transforms.";

/** Frappe's "YYYY-MM-DD HH:MM:SS.ffffff" (system time zone), to the minute. */
function formatDatetime(value: string | null): string {
	return value ? value.slice(0, 16) : "Never";
}

function ConnectionCell({ row, column }: { row: ConnectionRow; column: string }) {
	switch (column) {
		case "name":
			return (
				<Link href={deskFormUrl(CONNECTION, row.name)} renderIcon={Launch}>
					{row.name}
				</Link>
			);
		case "server_url":
			return <code>{row.server_url || "—"}</code>;
		case "enabled":
			return row.enabled ? (
				<Tag type="green" size="sm">
					Enabled
				</Tag>
			) : (
				<Tag type="gray" size="sm">
					Disabled
				</Tag>
			);
		case "sync_frequency":
			return <>{row.sync_frequency || "Manual"}</>;
		case "last_pull":
			return <>{formatDatetime(row.last_pull)}</>;
		default:
			return null;
	}
}

/** `#/connections`, and where the page opens: the Connections, linking to the desk for each. */
export function Overview() {
	const { data, error, isLoading } = useFrappeGetDocList<ConnectionRow>(CONNECTION, {
		fields: ["name", "server_url", "enabled", "sync_frequency", "last_pull"],
		orderBy: { field: "modified", order: "desc" },
		limit: 500,
	});
	useSessionRead(data, error);

	if (isLoading) {
		return <DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length} rowCount={3} />;
	}
	if (error) {
		return (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The Connections couldn't be loaded."
				subtitle={getErrorMessage(error, "Reload the page to try again.")}
			/>
		);
	}

	const rows = (data ?? []).map((row) => ({
		id: row.name,
		name: row.name,
		server_url: row.server_url,
		enabled: row.enabled,
		sync_frequency: row.sync_frequency,
		last_pull: row.last_pull,
	}));
	const byId = new Map(rows.map((row) => [row.id, row]));

	return (
		<DataTable rows={rows} headers={HEADERS}>
			{({ rows: tableRows, headers, getTableProps, getTableContainerProps }) => (
				<TableContainer title="Connections" description={DESCRIPTION} {...getTableContainerProps()}>
					<TableToolbar aria-label="Connections">
						<TableToolbarContent>
							<Button kind="ghost" href={hrefFor("specs")}>
								API specs
							</Button>
							<Button kind="primary" href={deskFormUrl(CONNECTION)} renderIcon={Add}>
								New connection
							</Button>
						</TableToolbarContent>
					</TableToolbar>
					<Table {...getTableProps()} aria-label="Connections">
						<TableHead>
							<TableRow>
								{headers.map((header) => (
									<TableHeader key={header.key}>{header.header}</TableHeader>
								))}
							</TableRow>
						</TableHead>
						<TableBody>
							{tableRows.map((tableRow) => {
								const record = byId.get(tableRow.id);
								return (
									<TableRow key={tableRow.id}>
										{tableRow.cells.map((cell) => (
											<TableCell key={cell.id}>
												{record && <ConnectionCell row={record} column={cell.info.header} />}
											</TableCell>
										))}
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
