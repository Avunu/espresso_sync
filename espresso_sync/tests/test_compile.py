# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import json
from pathlib import Path

import jsonata
from frappe.tests import IntegrationTestCase

from espresso_sync.transform import engine
from espresso_sync.transform.compile import compile_rules, rule_at

GOLDEN = Path(__file__).parent / "fixtures" / "compile"


def golden_cases():
	for path in sorted(GOLDEN.glob("*.json")):
		yield path.stem, json.loads(path.read_text()), (GOLDEN / f"{path.stem}.jsonata").read_text()


class TestCompile(IntegrationTestCase):
	def test_golden_files(self):
		# the editor's compile.ts is checked against the same files (test/unit/compile.test.ts)
		cases = list(golden_cases())
		self.assertGreaterEqual(len(cases), 5)
		for name, case, expected in cases:
			with self.subTest(name):
				compiled = compile_rules(case["rules"])
				self.assertEqual(compiled.jsonata, expected.removesuffix("\n"))
				self.assertEqual([[e.rule, e.code] for e in compiled.errors], case["errors"])
				self.assertEqual(engine.evaluate(compiled.jsonata, case["input"]), case["output"])

	def test_a_lone_surrogate_is_not_a_pointer(self):
		# a golden file cannot hold one (check-json refuses it): compile.test.ts has this case too
		compiled = compile_rules([{"ptr": "/\ud800", "kind": "field", "expr": "x"}])
		self.assertEqual((compiled.jsonata, [[e.rule, e.code] for e in compiled.errors]), ("{}", [["", "compile.pointer"]]))

	def test_an_error_position_names_its_rule(self):
		compiled = compile_rules(
			[
				{"ptr": "/a", "kind": "field", "expr": "x"},
				{"ptr": "/lines", "kind": "collection", "expr": "lines"},
				{"ptr": "/lines/b", "kind": "field", "expr": "$noSuchFunction(y)"},
			]
		)
		with self.assertRaises(jsonata.JException) as raised:
			engine.evaluate(compiled.jsonata, {"lines": [{"y": 1}]})
		self.assertEqual(rule_at(compiled, raised.exception.location), "/lines/b")
		self.assertEqual(rule_at(compiled, None), "")
		self.assertEqual(rule_at(compiled, 0), "")
