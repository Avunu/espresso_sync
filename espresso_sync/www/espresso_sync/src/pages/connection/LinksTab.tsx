// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect, useRef, useState } from "react";
import {
	Button,
	Checkbox,
	CodeSnippet,
	DataTable,
	DataTableSkeleton,
	Dropdown,
	InlineNotification,
	Link as CarbonLink,
	OverflowMenu,
	OverflowMenuItem,
	Pagination,
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
	Toggle,
} from "@carbon/react";
import { Add, Launch, Link as LinkIcon } from "@carbon/react/icons";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { plural } from "../../../../../public/js/portal/datetime.ts";
import { ConfirmDangerModal } from "../../components/ConfirmDangerModal";
import { DateTime } from "../../components/DateTime";
import { EmptyState } from "../../components/EmptyState";
import { type Check, type Deleted, type Link, type LinkList, METHODS } from "../../data/api";
import { useConnectionStatus } from "../../data/useConnectionStatus";
import { useToasts } from "../../portal/Toasts";
import { getErrorMessage, useBackendCall } from "../../portal/useBackendCall";
import { deskFormUrl, hrefFor, navigate, replaceQuery } from "../../route";
import { useSessionRead } from "../../useSessionRead";
import { LinkModal } from "./LinkModal";
import { toolbarProps } from "./ShotsTab";
import { useInlineCall } from "./ShotModal";

export interface LinksTabProps {
	/** The Connection's name. */
	connection: string;
	/** The DocTypes of its shots: what "Link a document" offers. */
	shotDoctypes: string[];
	/** The route's query: `doctype`, `q`, `off`, `page` and `size`. */
	query: Readonly<Record<string, string>>;
}

const HEADERS = [
	{ key: "parenttype", header: "DocType" },
	{ key: "parent", header: "Document" },
	{ key: "external_id", header: "External ID" },
	{ key: "last_synced_modified", header: "Last synced" },
	{ key: "external_modified", header: "API modified" },
	{ key: "dont_sync", header: "Sync" },
];

const PAGE_SIZES = [25, 50, 100];
const DEFAULT_SIZE = 50;
const SEARCH_DELAY_MS = 300;
const ALL_DOCTYPES = "All DocTypes";

/** The tab's filters and its page, as the route's query carries them. */
interface LinkFilters {
	doctype: string;
	q: string;
	off: boolean;
	page: number;
	size: number;
}

function filtersOf(query: Readonly<Record<string, string>>): LinkFilters {
	const page = Number.parseInt(query["page"] ?? "", 10);
	const size = Number.parseInt(query["size"] ?? "", 10);
	return {
		doctype: query["doctype"] ?? "",
		q: query["q"] ?? "",
		off: query["off"] === "1",
		page: page > 1 ? page : 1,
		size: PAGE_SIZES.includes(size) ? size : DEFAULT_SIZE,
	};
}

/** Put the filters in the URL; what is as it starts out is left out of it. */
function writeFilters(filters: LinkFilters): void {
	replaceQuery({
		doctype: filters.doctype || undefined,
		q: filters.q || undefined,
		off: filters.off ? "1" : undefined,
		page: filters.page > 1 ? String(filters.page) : undefined,
		size: filters.size === DEFAULT_SIZE ? undefined : String(filters.size),
	});
}

interface LinkCellProps {
	link: Link;
	column: string;
	now: string | undefined;
	/** Whether the document syncs, as shown: what was just asked for, until it is answered. */
	syncs: boolean;
	busy: boolean;
	onToggle: (syncs: boolean) => void;
}

function LinkCell({ link, column, now, syncs, busy, onToggle }: LinkCellProps) {
	switch (column) {
		case "parenttype":
			return <>{link.parenttype}</>;
		case "parent":
			return (
				<CarbonLink
					href={deskFormUrl(link.parenttype, link.parent)}
					target="_blank"
					rel="noreferrer"
					renderIcon={Launch}
					title="Open in the desk, in a new tab"
				>
					{link.parent}
				</CarbonLink>
			);
		case "external_id":
			return link.external_id ? (
				<CodeSnippet type="inline" feedback="Copied" aria-label={`Copy the External ID ${link.external_id}`}>
					{link.external_id}
				</CodeSnippet>
			) : (
				<>None</>
			);
		case "last_synced_modified":
			return <DateTime value={link.last_synced_modified} now={now} />;
		case "external_modified":
			return <DateTime value={link.external_modified} now={now} />;
		case "dont_sync":
			return (
				<Toggle
					id={`link-sync-${link.name}`}
					size="sm"
					hideLabel
					aria-label={`Sync ${link.parenttype} ${link.parent}`}
					toggled={syncs}
					disabled={busy}
					onToggle={onToggle}
				/>
			);
		default:
			return null;
	}
}

