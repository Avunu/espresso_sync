// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { NumberInput, Select, SelectItem, Stack, TextArea, TextInput } from "@carbon/react";
import { syntaxError } from "../../../../public/js/editor/mapping.ts";

/** The fields of a transform a sync reads besides its rules, as the editor edits them: text. */
export const SETTINGS = [
	"items_pointer",
	"path_params",
	"query_params",
	"next_request_expr",
	"max_pages",
	"external_id_expr",
	"modified_expr",
	"runtime_validation",
	"child_table_policy",
	"child_table_keys",
] as const;

export type Setting = (typeof SETTINGS)[number];
export type Settings = Record<Setting, string>;

/** Why a setting can't be saved as it is, if it can't. */
export function settingError(name: Setting, value: string): string | undefined {
	if (name === "items_pointer") {
		return value === "" || value.startsWith("/") ? undefined : "A JSON Pointer starts with /";
	}
	if (name === "child_table_keys") {
		if (!value.trim()) return undefined;
		try {
			const keys: unknown = JSON.parse(value);
			return typeof keys === "object" && keys !== null && !Array.isArray(keys)
				? undefined
				: 'An object of table and key: {"items": "item_code"}';
		} catch {
			return "Not JSON";
		}
	}
	if (name.endsWith("_params") || name.endsWith("_expr")) {
		const error = value.trim() ? syntaxError(value) : undefined;
		return error && `${error.message} (${error.code})`;
	}
	return undefined;
}

interface ExpressionProps {
	name: Setting;
	label: string;
	help: string;
	settings: Settings;
	onChange: (name: Setting, value: string) => void;
}

function Expression({ name, label, help, settings, onChange }: ExpressionProps) {
	const error = settingError(name, settings[name]);
	return (
		<TextArea
			id={`setting-${name}`}
			labelText={label}
			helperText={help}
			rows={2}
			spellCheck={false}
			value={settings[name]}
			invalid={error !== undefined}
			invalidText={error}
			style={{ fontFamily: "var(--cds-code-02-font-family)" }}
			onChange={(event) => onChange(name, event.target.value)}
		/>
	);
}

interface TransformSettingsProps {
	importing: boolean;
	settings: Settings;
	onChange: (name: Setting, value: string) => void;
}

/**
 * What a sync reads besides the rules: where the items are, the request's
 * parameters, the pages, the ids and the checks. Saved with the rules.
 */
export function TransformSettings({ importing, settings, onChange }: TransformSettingsProps) {
	const field = { settings, onChange };
	return (
		<Stack gap={6}>
			{importing && (
				<TextInput
					id="setting-items_pointer"
					labelText="Items Pointer"
					helperText="Where the items are in the response, as a JSON Pointer (/data). Empty: the response is the item, or the list of items. The source fields are an item's."
					value={settings.items_pointer}
					invalid={settingError("items_pointer", settings.items_pointer) !== undefined}
					invalidText={settingError("items_pointer", settings.items_pointer)}
					onChange={(event) => onChange("items_pointer", event.target.value)}
				/>
			)}
			<Expression
				name="external_id_expr"
				label="External ID"
				help={
					importing
						? "The item's id in the API (required): what a later sync finds its document by."
						: "The id in the API, read from a create's response."
				}
				{...field}
			/>
			{importing && (
				<Expression
					name="modified_expr"
					label="Modified"
					help="When the item last changed: an item no newer than its last import is skipped."
					{...field}
				/>
			)}
			<Expression
				name="path_params"
				label="Path Parameters"
				help={`An object of the path's parameters: {"id": $syncId("Customer", customer)}. ${
					importing ? 'Evaluated on {"last_import"}.' : "Evaluated on the document."
				}`}
				{...field}
			/>
			<Expression
				name="query_params"
				label="Query Parameters"
				help='An object of the query parameters: {"updated_since": last_import}.'
				{...field}
			/>
			{importing && (
				<>
					<Expression
						name="next_request_expr"
						label="Next Request"
						help={`Evaluated on the last page ({body, headers, query}): the next page's query parameters ({"page": query.page + 1}), or nothing after the last page.`}
						{...field}
					/>
					<NumberInput
						id="setting-max_pages"
						label="Maximum Pages"
						helperText="The most pages one sync reads."
						min={0}
						value={settings.max_pages}
						onChange={(_event, { value }) => onChange("max_pages", String(value))}
					/>
				</>
			)}
			<Select
				id="setting-runtime_validation"
				labelText="Runtime Validation"
				helperText="Enforce: an object that fails the target's schema is not saved or sent. Warn: it is, and the findings are logged. Off: nothing is checked."
				value={settings.runtime_validation}
				onChange={(event) => onChange("runtime_validation", event.target.value)}
			>
				{["Enforce", "Warn", "Off"].map((option) => (
					<SelectItem key={option} value={option} text={option} />
				))}
			</Select>
			{importing && (
				<>
					<Select
						id="setting-child_table_policy"
						labelText="Child Tables"
						helperText="On an update, Replace sets each mapped child table to the mapped rows; Merge by Key updates the rows with the same key and adds the others."
						value={settings.child_table_policy}
						onChange={(event) => onChange("child_table_policy", event.target.value)}
					>
						{["Replace", "Merge by Key"].map((option) => (
							<SelectItem key={option} value={option} text={option} />
						))}
					</Select>
					{settings.child_table_policy === "Merge by Key" && (
						<TextArea
							id="setting-child_table_keys"
							labelText="Child Table Keys"
							helperText={`For each child table, the JSONata giving a row's key: {"items": "item_code"}.`}
							rows={3}
							spellCheck={false}
							value={settings.child_table_keys}
							invalid={settingError("child_table_keys", settings.child_table_keys) !== undefined}
							invalidText={settingError("child_table_keys", settings.child_table_keys)}
							style={{ fontFamily: "var(--cds-code-02-font-family)" }}
							onChange={(event) => onChange("child_table_keys", event.target.value)}
						/>
					)}
				</>
			)}
		</Stack>
	);
}
