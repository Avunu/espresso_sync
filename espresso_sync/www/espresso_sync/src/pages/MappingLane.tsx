// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useCallback, useLayoutEffect, useRef, useState } from "react";

/** A line from a source row to a target row: a rule there reads the source field. */
export interface Link {
	source: string;
	target: string;
	/** A collection's line is dashed; one into a field whose rule is more than a path is the interactive colour. */
	kind: "path" | "formula" | "collection";
	/** The selected rule's lines are drawn on top, at full strength. */
	hot: boolean;
	error: boolean;
}

interface Drawn extends Link {
	y1: number;
	y2: number;
}

const LABEL = ":scope > .cds--tree-node__label";

/** The vertical middle of a row, from the lane's top; undefined when the row isn't shown. */
function middle(id: string, top: number): number | undefined {
	const row = document.getElementById(id)?.querySelector(LABEL);
	if (!row) return undefined;
	const box = row.getBoundingClientRect();
	return box.height > 0 ? box.top + box.height / 2 - top : undefined;
}

function colour(link: Link): string {
	if (link.error) return "var(--cds-support-error)";
	if (link.kind === "formula" || link.hot) return "var(--cds-interactive)";
	return "var(--cds-border-strong)";
}

/**
 * The lane between the trees: a curve from each source field a rule reads to
 * the field the rule fills, measured off the rows as drawn. It only shows what
 * the rows already say, so it is hidden from assistive technology.
 */
export function MappingLane({ links, selected }: { links: Link[]; selected: boolean }) {
	const lane = useRef<SVGSVGElement>(null);
	const [drawn, setDrawn] = useState<Drawn[]>([]);
	const [width, setWidth] = useState(0);

	const measure = useCallback(() => {
		const svg = lane.current;
		if (!svg) return;
		const box = svg.getBoundingClientRect();
		const next: Drawn[] = [];
		for (const link of links) {
			const y1 = middle(link.source, box.top);
			const y2 = middle(link.target, box.top);
			if (y1 !== undefined && y2 !== undefined) next.push({ ...link, y1, y2 });
		}
		// the selected rule's lines last, so they cross over the others
		next.sort((a, b) => Number(a.hot) - Number(b.hot));
		setWidth(box.width);
		setDrawn((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next));
	}, [links]);

	useLayoutEffect(() => {
		measure();
		// rows move when a group opens, the trees are filtered, or the window resizes
		const grid = lane.current?.parentElement;
		if (!grid) return undefined;
		const observer = new ResizeObserver(() => measure());
		observer.observe(grid);
		for (const child of grid.children) observer.observe(child);
		return () => observer.disconnect();
	}, [measure]);

	return (
		<svg ref={lane} aria-hidden="true" style={{ width: "100%", height: "100%", overflow: "visible" }}>
			{drawn.map((link) => {
				const stroke = colour(link);
				const opacity = selected && !link.hot ? 0.35 : 1;
				const mid = width / 2;
				return (
					<g key={`${link.source}>${link.target}`} opacity={opacity}>
						<path
							d={`M0 ${link.y1} C${mid} ${link.y1} ${mid} ${link.y2} ${width} ${link.y2}`}
							fill="none"
							stroke={stroke}
							strokeWidth={link.hot ? 2 : 1}
							strokeDasharray={link.kind === "collection" ? "4 3" : undefined}
						/>
						<circle cx={width - 2} cy={link.y2} r={3} fill={stroke} />
					</g>
				);
			})}
		</svg>
	);
}
