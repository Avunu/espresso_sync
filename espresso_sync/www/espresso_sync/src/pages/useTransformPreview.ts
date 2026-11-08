// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect, useRef, useState } from "react";
import type { Rule } from "../../../../public/js/editor/compile.ts";
import {
	type EvalCall,
	EvalClient,
	type EvalResponse,
	evaluateAll,
	type FunctionCall,
	type FunctionResult,
	type FunctionResults,
} from "../../../../public/js/editor/evalWorker.ts";
import {
	answerOf,
	type ProbeAnswer,
	probeExpression,
	probesExpression,
	type RuleResults,
	ruleResults,
	type Rules,
	syntaxError,
} from "../../../../public/js/editor/mapping.ts";
import { useBackendCall } from "../portal/useBackendCall";

export interface Preview {
	/** What the compiled transform maps each sample item to: as the server's dry run maps it. */
	outputs: EvalResponse[];
	/** Each rule's values and errors on the sample, by pointer. */
	results: Map<string, RuleResults>;
	/** Whether an evaluation is running: the preview is of rules as they were. */
	busy: boolean;
}

// busy from the start: the first evaluation starts as the page opens
const STARTING: Preview = { outputs: [], results: new Map(), busy: true };

/**
 * The transform evaluated on its sample in the browser, in a Web Worker
 * (evalWorker.ts), with the app's functions answered by the server.
 * Each item gets two evaluations: the compiled transform, and every rule's
 * probe at once; an item whose probes fail is probed rule by rule, to find
 * which rules fail. A change of rules or sample starts over, and what an older
 * evaluation finds is dropped.
 */
export function useTransformPreview(
	transform: string,
	jsonata: string,
	rules: Rules,
	items: readonly unknown[],
): Preview {
	const client = useRef<EvalClient | undefined>(undefined);
	// the server's answers to the app's functions, kept while the page is open
	const answers = useRef<FunctionResults>({});
	const [preview, setPreview] = useState<Preview>(STARTING);
	const { call } = useBackendCall<FunctionResult[]>(
		"espresso_sync.api.transform.resolve_functions",
		"The functions in the rules couldn't be evaluated.",
	);

	useEffect(() => {
		const url = window.portal_boot?.eval_worker ?? "";
		const created = new EvalClient(() => new Worker(url));
		client.current = created;
		return () => {
			created.dispose();
			client.current = undefined;
		};
	}, []);

	useEffect(() => {
		const engine = client.current;
		if (!engine) return undefined;
		let stale = false;
		const resolve = async (calls: FunctionCall[]) => {
			const result = await call({ calls: JSON.stringify(calls), transform });
			return result.ok ? result.data : undefined;
		};
		// a rule that doesn't parse has its syntax error to show instead
		const probed = [...rules.values()].filter((rule) => rule.expr.trim() && !syntaxError(rule.expr));
		const probes = probesExpression(probed, rules);
		const calls: EvalCall[] = items.flatMap((input, index) => [
			{ key: `output:${index}`, expression: jsonata, input },
			{ key: `probes:${index}`, expression: probes, input },
		]);
		setPreview((current) => ({ ...current, busy: true }));
		void (async () => {
			const responses = await evaluateAll(engine, calls, answers.current, resolve);
			if (stale) return;
			const outputs = items.map((_item, index) => responses[index * 2] as EvalResponse);
			const combined = items.map((_item, index) => responses[index * 2 + 1]);
			// the items whose probes failed together, probed one rule at a time
			const failed = combined.flatMap((response, index) => (response?.ok ? [] : [index]));
			const single: EvalCall[] = failed.flatMap((index) =>
				probed.map((rule) => ({
					key: `probe:${index}:${rule.ptr}`,
					expression: probeExpression(rule, rules),
					input: items[index],
				})),
			);
			const singles = single.length > 0 ? await evaluateAll(engine, single, answers.current, resolve) : [];
			if (stale) return;
			const results = new Map<string, RuleResults>();
			for (const [position, rule] of probed.entries()) {
				const ruleAnswers = items.map((_item, index): ProbeAnswer => {
					const fromAll = answerOf(combined[index], rule.ptr);
					if (fromAll) return fromAll;
					const own = singles[failed.indexOf(index) * probed.length + position];
					if (!own) return { ok: false, error: { code: "ES_ABORTED", message: "Not evaluated" } };
					return own.ok
						? { ok: true, value: own.value, defined: own.defined }
						: { ok: false, error: own.error };
				});
				results.set(rule.ptr, ruleResults(rule as Rule, rules, ruleAnswers));
			}
			setPreview({ outputs, results, busy: false });
		})();
		return () => {
			stale = true;
		};
	}, [transform, jsonata, rules, items, call]);

	return preview;
}
