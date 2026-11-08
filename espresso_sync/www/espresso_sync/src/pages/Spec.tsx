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
	Pagination,
	SkeletonText,
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
	TableToolbarSearch,
	Tag,
} from "@carbon/react";
import { Add, Launch, Renew } from "@carbon/react/icons";
import { useFrappeGetCall, useFrappeGetDocList } from "frappe-react-sdk";
import { useToasts } from "../portal/Toasts";
import type { FrappeEnvelope } from "../portal/types";
import { getErrorMessage } from "../portal/useBackendCall";
import { deskFormUrl, hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { Details } from "./Details";
import { ImportSpec, type SavedSpec } from "./ImportSpec";
import { NewTransform, TRANSFORM_METHODS, type Operation } from "./NewTransform";
import { SPEC } from "./Specs";

interface SpecDoc {
	name: string;
	title: string;
	connection: string | null;
	source_url: string | null;
	source_format: string;
	original_version: string | null;
	spec_hash: string | null;
	modified: string;
}

const HEADERS = [
	{ key: "method", header: "Method" },
	{ key: "path", header: "Path" },
	{ key: "summary", header: "Summary" },
	{ key: "tags", header: "Tags" },
	{ key: "transform", header: "Transform" },
];

const PAGE_SIZES = [25, 50, 100];

const METHOD_TAGS: Record<string, "blue" | "green" | "purple" | "red" | "gray"> = {
	GET: "blue",
	POST: "green",
	PUT: "purple",
	PATCH: "purple",
	DELETE: "red",
};

/** Whether an operation has every word of the search in its method, path, id, summary or tags. */
function matches(operation: Operation, words: string[]): boolean {
	const text = [
		operation.method,
		operation.path,
		operation.operation_id,
		operation.summary,
		...operation.tags,
	]
		.join(" ")
		.toLowerCase();
	return words.every((word) => text.includes(word));
}

/** `#/specs/<name>`: an API Spec's operations, re-importing it, and starting a transform from an operation. */
export function Spec({ name }: { name: string }) {
	const specs = useFrappeGetDocList<SpecDoc>(SPEC, {
		fields: [
			"name",
			"title",
			"connection",
			"source_url",
			"source_format",
			"original_version",
			"spec_hash",
			"modified",
		],
		filters: [["name", "=", name]],
		limit: 1,
	});
	const operations = useFrappeGetCall<FrappeEnvelope<Operation[]>>(
		"espresso_sync.api.schema.list_operations",
		{
			spec: name,
		},
	);
	useSessionRead(specs.data, specs.error);
	useSessionRead(operations.data, operations.error);
	const showToast = useToasts();

	const [search, setSearch] = useState("");
	const [page, setPage] = useState(1);
	const [pageSize, setPageSize] = useState(PAGE_SIZES[0] ?? 25);
	const [reimporting, setReimporting] = useState(false);
	const [reimportKey, setReimportKey] = useState(0);
	const reimportLauncher = useRef<HTMLButtonElement>(null);
	const [operation, setOperation] = useState<Operation | undefined>();
	const [creating, setCreating] = useState(false);
	const [transformKey, setTransformKey] = useState(0);
	const transformLauncher = useRef<HTMLButtonElement>(null);

	const spec = specs.data?.[0];
	const breadcrumb = (
		<Breadcrumb noTrailingSlash>
			<BreadcrumbItem href={hrefFor("connections")}>Connections</BreadcrumbItem>
			<BreadcrumbItem href={hrefFor("specs")}>API specs</BreadcrumbItem>
			<BreadcrumbItem isCurrentPage>{spec?.title ?? name}</BreadcrumbItem>
		</Breadcrumb>
	);

	if (specs.isLoading) {
		return (
			<Stack gap={6}>
				{breadcrumb}
				<SkeletonText heading />
				<DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length} rowCount={5} />
			</Stack>
		);
	}
	if (specs.error || !spec) {
		return (
			<Stack gap={6}>
				{breadcrumb}
				<InlineNotification
					kind="error"
					lowContrast
					hideCloseButton
					title={specs.error ? "The API spec couldn't be loaded." : `There is no API spec ${name}.`}
					subtitle={specs.error ? getErrorMessage(specs.error, "Reload the page to try again.") : ""}
				/>
			</Stack>
		);
	}

	function reimported(saved: SavedSpec) {
		setReimporting(false);
		const count = saved.operations.length;
		showToast(
			saved.changed
				? {
						kind: "success",
						title: `The spec changed: it has ${count} ${count === 1 ? "operation" : "operations"}.`,
					}
				: { kind: "info", title: "The spec is unchanged." },
		);
		void specs.mutate();
		void operations.mutate();
	}

	const words = search.toLowerCase().split(/\s+/).filter(Boolean);
	const found = (operations.data?.message ?? []).filter((op) => matches(op, words));
	const shown = found.slice((page - 1) * pageSize, page * pageSize);
	const byId = new Map(shown.map((op) => [`${op.method} ${op.path}`, op]));
	const rows = shown.map((op) => ({
		id: `${op.method} ${op.path}`,
		method: op.method,
		path: op.path,
		summary: op.summary,
		tags: op.tags.join(", "),
		transform: "",
	}));

	function cell(op: Operation, column: string) {
		switch (column) {
			case "method":
				return (
					<Tag size="sm" type={METHOD_TAGS[op.method] ?? "gray"}>
						{op.method}
					</Tag>
				);
			case "path":
				return <code>{op.path}</code>;
			case "summary":
				return (
					<>
						{op.summary || op.operation_id}{" "}
						{op.deprecated && (
							<Tag size="sm" type="warm-gray">
								Deprecated
							</Tag>
						)}
					</>
				);
			case "tags":
				return op.tags.map((tag) => (
					<Tag key={tag} size="sm" type="cool-gray">
						{tag}
					</Tag>
				));
			case "transform":
				return (
					TRANSFORM_METHODS.includes(op.method) && (
						<Button
							kind="ghost"
							size="sm"
							renderIcon={Add}
							aria-label={`New transform for ${op.method} ${op.path}`}
							onClick={(event) => {
								transformLauncher.current = event.currentTarget;
								setTransformKey((key) => key + 1);
								setOperation(op);
								setCreating(true);
							}}
						>
							New transform
						</Button>
					)
				);
			default:
				return null;
		}
	}

	let table;
	if (operations.isLoading) {
		table = <DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length} rowCount={5} />;
	} else if (operations.error) {
		table = (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The operations couldn't be read."
				subtitle={getErrorMessage(operations.error, "Reload the page to try again.")}
			/>
		);
	} else {
		table = (
			<DataTable rows={rows} headers={HEADERS}>
				{({ rows: tableRows, headers, getTableProps, getTableContainerProps }) => (
					<TableContainer
						title="Operations"
						description="Start a transform from an operation: an import maps its response to documents, an export maps documents to its request body."
						{...getTableContainerProps()}
					>
						<TableToolbar aria-label="Operations">
							<TableToolbarContent>
								<TableToolbarSearch
									persistent
									labelText="Search the operations"
									placeholder="Search by method, path, summary or tag"
									value={search}
									onChange={(_event, value) => {
										setSearch(value ?? "");
										setPage(1);
									}}
								/>
							</TableToolbarContent>
						</TableToolbar>
						<Table {...getTableProps()} aria-label="Operations">
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
											{search.trim()
												? `No operations match "${search.trim()}".`
												: "This spec has no operations."}
										</TableCell>
									</TableRow>
								)}
								{tableRows.map((tableRow) => {
									const record = byId.get(tableRow.id);
									return (
										<TableRow key={tableRow.id}>
											{tableRow.cells.map((tableCell) => (
												<TableCell key={tableCell.id}>
													{record && cell(record, tableCell.info.header)}
												</TableCell>
											))}
										</TableRow>
									);
								})}
							</TableBody>
						</Table>
						<Pagination
							page={page}
							pageSize={pageSize}
							pageSizes={PAGE_SIZES}
							totalItems={found.length}
							onChange={(next) => {
								setPage(next.page);
								setPageSize(next.pageSize);
							}}
						/>
					</TableContainer>
				)}
			</DataTable>
		);
	}

	return (
		<Stack gap={6}>
			{breadcrumb}
			<h1>{spec.title}</h1>
			<Details
				label="About the spec"
				fields={[
					["Connection", spec.connection || "None"],
					[
						"Imported from",
						`${spec.source_format}${spec.original_version ? ` (${spec.original_version})` : ""}`,
					],
					["Source URL", spec.source_url ? <code key="url">{spec.source_url}</code> : "Pasted or uploaded"],
					["Spec hash", <code key="hash">{spec.spec_hash?.slice(0, 12)}</code>],
					["Last imported", spec.modified.slice(0, 16)],
				]}
			/>
			<div>
				<Button
					ref={reimportLauncher}
					kind="tertiary"
					renderIcon={Renew}
					onClick={() => {
						setReimportKey((key) => key + 1);
						setReimporting(true);
					}}
				>
					Re-import
				</Button>
				<Button kind="ghost" href={deskFormUrl(SPEC, spec.name)} renderIcon={Launch}>
					Open in the desk
				</Button>
			</div>
			{table}
			<ImportSpec
				key={`reimport-${reimportKey}`}
				open={reimporting}
				spec={spec}
				launcherButtonRef={reimportLauncher}
				onClose={() => setReimporting(false)}
				onImported={reimported}
			/>
			<NewTransform
				key={`transform-${transformKey}`}
				open={creating}
				spec={spec.name}
				operation={operation}
				launcherButtonRef={transformLauncher}
				onClose={() => setCreating(false)}
			/>
		</Stack>
	);
}
