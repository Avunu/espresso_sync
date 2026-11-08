// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useState } from "react";
import {
	Button,
	ComboBox,
	InlineNotification,
	Stack,
	StructuredListBody,
	StructuredListCell,
	StructuredListRow,
	StructuredListWrapper,
	Tag,
	TextArea,
} from "@carbon/react";
import { TrashCan } from "@carbon/react/icons";
import type { Rule } from "../../../../public/js/editor/compile.ts";
import type { Diagnostic } from "../../../../public/js/editor/diagnostics.ts";
import { type RuleResults, type Snippet, syntaxError } from "../../../../public/js/editor/mapping.ts";
import { fromPointer, toPointer } from "../../../../public/js/editor/pointer.ts";
import { ruleKind, type TreeNode as Field } from "../../../../public/js/editor/schemaTree.ts";
import { fieldType } from "./FieldTree";

/** A function to insert, as the design's palette groups them. */
interface PaletteItem {
	group: string;
	text: string;
	help: string;
	snippet: Snippet;
}

// group, text, help, and the snippet's two sides
const ITEMS: [string, string, string, string, string][] = [
	["Text", "$string()", "Make text", "$string(", ")"],
	["Text", "$uppercase()", "Upper case", "$uppercase(", ")"],
	["Text", "$trim()", "Trim the spaces", "$trim(", ")"],
	["Text", "$substring()", "Part of a text", "$substring(", ", 0, 10)"],
	["Text", "$join()", "Join a list of texts", "$join(", ', ", ")'],
	["Text", "$split()", "Split a text into a list", "$split(", ', ",")'],
	["Text", "$replace()", "Replace text", "$replace(", ', "a", "b")'],
	["Text", "&", "Join two texts", " & ", ""],
	["Number", "$number()", "Make a number", "$number(", ")"],
	["Number", "$round()", "Round to decimals", "$round(", ", 2)"],
	["Number", "$sum()", "Add a list up", "$sum(", ")"],
	["Number", "$count()", "Count the items", "$count(", ")"],
	["Number", "$abs()", "Absolute value", "$abs(", ")"],
	["Logic", "? :", "If, else", " ? ", ' : ""'],
	["Logic", "=", "Equals", " = ", ""],
	["Logic", "and", "Both true", " and ", ""],
	["Logic", "$exists()", "Has a value", "$exists(", ")"],
	["Logic", "$contains()", "Contains text", "$contains(", ', "x")'],
	["Context", "$$", "The source item, inside a collection", "$$.", ""],
	["Context", "$", "The current item", "$", ""],
	["Context", "[0]", "The first one", "[0]", ""],
	["Context", "$now()", "Now, as an ISO timestamp", "$now()", ""],
	["Frappe", "$frappeDate()", "A date as Frappe stores it", "$frappeDate(", ")"],
	["Frappe", "$frappeDatetime()", "A datetime in the system time zone", "$frappeDatetime(", ")"],
	["Frappe", "$frappeCheck()", "0 or 1, for a Check", "$frappeCheck(", ")"],
	["Frappe", "$getValue()", "A field of a document", '$getValue("', '", name, "fieldname")'],
	["Frappe", "$syncId()", "A document's id in the API", '$syncId("', '", name)'],
	["Frappe", "$localName()", "The document with an id in the API", '$localName("', '", id)'],
];

const PALETTE: PaletteItem[] = ITEMS.map(([group, text, help, before, after]) => ({
	group,
	text,
	help,
	snippet: { before, after },
}));

const SHOWN_RESULTS = 25;

/** Whether an item's text has the text typed in a combo box in it. */
function hasText<T>({
	item,
	itemToString,
	inputValue,
}: {
	item: T;
	itemToString?: (item: T | null) => string;
	inputValue: string | null;
}): boolean {
	return !inputValue || (itemToString?.(item) ?? "").toLowerCase().includes(inputValue.toLowerCase());
}

/** A rule's pointer as people read it: `/lines/qty` is `lines[].qty` when lines is a list. */
function pointerLabel(pointer: string, isList: (pointer: string) => boolean): string {
	const segments = fromPointer(pointer);
	return segments
		.map((segment, index) => {
			const at = toPointer(segments.slice(0, index + 1));
			return index < segments.length - 1 && isList(at) ? `${segment}[]` : segment;
		})
		.join(".");
}

