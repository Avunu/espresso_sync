export type NodeKind = "object" | "collection" | "scalar_collection" | "field" | "map" | "variants" | "cycle";
export type RequiredTier = "hard" | "server" | null;
/** What doctype_json_schema says about a DocType field (its `x-frappe`). */
export interface FrappeFieldInfo {
    fieldtype: string | undefined;
    options: string | undefined;
    /** The DocType a Link points to. */
    link: string | undefined;
    /** For a Dynamic Link: the field that holds the DocType. */
    dynamicLink: string | undefined;
    custom: boolean;
}
export interface Variant {
    label: string;
    node: TreeNode;
}
export interface TreeNode {
    /** The property name; `""` for the root. */
    key: string;
    pointer: string;
    kind: NodeKind;
    /** The JSON types the value may have (`[]`: anything). A collection's is `["array"]`. */
    types: string[];
    nullable: boolean;
    required: RequiredTier;
    readOnly: boolean;
    title?: string;
    description?: string;
    format?: string;
    enum?: unknown[];
    /** Object and collection: the fields (for a collection, of each item). */
    children: TreeNode[];
    /** Whether an object (or a collection's items) takes keys beyond `children`. */
    open: boolean;
    /** A variant group: the shapes the value (or each item) may take. */
    variants?: Variant[];
    variantMode?: "oneOf" | "anyOf";
    /** A scalar collection's item types, or a map's value types. */
    itemTypes?: string[];
    /** A cycle node: the schema it would have expanded again. */
    cycle?: string;
    frappe?: FrappeFieldInfo;
}
export interface OpenApiOptions {
    /** The whole OpenAPI document, for `$ref`s the schema still carries (`#/components/schemas/…`). */
    document?: unknown;
}
/** The tree of an OpenAPI operation's body schema (OAS 3.1, or 3.0's `nullable`). */
export declare function fromOpenApiSchema(schema: unknown, options?: OpenApiOptions): TreeNode;
/** The tree of a DocType, from doctype_json_schema (child tables are collections). */
export declare function fromDocTypeSchema(schema: unknown): TreeNode;
/** Every node under (and including) `root`, depth first; a variant's nodes come after their group. */
export declare function walkTree(root: TreeNode): Generator<TreeNode>;
/** The node at a pointer (the first one, if variants repeat it). */
export declare function findNode(root: TreeNode, pointer: string): TreeNode | undefined;
/** The kind of rule that fills a node, or undefined for a node a rule can't target. */
export declare function ruleKind(node: TreeNode): "field" | "collection" | "scalar_collection" | undefined;
/** The nodes a rule can fill: leaves, scalar collections and collections (not the root). */
export declare function mappableNodes(root: TreeNode): TreeNode[];
