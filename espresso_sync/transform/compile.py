# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""A Transform's rules, compiled to the one JSONata expression it runs.

A rule fills the target field at its pointer. As in the editor (pointer.ts), the items
of a collection are implied, never indexed: ``/items/qty`` is the ``qty`` of every item.

- ``field``: the value of its expression;
- ``collection``: an array holding an object for each item its expression gives, each
  filled by the rules under it, evaluated on that item;
- ``scalar_collection``: an array of the values its expression gives.

The fields between the root and a rule that no rule fills are objects. Keys come in the
order the rules first name them. A collection is always an array, of one item or none
too. Each expression is kept as written, in parentheses, its newlines included: one may
be inside a string literal.

The editor's compile.ts gives the same text for the same rules, byte for byte: both are
checked against the golden files in tests/fixtures/compile.
"""

import json
from typing import Any, NamedTuple

from frappe import _

KINDS = ("field", "collection", "scalar_collection")
INDENT = "\t"


class CompileError(NamedTuple):
	rule: str
	code: str
	message: str


class Compiled(NamedTuple):
	jsonata: str
	# the rules left out, and why
	errors: list[CompileError]
	# (start, end, rule pointer): where each rule's expression is in the text
	spans: list[tuple[int, int, str]]


class Node:
	__slots__ = ("children", "rule")

	def __init__(self):
		self.rule: dict[str, Any] | None = None
		self.children: dict[str, Node] = {}


def unescape(token: str) -> str:
	return token.replace("~1", "/").replace("~0", "~")


def rule_errors(rule: Any) -> CompileError | None:
	"""Why a rule cannot be compiled at all, if it cannot."""
	if not isinstance(rule, dict):
		return CompileError("", "compile.rule", _("A rule is an object with ptr, kind and expr"))
	pointer = rule.get("ptr")
	if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
		shown = pointer if isinstance(pointer, str) else ""
		return CompileError(shown, "compile.pointer", _("{0} is not a JSON Pointer").format(pointer))
	if rule.get("kind") not in KINDS:
		return CompileError(
			pointer,
			"compile.kind",
			_("{0} is not field, collection or scalar_collection").format(rule.get("kind")),
		)
	expression = rule.get("expr")
	if not isinstance(expression, str) or not expression.strip():
		return CompileError(pointer, "compile.empty", _("An expression is required"))
	return None


def rules_under(node: Node):
	for child in node.children.values():
		if child.rule is not None:
			yield child.rule
		yield from rules_under(child)


class Writer:
	def __init__(self, errors: list[CompileError]):
		self.parts: list[str] = []
		self.length = 0
		self.spans: list[tuple[int, int, str]] = []
		self.errors = errors

	def write(self, text: str):
		self.parts.append(text)
		self.length += len(text)

	def expression(self, rule: dict[str, Any]):
		self.write("(")
		start = self.length
		self.write(rule["expr"])
		self.spans.append((start, self.length, rule["ptr"]))
		self.write(")")

	def node(self, node: Node, depth: int):
		rule = node.rule
		if rule is None:
			self.object(node, depth)
			return
		if rule["kind"] != "collection":
			self.errors.extend(
				CompileError(
					nested["ptr"],
					"compile.nested",
					_("{0} is filled by a {1} rule: nothing can be under it").format(
						rule["ptr"], rule["kind"]
					),
				)
				for nested in rules_under(node)
			)
		if rule["kind"] == "field":
			self.expression(rule)
			return
		self.write("[")
		self.expression(rule)
		if rule["kind"] == "collection":
			self.write(".")
			self.object(node, depth)
		self.write("]")

	def object(self, node: Node, depth: int):
		if not node.children:
			self.write("{}")
			return
		self.write("{")
		for index, (key, child) in enumerate(node.children.items()):
			separator = "," if index else ""
			self.write(f"{separator}\n{INDENT * (depth + 1)}{json.dumps(key, ensure_ascii=False)}: ")
			self.node(child, depth + 1)
		self.write(f"\n{INDENT * depth}}}")


def compile_rules(rules: list[Any]) -> Compiled:
	"""The JSONata of `rules` ([{ptr, kind, expr}]), with the rules it had to leave out."""
	root = Node()
	errors: list[CompileError] = []
	for rule in rules:
		error = rule_errors(rule)
		if error:
			errors.append(error)
			continue
		node = root
		pointer = rule["ptr"]
		for token in pointer[1:].split("/") if pointer else ():
			node = node.children.setdefault(unescape(token), Node())
		if node.rule is not None:
			errors.append(CompileError(pointer, "compile.duplicate", _("{0} has two rules").format(pointer)))
			continue
		node.rule = rule
	writer = Writer(errors)
	writer.node(root, 0)
	return Compiled("".join(writer.parts), errors, writer.spans)


def rule_at(compiled: Compiled, position: int | None) -> str:
	"""The pointer of the rule whose expression holds `position` (an error's, in the text),
	or "" when none does."""
	if position is None:
		return ""
	return next((pointer for start, end, pointer in compiled.spans if start <= position <= end), "")
