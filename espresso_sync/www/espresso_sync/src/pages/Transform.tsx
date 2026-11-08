// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
	Breadcrumb,
	BreadcrumbItem,
	Button,
	Checkbox,
	CodeSnippet,
	InlineNotification,
	Select,
	SelectItem,
	SkeletonText,
	Stack,
	Tab,
	TabList,
	TabPanel,
	TabPanels,
	Tabs,
	Tag,
	Toggle,
} from "@carbon/react";
import { DataCheck, FunctionMath, Launch, Play, Rocket, Save } from "@carbon/react/icons";
import { useFrappeGetCall, useFrappeGetDoc, useFrappeUpdateDoc } from "frappe-react-sdk";
import { compileRules, type Rule } from "../../../../public/js/editor/compile.ts";
import {
	type Diagnostic,
	mergeDiagnostics,
	type Severity,
} from "../../../../public/js/editor/diagnostics.ts";
import {
	insertSnippet,
	itemsSchema,
	mappingCounts,
	outputDiagnostics,
	requiredUnmapped,
	resultDiagnostics,
	ruleDiagnostics,
	ruleLinks,
	ruleReads,
	sampleItems,
	schemaValidator,
	shownRow,
	simplePath,
	type Snippet,
	sourceContext,
	sourceReference,
	valuesAt,
	withAncestors,
	withoutRepeats,
} from "../../../../public/js/editor/mapping.ts";
import { parentPointer } from "../../../../public/js/editor/pointer.ts";
import {
	fromDocTypeSchema,
	fromOpenApiSchema,
	ruleKind,
	type TreeNode as Field,
	walkTree,
} from "../../../../public/js/editor/schemaTree.ts";
import { inferFromSamples, inferType, toJsonSchema } from "../../../../public/js/editor/typeInfer.ts";
import { useToasts } from "../portal/Toasts";
import type { FrappeEnvelope } from "../portal/types";
import { getErrorMessage, useBackendCall } from "../portal/useBackendCall";
import { deskFormUrl, hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { DiagnosticsTable } from "./DiagnosticsTable";
import { FieldTree, rowId } from "./FieldTree";
import { type Link, MappingLane } from "./MappingLane";
import { TRANSFORM } from "./NewTransform";
import { RuleInspector } from "./RuleInspector";
import { SampleEditor } from "./SampleEditor";
import { SeverityIcon } from "./SeverityIcon";
import { type Setting, settingError, SETTINGS, type Settings, TransformSettings } from "./TransformSettings";
import { Transforms } from "./Transforms";
import { useTransformPreview } from "./useTransformPreview";

/** The fields of a transform the editor reads (JSON fields come as JSON text). */
interface TransformDoc extends Partial<Record<Setting, string | number | null>> {
	name: string;
	direction: "Import" | "Export";
	status: "Draft" | "Active";
	document_type: string;
	api_spec: string;
	method: string;
	path: string;
	rules: string | null;
	sample: string | null;
	diagnostics: string | null;
	compiled_jsonata: string | null;
	active_compiled: string | null;
	modified: string;
}

/** What get_operation_schema answers. */
interface OperationSchema {
	schema: unknown;
	media_type: string | null;
	status: string | null;
}

interface DryRunItem {
	item: number;
	output: unknown;
	name: string | null;
	diagnostics: Diagnostic[];
}

/** The most sample items previewed: as many as the server checks. */
const MAX_ITEMS = 50;
const DENSITY = "espresso_sync.editor.density";
const TABS = ["sample", "output", "jsonata", "diagnostics", "settings"] as const;

function parseJson(text: string | null | undefined): unknown {
	if (!text) return null;
	try {
		return JSON.parse(text) as unknown;
	} catch {
		return null;
	}
}

function rulesOf(doc: TransformDoc): Rule[] {
	const rules = parseJson(doc.rules);
	return Array.isArray(rules) ? (rules as Rule[]) : [];
}

/** The saved sample's text: laid out for reading, unless that would round a number in it. */
function sampleTextOf(doc: TransformDoc): string {
	const sample = parseJson(doc.sample);
	if (sample === null) return "";
	return inferType(sample).unsafeInteger ? (doc.sample ?? "") : JSON.stringify(sample, null, 2);
}

/** A sample's text as compared for changes: its JSON, however it is laid out. */
function sampleKey(text: string | null): string {
	if (!text?.trim()) return "";
	try {
		return JSON.stringify(JSON.parse(text));
	} catch {
		return text;
	}
}

function settingsOf(doc: TransformDoc): Settings {
	const settings = {} as Settings;
	for (const name of SETTINGS) {
		const value = doc[name];
		settings[name] = value === null || value === undefined ? "" : String(value);
	}
	if (!settings.runtime_validation) settings.runtime_validation = "Enforce";
	if (!settings.child_table_policy) settings.child_table_policy = "Replace";
	return settings;
}

/** A short text of a value for a row. */
function brief(value: unknown): string {
	if (typeof value === "string") return JSON.stringify(value.length > 16 ? `${value.slice(0, 16)}…` : value);
	if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "item" : "items"}`;
	if (typeof value === "object" && value !== null) return "{…}";
	return JSON.stringify(value) ?? "";
}

function plural(count: number, one: string, many: string): string {
	return `${count} ${count === 1 ? one : many}`;
}

function isGroup(field: Field): boolean {
	return field.children.length > 0 || (field.variants?.length ?? 0) > 0;
}

/** The groups a tree opens with: those at its top. Deeper ones start closed. */
function topGroups(root: Field): Set<string> {
	const top = root.kind === "collection" ? [root, ...root.children] : root.children;
	return new Set(top.filter(isGroup).map((field) => field.pointer));
}

/** `#/transforms/<name>`: the transform editor; `#/transforms`: the transforms. */
export function Transform({ name }: { name: string | undefined }) {
	return name ? <TransformPage key={name} name={name} /> : <Transforms />;
}

function TransformPage({ name }: { name: string }) {
	const doc = useFrappeGetDoc<TransformDoc>(TRANSFORM, name);
	useSessionRead(doc.data, doc.error);
	const transform = doc.data;
	const importing = transform?.direction === "Import";
	const operation = useFrappeGetCall<FrappeEnvelope<OperationSchema>>(
		"espresso_sync.api.schema.get_operation_schema",
		transform && {
			spec: transform.api_spec,
			method: transform.method,
			path: transform.path,
			part: importing ? "response" : "requestBody",
		},
		transform ? undefined : null,
	);
	const doctype = useFrappeGetCall<FrappeEnvelope<unknown>>(
		"espresso_sync.api.schema.get_doctype_schema",
		transform && { doctype: transform.document_type, mode: importing ? "insert" : "read" },
		transform ? undefined : null,
	);
	useSessionRead(operation.data, operation.error);
	useSessionRead(doctype.data, doctype.error);

	const breadcrumb = (
		<Breadcrumb noTrailingSlash>
			<BreadcrumbItem href={hrefFor("connections")}>Connections</BreadcrumbItem>
			<BreadcrumbItem href={hrefFor("transforms")}>Transforms</BreadcrumbItem>
			<BreadcrumbItem isCurrentPage>{name}</BreadcrumbItem>
		</Breadcrumb>
	);
	const error = doc.error ?? operation.error ?? doctype.error;
	if (error) {
		const missing = doc.error && (doc.error as { httpStatus?: number }).httpStatus === 404;
		return (
			<Stack gap={6}>
				{breadcrumb}
				<InlineNotification
					kind="error"
					lowContrast
					hideCloseButton
					title={missing ? `There is no transform ${name}.` : "The transform couldn't be loaded."}
					subtitle={missing ? "" : getErrorMessage(error, "Reload the page to try again.")}
				/>
			</Stack>
		);
	}
	if (!transform || !operation.data || !doctype.data) {
		return (
			<Stack gap={6}>
				{breadcrumb}
				<SkeletonText heading />
				<SkeletonText paragraph lineCount={8} />
			</Stack>
		);
	}
	return (
		<Stack gap={6}>
			{breadcrumb}
			<Editor
				transform={transform}
				operation={operation.data.message}
				doctype={doctype.data.message}
				onSaved={() => void doc.mutate()}
			/>
		</Stack>
	);
}

interface EditorProps {
	transform: TransformDoc;
	operation: OperationSchema;
	doctype: unknown;
	/** The transform was saved or activated: what the page holds of it is out of date. */
	onSaved: () => void;
}

function Editor({ transform, operation, doctype, onSaved }: EditorProps) {
	const importing = transform.direction === "Import";
	const showToast = useToasts();
	const [saved, setSaved] = useState(transform);
	const [rules, setRules] = useState(() => rulesOf(transform));
	const [sampleText, setSampleText] = useState(() => sampleTextOf(transform));
	const [items, setItems] = useState(() => sampleItems(parseJson(transform.sample)));
	const [sampleError, setSampleError] = useState<string | undefined>();
	const [settings, setSettings] = useState(() => settingsOf(transform));
	const [selected, setSelected] = useState<string | undefined>();
	const [pending, setPending] = useState<string | undefined>();
	const [serverDiagnostics, setServerDiagnostics] = useState<Diagnostic[]>(() => {
		const stored = parseJson(transform.diagnostics);
		return Array.isArray(stored) ? (stored as Diagnostic[]) : [];
	});
	const [dryRun, setDryRun] = useState<DryRunItem[] | undefined>();
	const [compact, setCompact] = useState(() => window.localStorage.getItem(DENSITY) === "compact");
	const [tab, setTab] = useState(0);
	const [shownItem, setShownItem] = useState(0);
	const [sourceFilter, setSourceFilter] = useState("");
	const [targetFilter, setTargetFilter] = useState("");
	const [readOnly, setReadOnly] = useState(false);
	const [requiredOnly, setRequiredOnly] = useState(false);
	const [mappedOnly, setMappedOnly] = useState(false);
	// a row to scroll to and focus, once it is drawn
	const reveal = useRef<string | undefined>(undefined);
	const expression = useRef<HTMLTextAreaElement>(null);
	const caret = useRef<number | undefined>(undefined);

	const update = useFrappeUpdateDoc<Record<string, unknown>>();
	const validate = useBackendCall<Diagnostic[]>(
		"espresso_sync.api.transform.validate_transform",
		"The transform couldn't be checked.",
	);
	const dryRunCall = useBackendCall<DryRunItem[]>(
		"espresso_sync.api.transform.dry_run",
		"The dry run failed.",
	);
	const activate = useBackendCall<{ status: "Draft" | "Active"; active_compiled: string }>(
		"espresso_sync.api.transform.activate_transform",
		"The transform couldn't be activated.",
	);

	// the trees: an import reads the operation's items and fills the DocType; an export the reverse
	const sourceTree = useMemo(() => {
		if (!importing) return fromDocTypeSchema(doctype);
		const tree = fromOpenApiSchema(itemsSchema(operation.schema, settings.items_pointer));
		if (tree.children.length > 0 || tree.kind !== "field") return tree;
		// no schema for the items: the sample's shape stands in
		const inferred = inferFromSamples(items);
		return inferred ? fromOpenApiSchema(toJsonSchema(inferred)) : tree;
	}, [importing, doctype, operation.schema, settings.items_pointer, items]);
	const targetSchema = importing ? doctype : operation.schema;
	const targetTree = useMemo(
		() => (importing ? fromDocTypeSchema(targetSchema) : fromOpenApiSchema(targetSchema ?? {})),
		[importing, targetSchema],
	);
	const validator = useMemo(() => schemaValidator(targetSchema), [targetSchema]);
	const [sourceOpen, setSourceOpen] = useState(() => topGroups(sourceTree));
	const [targetOpen, setTargetOpen] = useState(() => topGroups(targetTree));

	const ruleMap = useMemo(() => new Map(rules.map((rule) => [rule.ptr, rule])), [rules]);
	const compiled = useMemo(() => compileRules(rules), [rules]);
	const previewItems = useMemo(() => items.slice(0, MAX_ITEMS), [items]);
	const preview = useTransformPreview(saved.name, compiled.jsonata, ruleMap, previewItems);

	const targetFields = useMemo(
		() => new Map([...walkTree(targetTree)].map((field) => [field.pointer, field])),
		[targetTree],
	);
	const sourceFields = useMemo(
		() => new Map([...walkTree(sourceTree)].map((field) => [field.pointer, field])),
		[sourceTree],
	);

	// what the browser finds, as the rules change and the preview comes in
	const clientDiagnostics = useMemo(() => {
		const found = ruleDiagnostics(targetTree, ruleMap, compiled);
		for (const rule of rules) {
			const results = preview.results.get(rule.ptr);
			if (results) found.push(...resultDiagnostics(targetFields.get(rule.ptr), rule, results));
		}
		// the server knows which of the schema's findings Frappe takes after all: a DocType's are only warnings here
		const severity = importing ? "warning" : "error";
		found.push(
			...outputDiagnostics(preview.outputs, validator, {
				target: targetTree,
				rules: ruleMap,
				severity,
				placed: found,
			}),
		);
		return found;
	}, [targetTree, ruleMap, compiled, rules, preview, targetFields, validator, importing]);

	const draftState = JSON.stringify([rules, sampleKey(sampleText), settings]);
	const savedState = useMemo(
		() => JSON.stringify([rulesOf(saved), sampleKey(saved.sample), settingsOf(saved)]),
		[saved],
	);
	const dirty = draftState !== savedState;
	// the server's findings are of the saved transform: shown while that is what is edited
	const diagnostics = useMemo(
		() => withoutRepeats(mergeDiagnostics(clientDiagnostics, dirty ? [] : serverDiagnostics, "server")),
		[clientDiagnostics, serverDiagnostics, dirty],
	);
	const byRule = useMemo(() => {
		const map = new Map<string, Diagnostic[]>();
		for (const found of diagnostics) map.set(found.rule, [...(map.get(found.rule) ?? []), found]);
		return map;
	}, [diagnostics]);

	const counts = mappingCounts(targetTree, ruleMap);
	const missing = requiredUnmapped(targetTree, ruleMap);
	const errors = diagnostics.filter((d) => d.severity === "error");
	const warnings = diagnostics.filter((d) => d.severity === "warning");
	const unsafe = useMemo(() => inferType(items).unsafeInteger === true, [items]);
	const blocked =
		sampleError !== undefined
			? "The sample isn't JSON."
			: SETTINGS.map((setting) => settingError(setting, settings[setting])).find(Boolean) &&
				"A setting has an error (see Settings).";

	useEffect(() => {
		if (!dirty) return undefined;
		const warn = (event: BeforeUnloadEvent) => event.preventDefault();
		window.addEventListener("beforeunload", warn);
		return () => window.removeEventListener("beforeunload", warn);
	}, [dirty]);

	useEffect(() => {
		if (reveal.current === undefined) return;
		const row = document.getElementById(rowId("target", reveal.current));
		row?.scrollIntoView({ block: "nearest" });
		row?.focus();
		reveal.current = undefined;
	});

	useEffect(() => {
		// after an insertion, the caret goes back into the expression
		if (caret.current === undefined || !expression.current) return;
		expression.current.focus();
		expression.current.setSelectionRange(caret.current, caret.current);
		caret.current = undefined;
	});

	function setRule(pointer: string, kind: Rule["kind"], text: string) {
		setRules((current) => {
			const at = current.findIndex((rule) => rule.ptr === pointer);
			if (!text.trim()) return current.filter((rule) => rule.ptr !== pointer);
			const rule = { ptr: pointer, kind, expr: text };
			return at === -1 ? [...current, rule] : current.map((other, index) => (index === at ? rule : other));
		});
	}

	function kindAt(pointer: string): Rule["kind"] {
		const field = targetFields.get(pointer);
		return (field && ruleKind(field)) ?? ruleMap.get(pointer)?.kind ?? "field";
	}

	/** Select a target field, opening the groups above it, and put the keyboard on its row. */
	function show(pointer: string) {
		const groups: string[] = [];
		for (let above = parentPointer(pointer); above !== ""; above = parentPointer(above)) groups.push(above);
		setTargetOpen((open) => new Set([...open, ...groups]));
		setSelected(pointer);
		reveal.current = pointer;
	}

	function chooseTarget(field: Field) {
		if (pending === undefined) {
			setSelected(field.pointer);
			return;
		}
		const kind = ruleKind(field);
		const source = sourceFields.get(pending);
		if (!kind) {
			showToast({ kind: "warning", title: `${field.key} is an object: map its fields one by one.` });
			return;
		}
		if (
			kind === "collection" &&
			source &&
			source.kind !== "collection" &&
			source.kind !== "scalar_collection"
		) {
			showToast({ kind: "warning", title: `${field.key} is a list of objects: map a list to it.` });
			return;
		}
		setRule(field.pointer, kind, sourceReference(pending, field.pointer, ruleMap));
		setPending(undefined);
		setSelected(field.pointer);
	}

	function insert(snippet: Snippet) {
		if (selected === undefined) return;
		const text = ruleMap.get(selected)?.expr ?? "";
		const area = expression.current;
		const start = area?.selectionStart ?? text.length;
		const end = area?.selectionEnd ?? text.length;
		const next = insertSnippet(text, start, end, snippet);
		caret.current = next.caret;
		setRule(selected, kindAt(selected), next.expression);
	}

	function changeSample(text: string) {
		setSampleText(text);
		if (!text.trim()) {
			setItems([]);
			setSampleError(undefined);
			return;
		}
		try {
			setItems(sampleItems(JSON.parse(text)));
			setSampleError(undefined);
		} catch (error) {
			setSampleError(error instanceof Error ? error.message : "Not JSON");
		}
	}

	async function check(): Promise<Diagnostic[] | undefined> {
		const result = await validate.call({ name: saved.name });
		if (!result.ok) return undefined;
		setServerDiagnostics(result.data);
		return result.data;
	}

	async function save() {
		const values: Record<string, unknown> = { rules, sample: sampleText.trim() ? sampleText : null };
		for (const name of SETTINGS) {
			// nothing is null: a JSON field's column takes no empty text
			values[name] = name === "max_pages" ? Number(settings[name] || 0) : settings[name] || null;
		}
		let doc: TransformDoc;
		try {
			doc = (await update.updateDoc(TRANSFORM, saved.name, values)) as unknown as TransformDoc;
		} catch (error) {
			showToast({ kind: "error", title: getErrorMessage(error, "The transform couldn't be saved.") });
			return;
		}
		const drafted = saved.status === "Active" && doc.status === "Draft";
		setSaved(doc);
		onSaved();
		showToast(
			drafted
				? { kind: "warning", title: `Saved. ${doc.name} is a Draft again: activate it to run it.` }
				: { kind: "success", title: "Saved." },
		);
		await check();
	}

	async function runValidate() {
		const found = await check();
		if (!found) return;
		const count = found.filter((d) => d.severity === "error").length;
		showToast(
			count
				? { kind: "warning", title: `The server found ${plural(count, "error", "errors")}.` }
				: { kind: "success", title: "The server found no errors." },
		);
	}

	async function runDryRun() {
		const result = await dryRunCall.call({ name: saved.name });
		if (!result.ok) return;
		setDryRun(result.data);
		setTab(TABS.indexOf("output"));
		const failed = result.data.filter((item) => item.diagnostics.some((d) => d.severity === "error")).length;
		showToast(
			failed
				? { kind: "warning", title: `Dry run: ${plural(failed, "item fails", "items fail")}.` }
				: {
						kind: "success",
						title: `Dry run: ${plural(result.data.length, "item maps", "items map")}, and nothing was kept.`,
					},
		);
	}

	async function runActivate() {
		const result = await activate.call({ name: saved.name });
		if (!result.ok) {
			// the refusal lists the errors; the diagnostics show them on their rows
			await check();
			return;
		}
		const doc = { ...saved, status: result.data.status, active_compiled: result.data.active_compiled };
		setSaved(doc);
		onSaved();
		showToast({ kind: "success", title: `${saved.name} is Active: syncs run it.` });
	}

	// rows shown by the filters
	const targetShown = useMemo(() => {
		const text = targetFilter.trim().toLowerCase();
		if (!text && !requiredOnly && !mappedOnly) return undefined;
		const matches = [...targetFields.values()].filter(
			(field) =>
				field.pointer !== "" &&
				(!text || `${field.key} ${field.title ?? ""}`.toLowerCase().includes(text)) &&
				(!requiredOnly || field.required === "hard") &&
				(!mappedOnly || ruleMap.has(field.pointer)),
		);
		return withAncestors(matches.map((field) => field.pointer));
	}, [targetFilter, requiredOnly, mappedOnly, targetFields, ruleMap]);

	// the source fields each rule reads, and the lines between them
	const reads = useMemo(() => ruleReads(ruleMap), [ruleMap]);
	const readFields = useMemo(() => new Set([...reads.values()].flat()), [reads]);
	const sourceShown = useMemo(() => {
		const text = sourceFilter.trim().toLowerCase();
		if (!text && !readOnly) return undefined;
		const matches = [...sourceFields.values()].filter(
			(field) =>
				field.pointer !== "" &&
				(!text || `${field.key} ${field.title ?? ""}`.toLowerCase().includes(text)) &&
				(!readOnly || readFields.has(field.pointer)),
		);
		return withAncestors(matches.map((field) => field.pointer));
	}, [sourceFilter, readOnly, sourceFields, readFields]);

	const links = useMemo(() => {
		const sourcePointers = new Set(sourceFields.keys());
		const targetPointers = new Set(targetFields.keys());
		const lines = ruleLinks(
			ruleMap,
			reads,
			(pointer) => shownRow(pointer, sourcePointers, sourceShown ? sourcePointers : sourceOpen),
			(pointer) => shownRow(pointer, targetPointers, targetShown ? targetPointers : targetOpen),
		);
		return lines.map((line): Link => ({
			source: rowId("source", line.source),
			target: rowId("target", line.target),
			kind: line.kind,
			hot:
				selected !== undefined &&
				line.rules.some((rule) => rule === selected || rule.startsWith(`${selected}/`)),
			error: line.rules.some((rule) => (byRule.get(rule) ?? []).some((d) => d.severity === "error")),
		}));
	}, [
		ruleMap,
		reads,
		sourceFields,
		targetFields,
		targetShown,
		sourceShown,
		targetOpen,
		sourceOpen,
		selected,
		byRule,
	]);

	function targetDetails(field: Field): ReactNode {
		const rule = ruleMap.get(field.pointer);
		const found = byRule.get(field.pointer) ?? [];
		const worst: Severity | "ok" | undefined = found.some((d) => d.severity === "error")
			? "error"
			: found.some((d) => d.severity === "warning")
				? "warning"
				: rule
					? "ok"
					: undefined;
		const values = preview.results.get(field.pointer)?.values.filter((value) => value.defined) ?? [];
		const [first] = values;
		return (
			<>
				{field.required === "hard" && (
					<span title="Required" style={{ color: "var(--cds-text-error)" }}>
						{" *"}
						<span className="cds--visually-hidden">required</span>
					</span>
				)}
				{rule && !simplePath(rule.expr) && rule.kind === "field" && (
					<FunctionMath
						aria-label="formula"
						style={{ marginInlineStart: "0.5rem", verticalAlign: "middle" }}
					/>
				)}
				{worst && (
					<span style={{ marginInlineStart: "0.5rem", verticalAlign: "middle" }}>
						<SeverityIcon severity={worst} />
						<span className="cds--visually-hidden">{worst === "ok" ? "mapped" : worst}</span>
					</span>
				)}
				{first && (
					<span
						style={{
							marginInlineStart: "0.75rem",
							color: "var(--cds-text-secondary)",
							fontFamily: "var(--cds-code-01-font-family)",
						}}
					>
						{field.kind === "collection" ? plural(values.length, "item", "items") : brief(first.value)}
						{field.kind !== "collection" && values.length > 1 ? ` +${values.length - 1}` : ""}
					</span>
				)}
			</>
		);
	}

	function sourceDetails(field: Field): ReactNode {
		const first = items[0];
		if (first === undefined || isGroup(field)) return null;
		const values = valuesAt(first, field.pointer);
		if (values.length === 0) return null;
		return (
			<span
				style={{
					marginInlineStart: "0.75rem",
					color: "var(--cds-text-secondary)",
					fontFamily: "var(--cds-code-01-font-family)",
				}}
			>
				{brief(values[0])}
				{values.length > 1 ? ` +${values.length - 1}` : ""}
			</span>
		);
	}

	const size = compact ? "xs" : "sm";
	const selectedField = selected === undefined ? undefined : targetFields.get(selected);
	const selectedRule = selected === undefined ? undefined : ruleMap.get(selected);
	const sourceList = useMemo(
		() =>
			[...sourceFields.values()]
				.filter((field) => field.pointer !== "")
				.map((field) => ({
					pointer: field.pointer,
					text: selected === undefined ? field.pointer : sourceReference(field.pointer, selected, ruleMap),
				})),
		[sourceFields, selected, ruleMap],
	);
	const output = preview.outputs[shownItem];
	const dryItem = dryRun?.find((entry) => entry.item === shownItem);
	const operationLabel = `${saved.method} ${saved.path}`;

	return (
		<Stack gap={6}>
			<div
				style={{
					display: "flex",
					flexWrap: "wrap",
					gap: "1rem",
					alignItems: "baseline",
					justifyContent: "space-between",
				}}
			>
				<div>
					<h1>
						{saved.name} <Tag type={saved.status === "Active" ? "green" : "gray"}>{saved.status}</Tag>
					</h1>
					<p>
						{importing
							? `Imports the items of ${operationLabel} (${saved.api_spec}) as ${saved.document_type} documents.`
							: `Exports ${saved.document_type} documents as the request body of ${operationLabel} (${saved.api_spec}).`}
					</p>
				</div>
				<div>
					<Button kind="ghost" href={deskFormUrl(TRANSFORM, saved.name)} renderIcon={Launch}>
						Open in the desk
					</Button>
					<Button
						kind="tertiary"
						renderIcon={DataCheck}
						disabled={dirty || validate.loading}
						onClick={() => void runValidate()}
					>
						Validate
					</Button>
					<Button
						kind="tertiary"
						renderIcon={Play}
						disabled={dirty || dryRunCall.loading}
						onClick={() => void runDryRun()}
					>
						Dry run
					</Button>
					<Button
						kind="secondary"
						renderIcon={Rocket}
						disabled={dirty || activate.loading}
						onClick={() => void runActivate()}
					>
						Activate
					</Button>
					<Button
						kind="primary"
						renderIcon={Save}
						disabled={!dirty || update.loading || Boolean(blocked)}
						onClick={() => void save()}
					>
						Save
					</Button>
				</div>
			</div>

			<div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem 1.5rem", alignItems: "center" }}>
				<output>
					<strong>{counts.mapped}</strong> of {plural(counts.total, "field", "fields")} mapped
				</output>
				{missing.length > 0 && (
					<Button kind="ghost" size="sm" onClick={() => missing[0] && show(missing[0].pointer)}>
						<SeverityIcon severity="error" />
						&nbsp;{plural(missing.length, "required field unmapped", "required fields unmapped")}
					</Button>
				)}
				{errors.length > 0 && (
					<Button kind="ghost" size="sm" onClick={() => setTab(TABS.indexOf("diagnostics"))}>
						<SeverityIcon severity="error" />
						&nbsp;{plural(errors.length, "error", "errors")}
					</Button>
				)}
				{warnings.length > 0 && (
					<Button kind="ghost" size="sm" onClick={() => setTab(TABS.indexOf("diagnostics"))}>
						<SeverityIcon severity="warning" />
						&nbsp;{plural(warnings.length, "warning", "warnings")}
					</Button>
				)}
				{dirty && (
					<span>
						Unsaved changes{blocked ? `: ${blocked}` : ""}. Validate, Dry run and Activate check the saved
						transform.
					</span>
				)}
				<div style={{ marginInlineStart: "auto" }}>
					<Toggle
						id="transform-density"
						size="sm"
						labelText="Row height"
						labelA="Comfortable"
						labelB="Compact"
						toggled={compact}
						onToggle={(on: boolean) => {
							setCompact(on);
							window.localStorage.setItem(DENSITY, on ? "compact" : "comfortable");
						}}
					/>
				</div>
			</div>

			{saved.status === "Active" && (
				<InlineNotification
					kind="info"
					lowContrast
					hideCloseButton
					title="This transform is Active."
					subtitle={`Syncs run its rules as they were when it was activated${
						saved.compiled_jsonata === saved.active_compiled ? "" : " (the saved rules have changed since)"
					}: saving changed rules doesn't change what runs until you activate it again. Saving a change to a setting makes it a Draft again, and it stops running until you activate it.`}
				/>
			)}

			{pending !== undefined && (
				<div
					style={{
						display: "flex",
						flexWrap: "wrap",
						gap: "0.5rem 1rem",
						alignItems: "center",
						padding: "0.5rem 1rem",
						background: "var(--cds-layer-accent)",
					}}
				>
					<output>
						Mapping from <code>{pending}</code>: choose a target field, or
					</output>
					{selected !== undefined && selectedField && ruleKind(selectedField) && (
						<Button
							kind="tertiary"
							size="sm"
							onClick={() => {
								insert({ before: sourceReference(pending, selected, ruleMap), after: "" });
								setPending(undefined);
							}}
						>
							Insert into the {selectedField.key || "body"} rule
						</Button>
					)}
					<Button kind="ghost" size="sm" onClick={() => setPending(undefined)}>
						Cancel
					</Button>
				</div>
			)}

			<div
				id="transform-editor"
				aria-busy={preview.busy}
				style={{
					display: "grid",
					gridTemplateColumns: "minmax(0, 1fr) 4rem minmax(0, 1fr) minmax(18rem, 26rem)",
					alignItems: "start",
				}}
			>
				<FieldTree
					side="source"
					heading="Source"
					description={
						importing ? `${operationLabel}: an item of the response` : `${saved.document_type} documents`
					}
					filter={sourceFilter}
					onFilter={setSourceFilter}
					toggles={
						<Checkbox
							id="source-read"
							labelText="Read by a rule only"
							checked={readOnly}
							onChange={(_event, { checked }) => setReadOnly(checked)}
						/>
					}
					root={sourceTree}
					size={size}
					shown={sourceShown}
					expanded={sourceOpen}
					onExpand={setSourceOpen}
					selected={pending}
					onSelect={(field) =>
						setPending((current) => (current === field.pointer ? undefined : field.pointer))
					}
					details={sourceDetails}
				/>
				<div style={{ alignSelf: "stretch" }}>
					<MappingLane links={links} selected={selected !== undefined} />
				</div>
				<FieldTree
					side="target"
					heading="Target"
					description={
						importing ? `${saved.document_type}: a new document` : `${operationLabel}: the request body`
					}
					filter={targetFilter}
					onFilter={setTargetFilter}
					toggles={
						<div style={{ display: "flex", flexWrap: "wrap", gap: "0 1rem" }}>
							<Checkbox
								id="target-required"
								labelText="Required only"
								checked={requiredOnly}
								onChange={(_event, { checked }) => setRequiredOnly(checked)}
							/>
							<Checkbox
								id="target-mapped"
								labelText="Mapped only"
								checked={mappedOnly}
								onChange={(_event, { checked }) => setMappedOnly(checked)}
							/>
						</div>
					}
					root={targetTree}
					size={size}
					shown={targetShown}
					expanded={targetOpen}
					onExpand={setTargetOpen}
					selected={selected}
					onSelect={chooseTarget}
					details={targetDetails}
				/>
				<aside
					aria-label="Rule"
					style={{
						position: "sticky",
						top: "4rem",
						marginInlineStart: "1rem",
						padding: "1rem",
						background: "var(--cds-layer)",
						maxHeight: "calc(100vh - 5rem)",
						overflowY: "auto",
					}}
				>
					{selected === undefined ? (
						<p>
							Select a target field to write its rule. To map a source field to it, select the source field
							first.
						</p>
					) : (
						<RuleInspector
							pointer={selected}
							field={selectedField ?? (selected === "" ? targetTree : undefined)}
							rule={selectedRule}
							context={sourceContext(selected, ruleMap)}
							results={preview.results.get(selected)}
							diagnostics={byRule.get(selected) ?? []}
							items={previewItems.length}
							reads={reads.get(selected) ?? []}
							sources={sourceList}
							members={(selectedField?.children ?? []).map((field) => ({
								field,
								rule: ruleMap.get(field.pointer),
							}))}
							isList={(pointer) => targetFields.get(pointer)?.kind === "collection"}
							expressionRef={expression}
							onChange={(text) => setRule(selected, kindAt(selected), text)}
							onInsert={insert}
							onSelect={show}
						/>
					)}
				</aside>
			</div>

			<Tabs selectedIndex={tab} onChange={({ selectedIndex }) => setTab(selectedIndex)}>
				<TabList aria-label="The transform's sample, output and settings">
					<Tab>Sample</Tab>
					<Tab>Output</Tab>
					<Tab>JSONata</Tab>
					<Tab>{`Diagnostics (${diagnostics.length})`}</Tab>
					<Tab>Settings</Tab>
				</TabList>
				<TabPanels>
					<TabPanel>
						<SampleEditor
							transform={saved.name}
							importing={importing}
							text={sampleText}
							error={sampleError}
							items={items.length}
							unsafe={unsafe}
							onChange={changeSample}
						/>
					</TabPanel>
					<TabPanel>
						<Stack gap={5}>
							{previewItems.length === 0 ? (
								<p>Add a sample to see what the transform maps it to.</p>
							) : (
								<Select
									id="transform-output-item"
									labelText="Sample item"
									value={String(shownItem)}
									onChange={(event) => setShownItem(Number(event.target.value))}
								>
									{previewItems
										.map((_item, index) => String(index))
										.map((value) => (
											<SelectItem key={value} value={value} text={`Item ${Number(value) + 1}`} />
										))}
								</Select>
							)}
							{output && (
								<div>
									<h3 className="cds--label">
										{importing
											? "The document it maps to (preview)"
											: "The request body it maps to (preview)"}
									</h3>
									{output.ok ? (
										<CodeSnippet type="multi" feedback="Copied" wrapText>
											{output.defined ? JSON.stringify(output.value, null, 2) : "(nothing)"}
										</CodeSnippet>
									) : (
										<InlineNotification
											kind="error"
											lowContrast
											hideCloseButton
											title={output.error.message}
											subtitle={output.error.code}
										/>
									)}
								</div>
							)}
							{dryItem && (
								<div>
									<h3 className="cds--label">
										Dry run on the server
										{dryItem.name ? `: inserted as ${dryItem.name}, then rolled back` : ""}{" "}
										{output?.ok && (
											<Tag
												size="sm"
												type={
													JSON.stringify(output.value) === JSON.stringify(dryItem.output) ? "green" : "red"
												}
											>
												{JSON.stringify(output.value) === JSON.stringify(dryItem.output)
													? "Same as the preview"
													: "Differs from the preview"}
											</Tag>
										)}
									</h3>
									<CodeSnippet type="multi" feedback="Copied" wrapText>
										{JSON.stringify(dryItem.output, null, 2)}
									</CodeSnippet>
									{dryItem.diagnostics.map((found) => (
										<InlineNotification
											key={`${found.code} ${found.path}`}
											kind={found.severity === "info" ? "info" : found.severity}
											lowContrast
											hideCloseButton
											title={found.message}
											subtitle={`${found.rule || found.path || "(the whole object)"} · ${found.code}`}
										/>
									))}
								</div>
							)}
						</Stack>
					</TabPanel>
					<TabPanel>
						<Stack gap={3}>
							<p>
								The rules compiled to the one expression a sync runs. The server compiles them to the same
								text when the transform is saved.
							</p>
							<CodeSnippet type="multi" feedback="Copied" wrapText>
								{compiled.jsonata}
							</CodeSnippet>
						</Stack>
					</TabPanel>
					<TabPanel>
						<DiagnosticsTable
							diagnostics={diagnostics}
							current={!dirty}
							onShow={(found) => {
								if (found.rule === "" || found.rule.startsWith("/")) {
									show(found.rule);
									return;
								}
								// a setting's expression
								setTab(TABS.indexOf("settings"));
								window.setTimeout(() => document.getElementById(`setting-${found.rule}`)?.focus(), 0);
							}}
						/>
					</TabPanel>
					<TabPanel>
						<TransformSettings
							importing={importing}
							settings={settings}
							onChange={(name, value) => setSettings((current) => ({ ...current, [name]: value }))}
						/>
					</TabPanel>
				</TabPanels>
			</Tabs>
		</Stack>
	);
}
