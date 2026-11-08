// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import {
	Button,
	DataTable,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableHeader,
	TableRow,
} from "@carbon/react";
import { type Finding, itemRanges } from "../../../../public/js/editor/mapping.ts";
import { SeverityIcon } from "./SeverityIcon";

const HEADERS = [
	{ key: "severity", header: "Severity" },
	{ key: "rule", header: "Field" },
	{ key: "message", header: "Finding" },
	{ key: "items", header: "Sample items" },
	{ key: "origin", header: "Found by" },
];

interface DiagnosticsTableProps {
	diagnostics: Finding[];
	/** Whether the server's findings are of the transform as it is: false while it has unsaved changes. */
	current: boolean;
	onShow: (diagnostic: Finding) => void;
}

/** What the browser and the server's last check found, a row each; a row's field opens its rule. */
export function DiagnosticsTable({ diagnostics, current, onShow }: DiagnosticsTableProps) {
	const rows = diagnostics.map((found, index) => ({
		id: String(index),
		severity: found.severity,
		rule: found.rule,
		message: found.message,
		items: itemRanges(found.items),
		origin: found.origin,
	}));
	const description = current
		? "The browser checks as you edit; the server checks on save, and with Validate."
		: "The browser checks as you edit. Save to check the changes on the server too.";
	return (
		<DataTable rows={rows} headers={HEADERS}>
			{({ rows: tableRows, headers, getTableProps, getTableContainerProps }) => (
				<TableContainer title="Diagnostics" description={description} {...getTableContainerProps()}>
					<Table {...getTableProps()} aria-label="Diagnostics" size="sm">
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
									<TableCell colSpan={headers.length}>Nothing found.</TableCell>
								</TableRow>
							)}
							{tableRows.map((tableRow) => {
								const found = diagnostics[Number(tableRow.id)];
								if (!found) return null;
								return (
									<TableRow key={tableRow.id}>
										<TableCell>
											<SeverityIcon severity={found.severity} /> {found.severity}
										</TableCell>
										<TableCell>
											<Button kind="ghost" size="sm" onClick={() => onShow(found)}>
												<code>{found.rule || "(the whole object)"}</code>
											</Button>
										</TableCell>
										<TableCell>
											{found.message} <code>{found.code}</code>
										</TableCell>
										<TableCell>{itemRanges(found.items)}</TableCell>
										<TableCell>{found.origin === "server" ? "Server" : "Browser"}</TableCell>
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