function shown(value: unknown, defined: boolean): string {
	return defined ? JSON.stringify(value) : "nothing: the field is left out";
}

interface RuleInspectorProps {
	pointer: string;
	field: Field | undefined;
	rule: Rule | undefined;
	/** The source path of the items a rule here runs on; undefined when that isn't a plain path. */
	context: string[] | undefined;
	results: RuleResults | undefined;
	diagnostics: Diagnostic[];
	/** How many sample items there are. */
	items: number;
	/** The source fields the rule reads. */
	reads: string[];
	/** The source fields, as a rule here reads them. */
	sources: { pointer: string; text: string }[];
	/** An object's fields and their rules. */
	members: { field: Field; rule: Rule | undefined }[];
	isList: (pointer: string) => boolean;
	expressionRef: RefObject<HTMLTextAreaElement | null>;
	onChange: (expression: string) => void;
	onInsert: (snippet: Snippet) => void;
	onSelect: (pointer: string) => void;
}

/** The selected target field: its rule's expression, what it gives on the sample, and what to insert. */
export function RuleInspector(props: RuleInspectorProps) {
	const { pointer, field, rule, context, results, diagnostics, items, reads, sources, members, isList } =
		props;
	const { expressionRef } = props;
	const kind = field ? ruleKind(field) : rule?.kind;
	const name = field?.key || "(the body)";
	const label = pointerLabel(pointer, isList);
	const expression = rule?.expr ?? "";
	const syntax = expression.trim() ? syntaxError(expression) : undefined;
	const inCollection = context !== undefined && context.length > 0;
	// each insertion starts the boxes over, empty
	const [insertions, setInsertions] = useState(0);
	const insert = (snippet: Snippet) => {
		setInsertions((count) => count + 1);
		props.onInsert(snippet);
	};

	let heading = "Object";
	if (kind === "collection") heading = "Collection rule";
	else if (kind === "scalar_collection") heading = "List rule";
	else if (kind === "field") heading = "Field rule";

	let hint = "Runs on the source item.";
	if (kind === "collection") {
		hint =
			"Gives the items of the list: each becomes one entry, and the rules under it run on that item. $$ is the source item.";
	} else if (kind === "scalar_collection") {
		hint = "Gives the values of the list.";
	}
	if (kind !== "collection" && inCollection) {
		hint = `Runs on each item of ${context.join(".")}: field names are the item's, and $$ is the source item.`;
	} else if (kind !== "collection" && context === undefined) {
		hint = "Runs on each item of the collection above it. $$ is the source item.";
	}

	return (
		<Stack gap={5}>
			<div>
				<p className="cds--label">{heading}</p>
				<h2 style={{ fontFamily: "var(--cds-code-02-font-family)", overflowWrap: "anywhere" }}>{name}</h2>
				{label !== name && <code>{label}</code>}
			</div>
			<div>
				{field && (
					<Tag type="outline" size="sm">
						{fieldType(field).label}
					</Tag>
				)}
				{field?.required === "hard" && (
					<Tag type="red" size="sm">
						Required
					</Tag>
				)}
				{field?.required === "server" && (
					<Tag type="warm-gray" size="sm">
						Filled in by Frappe
					</Tag>
				)}
				{inCollection && (
					<Tag type="cool-gray" size="sm">
						Per item of {context.join(".")}
					</Tag>
				)}
				{field?.readOnly && (
					<Tag type="gray" size="sm">
						Read only
					</Tag>
				)}
			</div>
			{field?.description && <p>{field.description}</p>}
			{!field && (
				<InlineNotification
					kind="warning"
					lowContrast
					hideCloseButton
					title="The target has no field here."
					subtitle="The schema changed since this rule was written: clear it, or map the field it was meant for."
				/>
			)}
			{kind === undefined && field && (
				<Stack gap={3}>
					<p>A rule fills each of this object&apos;s fields:</p>
					{members.map((member) => (
						<Button
							key={member.field.pointer}
							kind="ghost"
							size="sm"
							onClick={() => props.onSelect(member.field.pointer)}
						>
							{member.field.key}: {member.rule ? <code>{member.rule.expr}</code> : "no rule"}
						</Button>
					))}
				</Stack>
			)}
			{kind !== undefined && (
				<>
					<TextArea
						id="rule-expression"
						ref={expressionRef}
						labelText={kind === "collection" ? "Source collection (JSONata)" : "Expression (JSONata)"}
						helperText={hint}
						rows={kind === "collection" ? 2 : 4}
						spellCheck={false}
						value={expression}
						invalid={syntax !== undefined}
						invalidText={syntax ? `${syntax.message} (${syntax.code})` : undefined}
						style={{ fontFamily: "var(--cds-code-02-font-family)" }}
						onChange={(event) => props.onChange(event.target.value)}
					/>
					<div>
						<Button
							kind="ghost"
							size="sm"
							renderIcon={TrashCan}
							disabled={!rule}
							onClick={() => props.onChange("")}
						>
							Clear the rule
						</Button>
					</div>
					<ComboBox<{ pointer: string; text: string }>
						key={`field-${insertions}`}
						id="rule-insert-field"
						titleText="Insert a source field"
						placeholder="Search the source fields"
						items={sources}
						itemToString={(item) => item?.text ?? ""}
						shouldFilterItem={hasText}
						selectedItem={null}
						onChange={({ selectedItem }) => {
							if (selectedItem) insert({ before: selectedItem.text, after: "" });
						}}
					/>
					<ComboBox<PaletteItem>
						key={`function-${insertions}`}
						id="rule-insert-function"
						titleText="Insert a function or operator"
						placeholder="Search: text, number, date…"
						items={PALETTE}
						itemToString={(item) => (item ? `${item.group}: ${item.text} — ${item.help}` : "")}
						shouldFilterItem={hasText}
						selectedItem={null}
						onChange={({ selectedItem }) => {
							if (selectedItem) insert(selectedItem.snippet);
						}}
					/>
					{reads.length > 0 && (
						<div>
							<p className="cds--label">Reads</p>
							{reads.map((read) => (
								<Tag key={read} type="gray" size="sm">
									{read}
								</Tag>
							))}
						</div>
					)}
				</>
			)}
			{diagnostics.map((found) => (
				<InlineNotification
					key={`${found.origin} ${found.code} ${found.path} ${found.item ?? ""}`}
					kind={found.severity === "info" ? "info" : found.severity}
					lowContrast
					hideCloseButton
					title={found.item === undefined ? found.message : `Item ${found.item + 1}: ${found.message}`}
					subtitle={`${found.code} (${found.origin === "server" ? "server" : "browser"})`}
				/>
			))}
			{kind !== undefined && rule && <ResultList results={results} items={items} />}
		</Stack>
	);
}

