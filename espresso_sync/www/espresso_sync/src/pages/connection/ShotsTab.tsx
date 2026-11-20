// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useRef, useState } from "react";
import {
	Button,
	Callout,
	DataTable,
	InlineNotification,
	Link,
	OverflowMenu,
	OverflowMenuItem,
	Stack,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableExpandedRow,
	TableExpandHeader,
	TableExpandRow,
	TableHead,
	TableHeader,
	TableRow,
	TableToolbar,
	TableToolbarContent,
	Tag,
} from "@carbon/react";
import { Add, DataShare } from "@carbon/react/icons";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { ConfirmDangerModal } from "../../components/ConfirmDangerModal";
import { DateTime } from "../../components/DateTime";
import { DescriptionList } from "../../components/DescriptionList";
import { EmptyState } from "../../components/EmptyState";
import {
	type ConnectionDetail,
	type Direction,
	METHODS,
	type ResetShotAnswer,
	type Shot,
	type ShotOption,
	type ShotsAnswer,
	type StatusProblem,
	type StatusRow,
} from "../../data/api";
import { useConnectionStatus } from "../../data/useConnectionStatus";
import { useToasts } from "../../portal/Toasts";
import { useBackendCall } from "../../portal/useBackendCall";
import { hrefFor, navigate } from "../../route";
import { useSessionRead } from "../../useSessionRead";
import { SeverityIcon } from "../SeverityIcon";
import { ShotModal, useInlineCall } from "./ShotModal";

export interface ShotsTabProps {
	/** The Connection as `get_connection` answered: its `shots` are the rows. */
	connection: ConnectionDetail;
	/** Its `list_status` row: editing is off while it is queued or running. */
	status: StatusRow | undefined;
	/** Called after a shot is saved, moved, reset or removed, for the page to refetch. */
	onChanged: () => void;
}

const HEADERS = [
	{ key: "dt", header: "DocType" },
	{ key: "import", header: "Import" },
	{ key: "last_import", header: "Last import" },
	{ key: "export", header: "Export" },
	{ key: "last_export", header: "Last export" },
];

/** DataTable's toolbar props as TableToolbar takes them: with no size, not an undefined one. */
export function toolbarProps<Size extends string>({ size, ...rest }: { size: Size | undefined }) {
	return size === undefined ? rest : { ...rest, size };
}

/** What the tab knows of the transforms: `shot_options` by name, and the problems
 * `list_status` found with the shots. */
interface TransformFacts {
	options: Map<string, ShotOption> | undefined;
	problems: StatusProblem[];
}

interface TransformRefProps {
	name: string | null;
	/** What stands for no transform: "Off", "None". */
	none: string;
	facts: TransformFacts;
}

/** A transform of a shot: a link to its editor, flagged when a sync would refuse it. */
function TransformRef({ name, none, facts }: TransformRefProps) {
	if (!name) return <>{none}</>;
	const problem = facts.problems.find((entry) => entry.transform === name);
	const draft = facts.options?.get(name)?.status === "Draft" || problem?.code === "transform-not-active";
	return (
		<span
			style={{ display: "inline-flex", flexWrap: "wrap", alignItems: "center", gap: "var(--cds-spacing-03)" }}
		>
			<Link href={hrefFor("transforms", name)}>{name}</Link>
			{/* the status as the Transforms list shows it; what is wrong with it is said apart */}
			{draft && (
				<Tag type="gray" size="sm">
					Draft
				</Tag>
			)}
			{(draft || problem) && (
				<span style={{ display: "inline-flex", alignItems: "center", gap: "var(--cds-spacing-02)" }}>
					<SeverityIcon severity="error" />
					<span>{draft ? "A sync refuses a Draft." : `${problem?.message ?? "Not usable"}.`}</span>
				</span>
			)}
		</span>
	);
}

interface ShotCellProps {
	shot: Shot;
	column: string;
	facts: TransformFacts;
	now: string | undefined;
}

function ShotCell({ shot, column, facts, now }: ShotCellProps) {
	switch (column) {
		case "dt":
			return <>{shot.dt}</>;
		case "import":
			if (!shot.do_import) return <>Off</>;
			if (!shot.import_transform)
				return (
					<Tag type="red" size="sm">
						No transform
					</Tag>
				);
			return <TransformRef name={shot.import_transform} none="Off" facts={facts} />;
		case "last_import":
			return shot.do_import || shot.last_import ? <DateTime value={shot.last_import} now={now} /> : <>—</>;
		case "export":
			if (!shot.do_export) return <>Off</>;
			if (!shot.export_transform)
				return (
					<Tag type="red" size="sm">
						No transform
					</Tag>
				);
			return <TransformRef name={shot.export_transform} none="Off" facts={facts} />;
		case "last_export":
			return shot.do_export || shot.last_export ? <DateTime value={shot.last_export} now={now} /> : <>—</>;
		default:
			return null;
	}
}

