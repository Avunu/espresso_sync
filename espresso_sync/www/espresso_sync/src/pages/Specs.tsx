// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useRef, useState } from "react";
import {
	Breadcrumb,
	BreadcrumbItem,
	Button,
	DataTable,
	DataTableSkeleton,
	InlineNotification,
	Link,
	Stack,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableHeader,
	TableRow,
	TableToolbar,
	TableToolbarContent,
} from "@carbon/react";
import { Upload } from "@carbon/react/icons";
import { useFrappeGetDocList } from "frappe-react-sdk";
import { useToasts } from "../portal/Toasts";
import { getErrorMessage } from "../portal/useBackendCall";
import { hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { ImportSpec, type SavedSpec } from "./ImportSpec";

export const SPEC = "Espresso Sync API Spec";

interface SpecRow {
	name: string;
	title: string;
	connection: string | null;
	original_version: string | null;
	/** JSON text: the operations' summaries. */
	operations: string | null;
}

const HEADERS = [
	{ key: "title", header: "Title" },
	{ key: "connection", header: "Connection" },
	{ key: "original_version", header: "Version" },
	{ key: "operations", header: "Operations" },
];

const DESCRIPTION =
	"An API's OpenAPI description, stored as OpenAPI 3.1: the operations a transform maps to and from a DocType.";

function countOperations(operations: string | null): number {
	try {
		const list: unknown = JSON.parse(operations || "[]");
		return Array.isArray(list) ? list.length : 0;
	} catch {
		return 0;
	}
}

function SpecCell({ row, column }: { row: SpecRow; column: string }) {
	switch (column) {
		case "title":
			return <Link href={hrefFor("specs", row.name)}>{row.title}</Link>;
		case "connection":
			return <>{row.connection || "—"}</>;
		case "original_version":
			return <>{row.original_version || "—"}</>;
		case "operations":
			return <>{countOperations(row.operations)}</>;
		default:
			return null;
	}
}

/** `#/specs`: the API Specs, and importing a new one. */
export function Specs() {
	const { data, error, isLoading } = useFrappeGetDocList<SpecRow>(SPEC, {
		fields: ["name", "title", "connection", "original_version", "operations"],
		orderBy: { field: "modified", order: "desc" },
		limit: 500,
	});
	useSessionRead(data, error);
	const [importing, setImporting] = useState(false);
	// a new form each time it opens; mounted while closed, so the modal hands focus back to the button
	const [importKey, setImportKey] = useState(0);
	const launcher = useRef<HTMLButtonElement>(null);
	const showToast = useToasts();

	function imported(saved: SavedSpec) {
		setImporting(false);
		showToast({ kind: "success", title: `${saved.name} imported: ${saved.operations.length} operations.` });
		window.location.hash = hrefFor("specs", saved.name);
	}

	let table;
	if (isLoading) {
		table = <DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length} rowCount={3} />;
	} else if (error) {
		table = (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The API specs couldn't be loaded."
				subtitle={getErrorMessage(error, "Reload the page to try again.")}
			/>
		);
	} else {
		const byId = new Map((data ?? []).map((row) => [row.name, row]));
		const rows = (data ?? []).map((row) => ({
			id: row.name,
			title: row.title,
			connection: row.connection,
			original_version: row.original_version,
			operations: countOperations(row.operations),
		}));
		table = (
			<DataTable rows={rows} headers={HEADERS}>
				{({ rows: tableRows, headers, getTableProps, getTableContainerProps }) => (
					<TableContainer title="API specs" description={DESCRIPTION} {...getTableContainerProps()}>
						<TableToolbar aria-label="API specs">
							<TableToolbarContent>
								<Button
									ref={launcher}
									kind="primary"
									renderIcon={Upload}
									onClick={() => {
										setImportKey((key) => key + 1);
										setImporting(true);
									}}
								>
									Import
								</Button>
							</TableToolbarContent>
						</TableToolbar>
						<Table {...getTableProps()} aria-label="API specs">
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
													{record && <SpecCell row={record} column={cell.info.header} />}
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

	return (
		<Stack gap={6}>
			<Breadcrumb noTrailingSlash>
				<BreadcrumbItem href={hrefFor("connections")}>Connections</BreadcrumbItem>
				<BreadcrumbItem isCurrentPage>API specs</BreadcrumbItem>
			</Breadcrumb>
			{table}
			<ImportSpec
				key={importKey}
				open={importing}
				launcherButtonRef={launcher}
				onClose={() => setImporting(false)}
				onImported={imported}
			/>
		</Stack>
	);
}
