/**
 * The transform editor's rules, read against its two trees.
 *
 * - Where a rule is evaluated: a rule under a `collection` rule runs on each
 *   item that rule gives, so `collectionChain` and `sourceContext` say which
 *   items, and `sourceReference` writes a source field as the rule must read it
 *   there (`sku` on a line item, `$$.currency` from the document's root).
 * - What each rule gives on a sample item: `probeExpression` wraps a rule in
 *   the collections above it as `{"i": [(collection).{"v": (rule)}]}`, so every
 *   value keeps the index of the item it came from, and `probeValues` reads
 *   them back. `probesExpression` asks for every rule at once.
 * - What the editor shows before anything is saved: the required fields no
 *   rule fills (as the server's validate.required_diagnostics finds them), how
 *   many fields are mapped, and the findings of the rules themselves.
 */
import { type ValidateFunction } from "ajv/dist/2020.js";
import type { Compiled, Rule } from "./compile.ts";
import { type Diagnostic, type Severity } from "./diagnostics.ts";
import type { EvalError, EvalResponse } from "./evalWorker.ts";
import { type TreeNode } from "./schemaTree.ts";
import { type Compatibility } from "./typeInfer.ts";
/** The rules, by the pointer of the field each fills. */
export type Rules = ReadonlyMap<string, Rule>;
/** A sample's items: a list, or one item (as the server's get_sample reads it). */
export declare function sampleItems(sample: unknown): unknown[];
/** A path an expression is, and nothing more: from the context (`a.b`, `$`), or from the root (`$$.a`). */
export interface SimplePath {
    absolute: boolean;
    segments: string[];
}
/** The path `expression` is, when it is only a path of field names; undefined for anything else. */
export declare function simplePath(expression: string): SimplePath | undefined;
/** Field names as a JSONata path: `customer.first_name`, with `` `odd name` `` quoted. */
export declare function pathExpression(segments: readonly string[]): string;
/** The `collection` rules above `pointer` (not its own), outermost first: what its rule runs on. */
export declare function collectionChain(pointer: string, rules: Rules): Rule[];
/**
 * The source path of the items a rule at `pointer` runs on: `[]` for the
 * source item itself, `["line_items"]` under a collection that reads
 * `line_items`. Undefined when a collection above it is more than a path.
 */
export declare function sourceContext(pointer: string, rules: Rules): string[] | undefined;
/** How a rule at `targetPointer` reads the source field at `sourcePointer`. */
export declare function sourceReference(sourcePointer: string, targetPointer: string, rules: Rules): string;
/** One value a rule gave: `at` is the index of each collection item above it. */
export interface ProbeValue {
    at: number[];
    value: unknown;
    /** False when the rule gave nothing there (JSONata's undefined: the key is left out). */
    defined: boolean;
}
/**
 * The expression that gives a rule's values on a source item: its own value
 * when no collection is above it, else `{"i": [(collection).{"v": (rule)}]}`,
 * a level for each collection, as the compiled transform evaluates it.
 */
export declare function probeExpression(rule: Rule, rules: Rules): string;
/** One expression giving every rule's probe, keyed by its pointer. */
export declare function probesExpression(list: readonly Rule[], rules: Rules): string;
/** The values in a probe's result, `depth` being how many collections are above the rule. */
export declare function probeValues(result: unknown, defined: boolean, depth: number): ProbeValue[];
/** Whether values a rule gave fit the target field (a collection's items are checked by their own rules). */
export declare function valueCompatibility(node: TreeNode, values: readonly unknown[]): Compatibility;
/** Every value at `pointer` in `item`, with collection items implied (as a source tree's pointers are). */
export declare function valuesAt(item: unknown, pointer: string): unknown[];
/**
 * The schema of one item of a response, as an import reads its items: the
 * schema at the Items Pointer, and its items when that is an array (the
 * server's read_items). `{}` when the pointer leads nowhere in the schema.
 */
export declare function itemsSchema(schema: unknown, itemsPointer: string): unknown;
/**
 * The required fields of `target` no rule fills: at its root, in the objects
 * rules fill field by field, and in the items of the mapped collections.
 */
export declare function requiredUnmapped(target: TreeNode, rules: Rules): TreeNode[];
/** The fields a rule can fill: the mappable nodes, and the root when it is a collection. */
export declare function targetFields(target: TreeNode): TreeNode[];
/** How many of the target's fields have a rule, of how many. */
export declare function mappingCounts(target: TreeNode, rules: Rules): {
    mapped: number;
    total: number;
};
/** The syntax error of an expression, if it has one. */
export declare function syntaxError(expression: string): EvalError | undefined;
/**
 * What the rules show without a sample, as the server's static checks find it:
 * the rules that don't compile, the expressions that don't parse, the required
 * fields no rule fills, and the rules for a field the target doesn't have.
 */