/** What a confirmation is about: removing a shot, or forgetting one of its two times. */
interface Confirmation {
	action: "remove" | Direction;
	shot: Shot;
}

function confirmationCopy({ action, shot }: Confirmation, connection: string) {
	if (action === "remove") {
		return {
			heading: `Remove the ${shot.dt} shot?`,
			primaryText: "Remove",
			body: `${connection} stops syncing ${shot.dt}. The documents it synced stay, with their links, and so does the Sync tab of ${shot.dt}.`,
		};
	}
	if (action === "Import") {
		return {
			heading: `Reset the last import of ${shot.dt}?`,
			primaryText: "Reset",
			body: `The next sync reads every ${shot.dt} object from the API again, not only those changed since the last import. Nothing is queued now.`,
		};
	}
	return {
		heading: `Reset the last export of ${shot.dt}?`,
		primaryText: "Reset",
		body: `The next sync goes through every ${shot.dt} document again, not only those changed since the last export. Documents already in sync are skipped. Nothing is queued now.`,
	};
}

/** `#/connections/<name>/shots`: the DocTypes the Connection syncs, and through which transforms. */
export function ShotsTab({ connection, status, onChanged }: ShotsTabProps) {
	const { name, shots } = connection;
	const options = useFrappeGetCall<FrappeResponse<ShotOption[]>>(METHODS.shotOptions, { connection: name });
	useSessionRead(options.data, options.error);
	const { now } = useConnectionStatus(name);
	const move = useBackendCall<ShotsAnswer>(METHODS.moveShot, "The shot couldn't be moved.");
	const remove = useInlineCall<ShotsAnswer>(METHODS.removeShot, "Try again.");
	const reset = useInlineCall<ResetShotAnswer>(METHODS.resetShot, "Try again.");
	const showToast = useToasts();

	// the modal is mounted while closed, so it hands the focus back; a new one each time it opens
	const [editing, setEditing] = useState<{ open: boolean; key: number; shot: Shot | undefined }>({
		open: false,
		key: 0,
		shot: undefined,
	});
	const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
	const [confirming, setConfirming] = useState(false);
	// what opened a dialog: the Add button, or the Actions menu of a row
	const launcher = useRef<HTMLElement | null>(null);

	const locked = status !== undefined && status.state !== "idle";
	const facts: TransformFacts = {
		options: options.data?.message && new Map(options.data.message.map((option) => [option.name, option])),
		problems: status?.problems ?? [],
	};

	function edit(shot: Shot | undefined) {
		// a transform made or activated since is on offer
		void options.mutate();
		setEditing((current) => ({ open: true, key: current.key + 1, shot }));
	}

	function ask(action: Confirmation["action"], shot: Shot) {
		remove.reset();
		reset.reset();
		setConfirmation({ action, shot });
		setConfirming(true);
	}

	async function moveShot(shot: Shot, by: -1 | 1) {
		const result = await move.call({ connection: name, name: shot.name, by });
		if (result.ok) onChanged();
	}

	async function confirm() {
		if (!confirmation) return;
		const { action, shot } = confirmation;
		const answer =
			action === "remove"
				? await remove.call({ connection: name, name: shot.name })
				: await reset.call({ connection: name, name: shot.name, direction: action });
		if (!answer) return;
		setConfirming(false);
		showToast({
			kind: "success",
			title:
				action === "remove"
					? `The ${shot.dt} shot was removed.`
					: `The last ${action.toLowerCase()} of ${shot.dt} was reset.`,
		});
		onChanged();
	}

	const addButton = (
		<Button
			kind="primary"
			renderIcon={Add}
			disabled={locked}
			onClick={(event) => {
				launcher.current = event.currentTarget;
				edit(undefined);
			}}
		>
			Add shot
		</Button>
	);

	const byId = new Map(shots.map((shot) => [shot.name, shot]));
	const rows = shots.map((shot) => ({
		id: shot.name,
		dt: shot.dt,
		import: shot.import_transform,
		last_import: shot.last_import,
		export: shot.export_transform,
		last_export: shot.last_export,
	}));
	const copy = confirmation && confirmationCopy(confirmation, name);

	return (
		<Stack gap={6}>
			{locked && (
				<InlineNotification
					kind="info"
					lowContrast
					hideCloseButton
					title={`${name} is ${status.state === "running" ? "syncing" : "queued to sync"}.`}
					subtitle="Its shots can be changed when the sync is done."
				/>
			)}
			{shots.length === 0 ? (
				<EmptyState icon={DataShare} title="No shots yet." action={addButton}>
					A shot is a DocType the connection syncs: whether it is imported, exported or both, and through
					which transforms.
				</EmptyState>
			) : (
				<DataTable rows={rows} headers={HEADERS} size="md">
					{({
						rows: tableRows,
						headers,
						getTableProps,
						getTableContainerProps,
						getToolbarProps,
						getHeaderProps,
						getExpandHeaderProps,
						getRowProps,
						getExpandedRowProps,
						getCellProps,
					}) => (
						<TableContainer
							title="Shots"
							description="The DocTypes the connection syncs, in the order a sync runs them."
							{...getTableContainerProps()}
						>
							<TableToolbar {...toolbarProps(getToolbarProps())} aria-label="Shots">
								<TableToolbarContent>{addButton}</TableToolbarContent>
							</TableToolbar>
							<Table {...getTableProps()} aria-label="Shots">
								<TableHead>
									<TableRow>
										<TableExpandHeader enableToggle {...getExpandHeaderProps()} />
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
									{tableRows.map((tableRow, index) => {
										const shot = byId.get(tableRow.id);
										if (!shot) return null;
										const { key, ...rowProps } = getRowProps({ row: tableRow });
										return [
											<TableExpandRow key={key} {...rowProps}>
												{tableRow.cells.map((cell) => {
													const { key: cellKey, ...cellProps } = getCellProps({ cell });
													return (
														<TableCell key={cellKey} {...cellProps}>
															<ShotCell shot={shot} column={cell.info.header} facts={facts} now={now} />
														</TableCell>
													);
												})}
												<TableCell className="cds--table-column-menu" style={{ inlineSize: "4rem" }}>
													<OverflowMenu
														aria-label={`Actions for ${shot.dt}`}
														iconDescription={`Actions for ${shot.dt}`}
														size="md"
														flipped
														onClick={(event?: { currentTarget?: unknown }) => {
															if (event?.currentTarget instanceof HTMLElement)
																launcher.current = event.currentTarget;
														}}
													>
														<OverflowMenuItem itemText="Edit" disabled={locked} onClick={() => edit(shot)} />
														<OverflowMenuItem
															itemText="Move up"
															disabled={locked || index === 0 || move.loading}
															onClick={() => void moveShot(shot, -1)}
														/>
														<OverflowMenuItem
															itemText="Move down"
															disabled={locked || index === tableRows.length - 1 || move.loading}
															onClick={() => void moveShot(shot, 1)}
														/>
														<OverflowMenuItem
															itemText="View log entries"
															onClick={() =>
																navigate(
																	hrefFor("logs", undefined, {
																		query: { connection: name, doctype: shot.dt },
																	}),
																)
															}
														/>
														<OverflowMenuItem
															itemText="Reset last import"
															disabled={locked || !shot.last_import}
															onClick={() => ask("Import", shot)}
														/>
														<OverflowMenuItem
															itemText="Reset last export"
															disabled={locked || !shot.last_export}
															onClick={() => ask("Export", shot)}
														/>
														<OverflowMenuItem
															itemText="Remove…"
															isDelete
															hasDivider
															disabled={locked}
															onClick={() => ask("remove", shot)}
														/>
													</OverflowMenu>
												</TableCell>
											</TableExpandRow>,
											tableRow.isExpanded && (
												<TableExpandedRow
													key={`${key}-expanded`}
													colSpan={headers.length + 2}
													{...getExpandedRowProps({ row: tableRow })}
												>
													<DescriptionList
														label={`The other transforms of the ${shot.dt} shot`}
														items={[
															[
																"Update transform",
																<TransformRef
																	key="update"
																	name={shot.update_transform}
																	none="None: the create transform sends updates too."
																	facts={facts}
																/>,
															],
															[
																"Follow-up transform",
																<TransformRef
																	key="follow-up"
																	name={shot.follow_up_transform}
																	none="None"
																	facts={facts}
																/>,
															],
														]}
													/>
												</TableExpandedRow>
											),
										];
									})}
								</TableBody>
							</Table>
						</TableContainer>
					)}
				</DataTable>
			)}
			<Callout
				kind="info"
				lowContrast
				title="Saving exports everything again."
				subtitle="After a shot or the Connection is saved, the next sync exports every document of its exporting shots again; documents already in sync are skipped."
			/>
			<ShotModal
				key={editing.key}
				open={editing.open}
				connection={name}
				shot={editing.shot}
				taken={shots.map((shot) => shot.dt)}
				options={options.data?.message ?? []}
				optionsError={options.error}
				launcherButtonRef={launcher}
				onClose={() => setEditing((current) => ({ ...current, open: false }))}
				onSaved={() => {
					const { shot } = editing;
					setEditing((current) => ({ ...current, open: false }));
					showToast({
						kind: "success",
						title: shot ? `The ${shot.dt} shot was saved.` : "The shot was added.",
					});
					onChanged();
				}}
			/>
			<ConfirmDangerModal
				open={confirming}
				heading={copy?.heading ?? ""}
				label={name}
				primaryText={copy?.primaryText ?? "Confirm"}
				busy={remove.busy || reset.busy}
				error={remove.error ?? reset.error}
				launcherButtonRef={launcher}
				onConfirm={() => void confirm()}
				onClose={() => setConfirming(false)}
			>
				{copy?.body}
			</ConfirmDangerModal>
		</Stack>
	);
}