/** `#/connections/<name>/links`: the documents linked to an object in the API (Espresso Sync ID rows). */
export function LinksTab({ connection, shotDoctypes, query }: LinksTabProps) {
	const filters = filtersOf(query);
	const { data, error, isLoading, mutate } = useFrappeGetCall<FrappeResponse<LinkList>>(
		METHODS.listLinks,
		{
			connection,
			doctype: filters.doctype || undefined,
			search: filters.q || undefined,
			not_syncing: filters.off ? 1 : 0,
			start: (filters.page - 1) * filters.size,
			limit: filters.size,
		},
		undefined,
		// the rows stay while another page or filter loads, so the table keeps its height
		{ keepPreviousData: true },
	);
	useSessionRead(data, error);
	const { now } = useConnectionStatus(connection);
	const list = data?.message;

	const change = useBackendCall<Link>(METHODS.updateLink, "The link couldn't be changed.");
	const forget = useBackendCall<Link>(METHODS.forgetLink, "The link couldn't be changed.");
	const remove = useInlineCall<Deleted>(METHODS.deleteLink, "Try again.");
	const showToast = useToasts();

	// typed text: it reaches the URL, and with it the server, once the typing stops
	const [search, setSearch] = useState(filters.q);
	// Carbon's search box keeps its own text: a new one is made when the filters are cleared
	const [searchBox, setSearchBox] = useState(0);
	const { doctype: byDoctype, q: searched, off: notSyncing, size: perPage } = filters;
	useEffect(() => {
		const q = search.trim();
		if (q === searched) return undefined;
		const timer = window.setTimeout(
			() => writeFilters({ doctype: byDoctype, q, off: notSyncing, page: 1, size: perPage }),
			SEARCH_DELAY_MS,
		);
		return () => window.clearTimeout(timer);
	}, [search, searched, byDoctype, notSyncing, perPage]);

	// a page past the last one (its rows were removed, or the URL was edited): back to the first
	const pastTheEnd = Boolean(list && list.rows.length === 0 && list.total > 0 && filters.page > 1);
	useEffect(() => {
		if (pastTheEnd) replaceQuery({ ...query, page: undefined });
	}, [pastTheEnd, query]);

	// what a Sync toggle was just set to, until the list says the same
	const [asked, setAsked] = useState<Record<string, Check>>({});
	// the modal is mounted while closed, so it hands the focus back; a new one each time it opens
	const [editing, setEditing] = useState<{ open: boolean; key: number; link: Link | undefined }>({
		open: false,
		key: 0,
		link: undefined,
	});
	const [removing, setRemoving] = useState<{ open: boolean; link: Link | undefined }>({
		open: false,
		link: undefined,
	});
	// what opened a dialog: the Link a document button, or the Actions menu of a row
	const launcher = useRef<HTMLElement | null>(null);

	async function setSyncs(link: Link, syncs: boolean) {
		if (syncs && !link.external_id) {
			// the server refuses it too: synced without one, the document is created in the API again
			showToast({
				kind: "info",
				title: `${link.parent} needs an External ID before it syncs.`,
				subtitle: "Give it the ID of its object in the API, then turn its sync on.",
			});
			launcher.current = document.getElementById(`link-sync-${link.name}`);
			edit(link);
			return;
		}
		const dontSync: Check = syncs ? 0 : 1;
		setAsked((current) => ({ ...current, [link.name]: dontSync }));
		const result = await change.call({ name: link.name, dont_sync: dontSync });
		if (result.ok) await mutate();
		setAsked(({ [link.name]: _answered, ...rest }) => rest);
	}

	async function syncAgain(link: Link) {
		const result = await forget.call({ name: link.name });
		if (!result.ok) return;
		showToast({ kind: "success", title: `${link.parent} syncs again with the next sync.` });
		void mutate();
	}

	async function removeLink() {
		const { link } = removing;
		if (!link) return;
		const answer = await remove.call({ name: link.name });
		if (!answer) return;
		setRemoving((current) => ({ ...current, open: false }));
		showToast({ kind: "success", title: `The link of ${link.parent} was removed.` });
		void mutate();
	}

	function edit(link: Link | undefined) {
		setEditing((current) => ({ open: true, key: current.key + 1, link }));
	}

	function clearFilters() {
		setSearch("");
		setSearchBox((key) => key + 1);
		writeFilters({ ...filters, doctype: "", q: "", off: false, page: 1 });
	}

	const linkButton = (
		<Button
			kind="primary"
			renderIcon={Add}
			disabled={shotDoctypes.length === 0}
			onClick={(event) => {
				launcher.current = event.currentTarget;
				edit(undefined);
			}}
		>
			Link a document
		</Button>
	);

	const filtered = Boolean(filters.doctype || filters.q || filters.off);
	let content;
	if (!list && isLoading) {
		content = <DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length + 1} rowCount={5} />;
	} else if (!list) {
		content = (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The linked documents couldn't be loaded."
				subtitle={getErrorMessage(error, "Reload the page to try again.")}
			/>
		);
	} else if (list.total === 0 && list.doctypes.length === 0 && !filtered) {
		content = (
			<EmptyState icon={LinkIcon} title="No linked documents yet." action={linkButton}>
				A sync links each document it imports or exports to its object in the API.{" "}
				{shotDoctypes.length === 0
					? "Add a shot first: a document is linked on a DocType the connection syncs."
					: "Link one by hand when it is already on both sides, so that the next sync does not create it again."}
			</EmptyState>
		);
	} else {
		const byId = new Map(list.rows.map((row) => [row.name, row]));
		const rows = list.rows.map((row) => ({ ...row, id: row.name }));
		// the DocType in the URL is on offer even when the Connection has no link of it (any more)
		const doctypes = [...new Set([...list.doctypes, ...(filters.doctype ? [filters.doctype] : [])])].sort();
		content = (
			<>
				<DataTable rows={rows} headers={HEADERS} size="md">
					{({
						rows: tableRows,
						headers,
						getTableProps,
						getTableContainerProps,
						getToolbarProps,
						getHeaderProps,
						getRowProps,
						getCellProps,
					}) => (
						<TableContainer
							title="Linked documents"
							description={`${plural(list.total, "document", "documents")}${filtered ? " match the filters" : ""}, each linked to its object in the API by an External ID.`}
							{...getTableContainerProps()}
						>
							<TableToolbar {...toolbarProps(getToolbarProps())} aria-label="Linked documents">
								<TableToolbarContent>
									<TableToolbarSearch
										key={searchBox}
										persistent
										labelText="Search by document or External ID"
										placeholder="Search by document or External ID"
										defaultValue={filters.q}
										onChange={(event) => setSearch(typeof event === "string" ? event : event.target.value)}
									/>
									<div style={{ inlineSize: "14rem", flexShrink: 0 }}>
										<Dropdown
											id="links-doctype"
											titleText="DocType"
											hideLabel
											label={ALL_DOCTYPES}
											size="lg"
											items={[ALL_DOCTYPES, ...doctypes]}
											selectedItem={filters.doctype || ALL_DOCTYPES}
											onChange={({ selectedItem }) =>
												writeFilters({
													...filters,
													doctype: !selectedItem || selectedItem === ALL_DOCTYPES ? "" : selectedItem,
													page: 1,
												})
											}
										/>
									</div>
									<div
										style={{
											display: "flex",
											alignItems: "center",
											flexShrink: 0,
											paddingInline: "var(--cds-spacing-05)",
										}}
									>
										<Checkbox
											id="links-not-syncing"
											labelText="Not syncing only"
											checked={filters.off}
											onChange={(_event, { checked }) => writeFilters({ ...filters, off: checked, page: 1 })}
										/>
									</div>
									{linkButton}
								</TableToolbarContent>
							</TableToolbar>
							<Table {...getTableProps()} aria-label="Linked documents">
								<TableHead>
									<TableRow>
										{headers.map((header) => {
											const { key, isSortable, ...headerProps } = getHeaderProps({ header });
											return (
												<TableHeader key={key} isSortable={Boolean(isSortable)} {...headerProps}>
													{header.header}
												</TableHeader>
											);
										})}
										<TableHeader aria-label="Actions" />
									</TableRow>
								</TableHead>
								<TableBody>
									{tableRows.length === 0 && (
										<TableRow>
											<TableCell colSpan={headers.length + 1}>
												<EmptyState
													title="No linked documents match these filters."
													action={
														<Button kind="tertiary" size="sm" onClick={clearFilters}>
															Clear filters
														</Button>
													}
												/>
											</TableCell>
										</TableRow>
									)}
									{tableRows.map((tableRow) => {
										const link = byId.get(tableRow.id);
										if (!link) return null;
										const { key, ...rowProps } = getRowProps({ row: tableRow });
										const dontSync = asked[link.name] ?? link.dont_sync;
										return (
											<TableRow key={key} {...rowProps}>
												{tableRow.cells.map((cell) => {
													const { key: cellKey, ...cellProps } = getCellProps({ cell });
													return (
														<TableCell key={cellKey} {...cellProps}>
															<LinkCell
																link={link}
																column={cell.info.header}
																now={now}
																syncs={!dontSync}
																busy={link.name in asked}
																onToggle={(syncs) => void setSyncs(link, syncs)}
															/>
														</TableCell>
													);
												})}
												<TableCell className="cds--table-column-menu" style={{ inlineSize: "4rem" }}>
													<OverflowMenu
														aria-label={`Actions for ${link.parent}`}
														iconDescription={`Actions for ${link.parent}`}
														size="md"
														flipped
														onClick={(event?: { currentTarget?: unknown }) => {
															if (event?.currentTarget instanceof HTMLElement)
																launcher.current = event.currentTarget;
														}}
													>
														<OverflowMenuItem itemText="Edit external ID" onClick={() => edit(link)} />
														<OverflowMenuItem
															itemText="Sync again next time"
															disabled={
																forget.loading || (!link.last_synced_modified && !link.external_modified)
															}
															onClick={() => void syncAgain(link)}
														/>
														<OverflowMenuItem
															itemText="View log entries"
															onClick={() =>
																navigate(
																	hrefFor("logs", undefined, {
																		query: { connection, doctype: link.parenttype, doc: link.parent },
																	}),
																)
															}
														/>
														<OverflowMenuItem
															itemText="Remove link…"
															isDelete
															hasDivider
															onClick={() => {
																remove.reset();
																setRemoving({ open: true, link });
															}}
														/>
													</OverflowMenu>
												</TableCell>
											</TableRow>
										);
									})}
								</TableBody>
							</Table>
						</TableContainer>
					)}
				</DataTable>
				<Pagination
					page={filters.page}
					pageSize={filters.size}
					pageSizes={PAGE_SIZES}
					totalItems={list.total}
					size="md"
					itemsPerPageText="Documents per page:"
					onChange={({ page, pageSize }) =>
						writeFilters({ ...filters, page: pageSize === filters.size ? page : 1, size: pageSize })
					}
				/>
			</>
		);
	}

	return (
		<Stack gap={6}>
			{/* shown with the rows it failed to refresh; with none, the notice above says it */}
			{Boolean(error) && list && (
				<InlineNotification
					kind="error"
					lowContrast
					hideCloseButton
					title="The linked documents couldn't be refreshed."
					subtitle={getErrorMessage(error, "Reload the page to try again.")}
				/>
			)}
			<div>{content}</div>
			<LinkModal
				key={editing.key}
				open={editing.open}
				connection={connection}
				shotDoctypes={shotDoctypes}
				link={editing.link}
				launcherButtonRef={launcher}
				onClose={() => setEditing((current) => ({ ...current, open: false }))}
				onSaved={(saved) => {
					const added = !editing.link;
					setEditing((current) => ({ ...current, open: false }));
					showToast({
						kind: "success",
						title: added
							? `${saved.parent} is linked to ${saved.external_id ?? "its object"}.`
							: `The External ID of ${saved.parent} was saved.`,
					});
					void mutate();
				}}
			/>
			<ConfirmDangerModal
				open={removing.open}
				heading={`Remove the link of ${removing.link?.parent ?? "the document"}?`}
				label={removing.link?.parenttype}
				primaryText="Remove link"
				busy={remove.busy}
				error={remove.error}
				launcherButtonRef={launcher}
				onConfirm={() => void removeLink()}
				onClose={() => setRemoving((current) => ({ ...current, open: false }))}
			>
				The document and its object in the API both stay, but the sync no longer knows them as one. The next
				sync may create a duplicate.
			</ConfirmDangerModal>
		</Stack>
	);
}