export declare function ruleDiagnostics(target: TreeNode, rules: Rules, compiled: Compiled): Diagnostic[];
/** A rule's results on the sample: its values, and the error it stopped with on each item it failed on. */
export interface RuleResults {
    values: ProbeValue[];
    /** The values by sample item. */
    byItem: ProbeValue[][];
    errors: {
        item: number;
        error: EvalError;
    }[];
}
/** What a rule's probe gave on one item: its result, or the error it stopped with. */
export type ProbeAnswer = {
    ok: true;
    value: unknown;
    defined: boolean;
} | {
    ok: false;
    error: EvalError;
};
/** A rule's answer out of `probesExpression`'s result on an item, when that evaluation succeeded. */
export declare function answerOf(combined: EvalResponse | undefined, pointer: string): ProbeAnswer | undefined;
/** A rule's results from its answers, one per sample item. */
export declare function ruleResults(rule: Rule, rules: Rules, answers: readonly ProbeAnswer[]): RuleResults;
/** What a rule's results show: the items it failed on, and values that don't fit the field. */
export declare function resultDiagnostics(node: TreeNode | undefined, rule: Rule, results: RuleResults): Diagnostic[];
/**
 * A JSON Schema validator for the objects the transform maps to, or undefined
 * when the schema can't be compiled. Formats are left to the server, which
 * knows what Frappe parses; a `$schema` naming OpenAPI's dialect, which ajv
 * doesn't know, is dropped.
 */
export declare function schemaValidator(schema: unknown): ValidateFunction | undefined;
/** A diagnostic as the editor lists it, with the sample items it was found on (none when it isn't about one). */
export interface Finding extends Diagnostic {
    items: number[];
}
/**
 * The diagnostics as the editor lists them: one for each rule, path, code and
 * sample item, the first of any the browser and the server both found; and of
 * those, the ones that differ only in their item as one finding, with its
 * items. A rule that fails on the whole sample is then one finding, not one an
 * item.
 */
export declare function withoutRepeats(diagnostics: readonly Diagnostic[]): Finding[];
/** Sample items as people count them, runs as ranges: [0, 3, 4, 5] is "1, 4–6". */
export declare function itemRanges(items: readonly number[]): string;
/** Text to insert into an expression: the caret (or the selection, wrapped) goes between `before` and `after`. */
export interface Snippet {
    before: string;
    after: string;
}
/**
 * `expression` with `snippet` put in place of the text from `start` to `end`,
 * that text wrapped in it (selecting `price` and inserting `$number(…)` gives
 * `$number(price)`), and where the caret goes: inside the snippet's hole, or
 * after what it wrapped.
 */
export declare function insertSnippet(expression: string, start: number, end: number, snippet: Snippet): {
    expression: string;
    caret: number;
};
/** The pointers given and every pointer above each: the rows a filtered tree shows. */
export declare function withAncestors(pointers: Iterable<string>): Set<string>;
/**
 * The row that shows the field at `pointer` (or the nearest field above it) in
 * a tree of `fields` whose open groups are `expanded`: its own row, or that of
 * the closed group it is in. Undefined when no field of the tree holds it.
 */
export declare function shownRow(pointer: string, fields: ReadonlySet<string>, expanded: ReadonlySet<string>): string | undefined;
/**
 * The source fields each rule reads, by the rule's pointer: a wildcard's read
 * stops at the field above it. A rule under a collection that is more than a
 * path reads from items the editor can't place, and is left out.
 */
export declare function ruleReads(rules: Rules): Map<string, string[]>;
/** A line between the trees: from a source row to a target row, for the rules it stands for. */
export interface RuleLink {
    source: string;
    target: string;
    /** A collection rule's line, a path's, or a formula's (the first rule's, when several share it). */
    kind: "path" | "formula" | "collection";
    rules: string[];
}
/**
 * The lines from the row of each field a rule reads to the row of the field it
 * fills, a row being the field's own or that of the closed group holding it
 * (`sourceRow`, `targetRow`: undefined when the field isn't shown).
 */
export declare function ruleLinks(rules: Rules, reads: ReadonlyMap<string, readonly string[]>, sourceRow: (pointer: string) => string | undefined, targetRow: (pointer: string) => string | undefined): RuleLink[];
/**
 * What the compiled transform's results show, one per sample item: the error
 * an item stopped with (unless a rule's own results already place it), and
 * what the target's schema finds in what it maps to, at `severity`.
 */
export declare function outputDiagnostics(outputs: readonly EvalResponse[], validate: ValidateFunction | undefined, options: {
    target: TreeNode;
    rules: Rules;
    severity: Severity;
    placed: readonly Diagnostic[];
}): Diagnostic[];
