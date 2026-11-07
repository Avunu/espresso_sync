// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect } from "react";
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
	Tile,
} from "@carbon/react";
import { Add, Launch } from "@carbon/react/icons";
import { useFrappeGetDocList } from "frappe-react-sdk";
import { deskFormUrl } from "../../../../public/js/editor/routes.ts";
import { useSession } from "../portal/session";
import { getErrorMessage, readFailure } from "../portal/useBackendCall";

const CONNECTION = "Espresso Sync Connection";

/** The list's columns: what identifies a Connection and how it runs, never its credentials. */
interface ConnectionRow {
	name: string;
	api_domain: string | null;
	pull_shot: 0 | 1;
	sync_frequency: string | null;
	last_pull: string | null;
}

const HEADERS = [
	{ key: "name", header: "Connection" },
	{ key: "api_domain", header: "API host" },
	{ key: "pull_shot", header: "Status" },
	{ key: "sync_frequency", header: "Runs" },
	{ key: "last_pull", header: "Last sync" },
];

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
		case "api_domain":
			return <code>{row.api_domain || "—"}</code>;
		case "pull_shot":
			return row.pull_shot ? (
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

function Connections() {
	const { data, error, isLoading } = useFrappeGetDocList<ConnectionRow>(CONNECTION, {
		fields: ["name", "api_domain", "pull_shot", "sync_frequency", "last_pull"],
		orderBy: { field: "modified", order: "desc" },
		limit: 500,
	});
	const { recordActivity, reportForbidden } = useSession();

	useEffect(() => {
		if (data) recordActivity();
	}, [data, recordActivity]);

	useEffect(() => {
		// A 403 here means the session ended: the page itself is only served to System Managers.
		if (error && readFailure(error).httpStatus === 403) reportForbidden();
	}, [error, reportForbidden]);

	const description =
		"Each Connection holds an API's address and credentials. Credentials are edited in the desk, never here.";

	if (isLoading) {
		return (
			<DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length} rowCount={3} showHeader={false} />
		);
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
		api_domain: row.api_domain,
		pull_shot: row.pull_shot,
		sync_frequency: row.sync_frequency,
		last_pull: row.last_pull,
	}));
	const byId = new Map(rows.map((row) => [row.id, row]));

	return (
		<DataTable rows={rows} headers={HEADERS} size="md">
			{({ rows: tableRows, headers, getTableProps, getTableContainerProps }) => (
				<TableContainer title="Connections" description={description} {...getTableContainerProps()}>
					<TableToolbar aria-label="Connections">
						<TableToolbarContent>
							<Button kind="primary" size="md" href={deskFormUrl(CONNECTION)} renderIcon={Add}>
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
					{rows.length === 0 && (
						<p className="es-empty">No Connections yet. Add one in the desk to get started.</p>
					)}
				</TableContainer>
			)}
		</DataTable>
	);
}

/** `#/`: the Connections, and what will be built on them. */
export function Overview() {
	return (
		<div className="es-page">
			<header className="es-heading">
				<h1>Espresso Sync</h1>
				<p>Keep your DocTypes in step with other systems&apos; REST APIs.</p>
			</header>
			<Connections />
			<section className="es-coming" aria-labelledby="es-coming-title">
				<h2 id="es-coming-title">API specs and transforms</h2>
				<div className="es-coming__tiles">
					<Tile>
						<h3>API specs</h3>
						<p>Import an API&apos;s OpenAPI document to see the operations a Connection can call.</p>
					</Tile>
					<Tile>
						<h3>Transforms</h3>
						<p>
							Map an operation&apos;s data to a DocType and back, one field at a time, checked against both
							schemas and previewed on real samples.
						</p>
					</Tile>
				</div>
				<p className="es-muted">Both are on their way in a coming version of Espresso Sync.</p>
			</section>
		</div>
	);
}
