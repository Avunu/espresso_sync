// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { memo, type ReactNode } from "react";
import { FeatureFlags, Search, Stack, TreeNode, TreeView } from "@carbon/react";
import {
	Boolean as BooleanIcon,
	Calendar,
	type CarbonIconType,
	CharacterDecimal,
	CharacterWholeNumber,
	Code,
	DataStructured,
	Json,
	ListBoxes,
	ListBulleted,
	Renew,
	StringText,
	Time,
} from "@carbon/react/icons";
import type { TreeNode as Field } from "../../../../public/js/editor/schemaTree.ts";

/** The DOM id of a field's row: the lane between the trees finds rows by it. */
export function rowId(side: string, pointer: string): string {
	return `${side}:${pointer}`;
}

/** A field's type, in words and as an icon. */
export function fieldType(field: Field): { label: string; icon: CarbonIconType } {
	switch (field.kind) {
		case "collection":
			return { label: "list of objects", icon: ListBoxes };
		case "scalar_collection":
			return { label: `list of ${field.itemTypes?.join(" or ") || "values"}`, icon: ListBulleted };
		case "object":
			return { label: "object", icon: DataStructured };
		case "map":
			return { label: "object of any keys", icon: Json };
		case "cycle":
			return { label: "recursive", icon: Renew };
		case "variants":
			return { label: "one of several shapes", icon: DataStructured };
		default:
			break;
	}
	if (field.frappe?.fieldtype === "Check") return { label: "check (0 or 1)", icon: BooleanIcon };
	if (field.format === "date") return { label: "date", icon: Calendar };
	if (field.format === "date-time" || field.format === "time") return { label: field.format, icon: Time };
	const [only, ...more] = field.types;
	const label = field.types.join(" or ") || "any value";
	if (more.length > 0 || only === undefined) return { label, icon: Code };
	if (only === "integer") return { label, icon: CharacterWholeNumber };
	if (only === "number") return { label, icon: CharacterDecimal };
	if (only === "boolean") return { label, icon: BooleanIcon };
	return { label, icon: only === "string" ? StringText : Code };
}

interface FieldTreeProps {
	/** "source" or "target": the rows' ids are made of it. */
	side: string;
	/** "Source" or "Target". */
	heading: string;
	/** Which operation or DocType it is. */
	description: string;
	filter: string;
	onFilter: (text: string) => void;
	/** The checkboxes that narrow the tree further. */
	toggles: ReactNode;
	root: Field;
	/** The fields shown: undefined for all. */
	shown: ReadonlySet<string> | undefined;
	/** The groups shown open. */
	expanded: ReadonlySet<string>;
	onExpand: (expanded: Set<string>) => void;
	selected: string | undefined;
	onSelect: (field: Field) => void;
	/** A field's row, after its name. */
	details: (field: Field) => ReactNode;
}

/**
 * One side of a transform: its fields as a Carbon tree, under a filter.
 * Arrow keys move between fields and open groups, Enter or Space selects one.
 * The root's own row shows only when the root is itself a list (a request
 * body that is an array). Memoized: a large tree draws again only when its
 * props change, not with every keystroke elsewhere on the page.
 */
export const FieldTree = memo(function FieldTree(props: FieldTreeProps) {
	const { side, heading, root, shown, expanded, selected, onSelect, details } = props;
	const onToggle = (pointer: string, open: boolean) => {
		const next = new Set(expanded);
		if (open) next.add(pointer);
		else next.delete(pointer);
		props.onExpand(next);
	};
	const top = root.kind === "collection" || root.kind === "scalar_collection" ? [root] : root.children;

	const render = (field: Field, variant: string): ReactNode => {
		if (shown && !shown.has(field.pointer)) return null;
		const id = rowId(side, `${variant}${field.pointer}`);
		const { label: type, icon } = fieldType(field);
		const children = [
			...field.children.map((child) => render(child, variant)),
			...(field.variants ?? [])
				.map((option, index) => ({ option, group: `${field.pointer}#${index}` }))
				.map(({ option, group }) => (
					<TreeNode
						key={group}
						id={rowId(side, `${variant}${group}`)}
						label={`${field.variantMode === "anyOf" ? "Any of" : "One of"}: ${option.label}`}
						isExpanded={expanded.has(group) || shown !== undefined}
						onToggle={(open: boolean | undefined) => onToggle(group, Boolean(open))}
					>
						{option.node.children.map((child) => render(child, `${variant}${group}`))}
					</TreeNode>
				)),
		].filter(Boolean);
		return (
			<TreeNode
				key={id}
				id={id}
				value={field.pointer}
				renderIcon={icon}
				label={
					<>
						<span style={{ fontFamily: "var(--cds-code-02-font-family)" }}>{field.key || "(the body)"}</span>
						<span className="cds--visually-hidden">, {type}</span>
						{details(field)}
					</>
				}
				{...(children.length > 0 ? { isExpanded: expanded.has(field.pointer) || shown !== undefined } : {})}
				onToggle={(open: boolean | undefined) => onToggle(field.pointer, Boolean(open))}
				onSelect={() => onSelect(field)}
			>
				{children.length > 0 ? children : undefined}
			</TreeNode>
		);
	};

	const selectedId = selected === undefined ? undefined : rowId(side, selected);
	return (
		<section aria-labelledby={`${side}-heading`} style={{ background: "var(--cds-layer)", padding: "1rem" }}>
			<Stack gap={4}>
				<div>
					<h2 id={`${side}-heading`} className="cds--label">
						{heading}
					</h2>
					<p>{props.description}</p>
				</div>
				<Search
					size="sm"
					labelText={`Filter the ${side} fields`}
					placeholder={`Filter the ${side} fields`}
					value={props.filter}
					onChange={(event) => props.onFilter(event.target.value)}
				/>
				{props.toggles}
				{/* Carbon's switch for a tree whose selection and open groups the page holds */}
				<FeatureFlags enableTreeviewControllable>
					<TreeView
						label={`${heading} fields`}
						hideLabel
						selected={selectedId === undefined ? [] : [selectedId]}
						// no row has the id "": nothing is marked
						active={selectedId ?? ""}
					>
						{top.map((field) => render(field, ""))}
					</TreeView>
				</FeatureFlags>
			</Stack>
		</section>
	);
});
