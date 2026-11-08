// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

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
	Tag,
} from "@carbon/react";
import { useFrappeGetDocList } from "frappe-react-sdk";
import { getErrorMessage } from "../portal/useBackendCall";
import { hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { TRANSFORM } from "./NewTransform";

interface TransformRow {
	name: string;
	direction: string;
	status: string;
	document_type: string;
	method: string;
	path: string;
}

const HEADERS = [
	{ key: "name", header: "Transform" },
	{ key: "direction", header: "Direction" },
	{ key: "document_type", header: "DocType" },
	{ key: "operation", header: "Operation" },
	{ key: "status", header: "Status" },
];

const DESCRIPTION =
	"Each transform maps an API operation's objects to a DocType's documents, or documents to an operation's request body. Start one from an operation of an API spec.";

function TransformCell({ row, column }: { row: TransformRow; column: string }) {
	switch (column) {
		case "name":
			return <Link href={hrefFor("transforms", row.name)}>{row.name}</Link>;
		case "direction":
			return <>{row.direction}</>;
		case "document_type":
			return <>{row.document_type}</>;
		case "operation":
			return <code>{`${row.method} ${row.path}`}</code>;
		case "status":
			return (
				<Tag size="sm" type={row.status === "Active" ? "green" : "gray"}>
					{row.status}
				</Tag>
			);
		default:
			return null;
	}
}

/** `#/transforms`: the transforms, each opening in the editor. */
export function Transforms() {
	const { data, error, isLoading } = useFrappeGetDocList<TransformRow>(TRANSFORM, {
		fields: ["name", "direction", "status", "document_type", "method", "path"],
		orderBy: { field: "modified", order: "desc" },
		limit: 500,
	});
	useSessionRead(data, error);

	let table;
	if (isLoading) {
		table = <DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length} rowCount={3} />;
	} else if (error) {
		table = (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The transforms couldn't be loaded."
				subtitle={getErrorMessage(error, "Reload the page to try again.")}
			/>
		);
	} else {
		const byId = new Map((data ?? []).map((row) => [row.name, row]));
		const rows = (data ?? []).map((row) => ({
			id: row.name,
			name: row.name,
			direction: row.direction,
			document_type: row.document_type,
			operation: `${row.method} ${row.path}`,
			status: row.status,
		}));
		table = (
			<DataTable rows={rows} headers={HEADERS}>
				{({ rows: tableRows, headers, getTableProps, getTableContainerProps }) => (
					<TableContainer title="Transforms" description={DESCRIPTION} {...getTableContainerProps()}>
						<TableToolbar aria-label="Transforms">
							<TableToolbarContent>
								<Button kind="primary" href={hrefFor("specs")}>
									API specs
								</Button>
							</TableToolbarContent>
						</TableToolbar>
						<Table {...getTableProps()} aria-label="Transforms">
							<TableHead>
								<TableRow>
									{headers.map((header) => (
										<TableHeader key={header.key}>{header.header}</TableHeader>
									))}
								</TableRow>
							</TableHead>
							<TableBody>
								{tableRows.length === 0 && (
									<TableRow>
										<TableCell colSpan={headers.length}>
											No transforms yet: start one from an operation of an API spec.
										</TableCell>
									</TableRow>
								)}
								{tableRows.map((tableRow) => {
									const record = byId.get(tableRow.id);
									return (
										<TableRow key={tableRow.id}>
											{tableRow.cells.map((cell) => (
												<TableCell key={cell.id}>
													{record && <TransformCell row={record} column={cell.info.header} />}
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
				<BreadcrumbItem isCurrentPage>Transforms</BreadcrumbItem>
			</Breadcrumb>
			{table}
		</Stack>
	);
}
