"""Offline format tests and a read-only regression against all frozen formal30 answers."""
import csv
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "controlled_raw/formal30"
sys.path.insert(0, str(ROOT))
from batch_transport import read
from evidence_refs import refs, refs_by_line, without_refs
from review import armdata


class Formats(unittest.TestCase):
    def test_markers(self):
        # Text, expected first-mention order, text shown for blind comparison.
        cases = [
            ("原文[E1]。", [1], "原文。"),
            ("原文[E1,E2]。", [1, 2], "原文。"),
            ("[E3，E1、3]", [3, 1], ""),
            ("[E1-E3]", [1, 2, 3], ""),
            ("[E1]—[E3]", [1, 2, 3], ""),
            ("【E1至3】", [1, 2, 3], ""),
            ("［ E2，4–6 ］", [2, 4, 5, 6], ""),
            ("[E3,E1-E4,E6]", [3, 1, 2, 4, 6], ""),
            ("[E2][E1][E2]", [2, 1], ""),
            ("[E1,\n E3]", [1, 3], "\n"),
            ("[E0,E11]", [0, 11], ""),
            ("[E3-E1]", [3, 1], ""),
            ("[E1-E1000000]", [1, 1000000], ""),
            ("GCS E1VTM2，pH 7.0，[10-19查房]。", [], "GCS E1VTM2，pH 7.0，[10-19查房]。"),
            ("[E1,未核实] [E3", [], "[E1,未核实] [E3"),
        ]
        for text, expected, blinded in cases:
            with self.subTest(text=text):
                self.assertEqual(refs(text), expected)
                self.assertEqual(without_refs(text), blinded)
                per_line = [i for ids in refs_by_line(text).values() for i in ids]
                self.assertEqual(list(dict.fromkeys(per_line)), expected)

    def test_line_links(self):
        self.assertEqual(refs_by_line("甲[E2][E2]\r\n乙[E1,\nE3]。[E2]"), {0: [2], 2: [1, 3, 2]})

    def test_out_of_bounds(self):
        eligible = {1, 2}
        self.assertEqual([n for n in refs("见[E1-E3,E0]") if n not in eligible], [3, 0])


def regression():
    def csv_rows(name):
        with (ROOT / name).open(encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    summary = {(r["病例"], r["方法"]): r for r in csv_rows("表一_逐例检索及成本.csv")}
    cited_positions = {}
    for r in csv_rows("检索与原文逐条标签.csv"):
        if r["层"] == "原文" and r["正文点名"] == "1":
            cited_positions.setdefault((r["病例"], r["方法"]), set()).add(int(r["位置"]))
    counts = Counter()
    checked = set()
    for case in read(ROOT / "manifest.json"):
        c = ROOT / case["tag"]
        for arm, bundle in armdata(c).items():
            key = (c.name, arm)
            if key in checked:
                raise ValueError(f"重复病例/组别 {key}")
            checked.add(key)
            ids = bundle["refs"]
            valid = {i for i in ids if 1 <= i <= len(bundle["ev"])}
            invalid = set(ids) - valid
            stored = read(c / arm / "result.json")
            stats = summary[key]
            historical_invalid = {int(i) for i in stats["越界编号"].split(",") if i}
            per_line = refs_by_line(bundle["ans"])
            current = set(i for row in per_line.values() for i in row)
            if not (set(ids) == set(stored["refs"]) == current and
                    invalid == set(stored["invalid"]) == historical_invalid and
                    len(valid) == int(stats["点名有效原文"]) and valid == cited_positions.get(key, set())):
                raise ValueError(f"冻结记录或统计存在差异 {key}")
            counts[arm, "answers"] += 1
            counts[arm, "valid"] += len(valid)
            counts[arm, "invalid"] += len(invalid)
    expected = {(f"F{i:02}", arm) for i in range(1, 31) for arm in ("direct", "static", "loop")}
    if checked != expected or set(summary) != expected:
        raise ValueError("90份冻结答案覆盖不完整")
    return counts


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Formats)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        sys.exit(1)
    counts = regression()
    for arm in ("direct", "static", "loop"):
        print(arm, dict((k, counts[arm,k]) for k in ("answers","valid","invalid")))

