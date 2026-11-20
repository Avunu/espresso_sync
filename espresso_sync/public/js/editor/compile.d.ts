export type RuleKind = "field" | "collection" | "scalar_collection";
/** A rule: the target field it fills (pointer.ts's form) and the expression that fills it. */
export interface Rule {
    ptr: string;
    kind: RuleKind;
    expr: string;
}
export interface CompileError {
    rule: string;
    code: string;
    message: string;
}
export interface Compiled {
    jsonata: string;
    /** The rules left out, and why. */
    errors: CompileError[];
}
/** The JSONata of `rules`, with the rules it had to leave out. */
export declare function compileRules(rules: readonly unknown[]): Compiled;
