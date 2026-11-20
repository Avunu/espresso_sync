// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useMemo } from "react";
import {
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
	Tag,
} from "@carbon/react";
import { useFrappeGetDocList } from "frappe-react-sdk";
import { PageHeader } from "../components/PageHeader";
import { CONNECTION, type StatusProblem } from "../data/api";
import { useConnectionStatus } from "../data/useConnectionStatus";
import { getErrorMessage } from "../portal/useBackendCall";
import { hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { TRANSFORM } from "./NewTransform";
import { SeverityIcon } from "./SeverityIcon";

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
	{ key: "used_by", header: "Used by" },
];

/** The fields of a shot that name a transform. */
const SHOT_TRANSFORMS = [
	"import_transform",
	"export_transform",
	"update_transform",
	"follow_up_transform",
] as const;

/** What the list of Connections is asked for: a row to each shot, with its transforms. */
type ShotQuery = Record<"name" | `shots.${(typeof SHOT_TRANSFORMS)[number]}`, string | null>;

/** A row of that list as answered: the shot's fields come without the `shots.`. */
type ShotRow = { name: string } & Partial<Record<(typeof SHOT_TRANSFORMS)[number], string | null>>;

/** A Connection with a shot that runs a transform, and what is wrong with that shot. */
interface Use {
	connection: string;
	problems: StatusProblem[];
}

/** The Connections whose shots run each transform, by the transform's name. */
function usesOf(shots: ShotRow[], problems: Map<string, StatusProblem[]>): Map<string, Use[]> {
	const uses = new Map<string, Use[]>();
	for (const shot of shots) {
		for (const field of SHOT_TRANSFORMS) {
			const transform = shot[field];
			if (!transform) continue;
			const list = uses.get(transform) ?? [];
			if (list.some((use) => use.connection === shot.name)) continue;
			list.push({
				connection: shot.name,
				problems: (problems.get(shot.name) ?? []).filter((problem) => problem.transform === transform),
			});
			uses.set(transform, list);
		}
	}
	return uses;
}

function UsedBy({ uses }: { uses: Use[] | undefined }) {
	if (!uses?.length) return <>—</>;
	return (
		<ul
			style={{
				display: "flex",
				flexDirection: "column",
				gap: "var(--cds-spacing-02)",
				// a long name wraps in its column
				overflowWrap: "anywhere",
			}}
		>
			{uses.map(({ connection, problems }) => (
				<li key={connection}>
					<Link href={hrefFor("connections", connection, { tab: "shots" })}>{connection}</Link>
					{problems.map((problem) => (
						<div
							// no two are alike: the server lists a problem of a shot's transform once
							key={`${problem.code} ${problem.doctype ?? ""} ${problem.message}`}
							style={{ display: "flex", gap: "var(--cds-spacing-02)", alignItems: "center" }}
						>
							<SeverityIcon severity="warning" />
							<span>{problem.message}</span>
						</div>
					))}
				</li>
			))}
		</ul>
	);
}

const DESCRIPTION =
	"Each transform maps an API operation's objects to a DocType's documents, or documents to an operation's request body. Start one from an operation of an API spec.";

function TransformCell({
	row,
	column,
	uses,
}: {
	row: TransformRow;
	column: string;
	uses: Use[] | undefined;
}) {
	switch (column) {
		case "name":
			return (
				<Link href={hrefFor("transforms", row.name)} className="es-long-name">
					{row.name}
				</Link>
			);
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
		case "used_by":
			return <UsedBy uses={uses} />;
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
	// the shots of every Connection, a row to each: which transforms are in use, and where.
	// The column is empty until both this and the Connections' status have answered.
	const shots = useFrappeGetDocList<ShotQuery>(CONNECTION, {
		fields: ["name", ...SHOT_TRANSFORMS.map((field) => `shots.${field}` as const)],
		limit: 5000,
	});
	useSessionRead(shots.data, shots.error);
	const status = useConnectionStatus();
	const uses = useMemo(
		() =>
			usesOf(
				(shots.data ?? []) as unknown as ShotRow[],
				new Map(status.rows.map((row) => [row.name, row.problems])),
			),
		[shots.data, status.rows],
	);

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
			used_by: (uses.get(row.name) ?? []).map((use) => use.connection).join(", "),
		}));
		table = (
			<DataTable rows={rows} headers={HEADERS}>
				{({ rows: tableRows, headers, getTableProps, getTableContainerProps }) => (
					<TableContainer {...getTableContainerProps()}>
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
											No transforms yet: start one from an operation of an{" "}
											<Link inline href={hrefFor("specs")}>
												API spec
											</Link>
											.
										</TableCell>
									</TableRow>
								)}
								{tableRows.map((tableRow) => {
									const record = byId.get(tableRow.id);
									return (
										<TableRow key={tableRow.id}>
											{tableRow.cells.map((cell) => (
												<TableCell key={cell.id}>
													{record && (
														<TransformCell
															row={record}
															column={cell.info.header}
															uses={uses.get(record.name)}
														/>
													)}
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
		<>
			<PageHeader breadcrumb={[]} title="Transforms" subtitle={DESCRIPTION} />
			{table}
		</>
	);
}