function ResultList({ results, items }: { results: RuleResults | undefined; items: number }) {
	if (items === 0) return <p>Add a sample to see what this rule gives.</p>;
	if (!results) return <p>Evaluating…</p>;
	const rows: { key: string; label: string; text: string; error: boolean }[] = [];
	for (const [item, values] of results.byItem.entries()) {
		const failure = results.errors.find((error) => error.item === item);
		if (failure) {
			rows.push({ key: `${item}`, label: `Item ${item + 1}`, text: failure.error.message, error: true });
			continue;
		}
		for (const value of values) {
			const at = value.at.map((index) => index + 1).join(" › ");
			rows.push({
				key: `${item}:${value.at.join(".")}`,
				label: at ? `Item ${item + 1} › ${at}` : `Item ${item + 1}`,
				text: shown(value.value, value.defined),
				error: false,
			});
		}
	}
	return (
		<div>
			<p className="cds--label">On the sample</p>
			{rows.length === 0 && <p>The collection above it has no items in the sample.</p>}
			{rows.length > 0 && (
				<StructuredListWrapper isCondensed aria-label="What the rule gives on the sample">
					<StructuredListBody>
						{rows.slice(0, SHOWN_RESULTS).map((row) => (
							<StructuredListRow key={row.key}>
								<StructuredListCell noWrap>{row.label}</StructuredListCell>
								<StructuredListCell
									style={{
										fontFamily: "var(--cds-code-01-font-family)",
										color: row.error ? "var(--cds-text-error)" : undefined,
										overflowWrap: "anywhere",
									}}
								>
									{row.text}
								</StructuredListCell>
							</StructuredListRow>
						))}
					</StructuredListBody>
				</StructuredListWrapper>
			)}
			{rows.length > SHOWN_RESULTS && <p>and {rows.length - SHOWN_RESULTS} more.</p>}
		</div>
	);
}
