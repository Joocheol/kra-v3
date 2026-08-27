from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from check_coherence import load_month
from kra.canonical import (
    CELL_FIELDS,
    _PartitionWriters,
    materialize_legacy_input,
    verify_v1_source,
)


class CanonicalInputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        race_id = "20250101-1-01"
        self._gzip_jsonl("races", [{
            "race_id": race_id, "year": 2025, "rc_date": 20250101,
            "meet": 1, "rc_no": 1,
        }])
        self._gzip_jsonl("entries", [
            {"race_id": race_id, "chulNo": horse, "hrName": f"말{horse}"}
            for horse in (1, 2, 3, 4)
        ])
        self._gzip_jsonl("results", [
            {"race_id": race_id, "chulNo": "1", "stOrd": "2", "differ": "목"},
            {"race_id": race_id, "chulNo": "2", "stOrd": "1", "differ": "-"},
            {"race_id": race_id, "chulNo": "3", "stOrd": "3", "differ": "1"},
            {"race_id": race_id, "chulNo": "4", "stOrd": None, "differ": "출전취소"},
        ])
        self._gzip_jsonl("sales", [
            {"race_id": race_id, "pool_code": pool, "amt": index * 100}
            for index, pool in enumerate(
                ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI"), start=1
            )
        ])
        odds = []
        for pool in ("WIN", "PLC"):
            odds.extend({"race_id": race_id, "pool_code": pool, "chulNo": h, "odds": h + .1}
                        for h in (1, 2, 3))
        for pool in ("QNL", "QPL"):
            odds.extend({"race_id": race_id, "pool_code": pool, "chulNo1": a,
                         "chulNo2": b, "odds": a * 10 + b + .1}
                        for a, b in ((1, 2), (1, 3), (2, 3)))
        odds.extend({"race_id": race_id, "pool_code": "EXA", "chulNo1": a,
                     "chulNo2": b, "odds": a * 10 + b + .1}
                    for a in (1, 2, 3) for b in (1, 2, 3) if a != b)
        odds.append({"race_id": race_id, "pool_code": "TLA", "chulNo": 1,
                     "chulNo2": 2, "chulNo3": 3, "odds": 12.3})
        odds.extend({"race_id": race_id, "pool_code": "TRI", "chulNo": a,
                     "chulNo2": b, "chulNo3": c, "odds": a * 100 + b * 10 + c + .1}
                    for a in (1, 2, 3) for b in (1, 2, 3) for c in (1, 2, 3)
                    if len({a, b, c}) == 3)
        self._gzip_jsonl("odds", odds)
        self._gzip_jsonl("coverage", [{
            "race_id": race_id,
            **{f"odds_{p}": True for p in ("win", "plc", "qnl", "exa", "qpl", "tla", "tri")},
            **{f"sales_{p}": True for p in ("win", "plc", "qnl", "exa", "qpl", "tla", "tri")},
        }])
        manifest = {
            "schema_version": 2, "race_id_format": "YYYYMMDD-meet-rcNo", "tables": {},
        }
        (self.source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        names = ("races.jsonl.gz", "entries.jsonl.gz", "results.jsonl.gz",
                 "sales.jsonl.gz", "odds.jsonl.gz", "coverage.jsonl.gz", "manifest.json")
        checksums = []
        for name in names:
            digest = hashlib.sha256((self.source / name).read_bytes()).hexdigest()
            checksums.append(f"{digest}  {name}")
        (self.source / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _gzip_jsonl(self, stem: str, rows: list[dict]) -> None:
        with gzip.open(self.source / f"{stem}.jsonl.gz", "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_verify_rejects_tampering(self) -> None:
        verify_v1_source(self.source, official=False)
        with (self.source / "manifest.json").open("a", encoding="utf-8") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_v1_source(self.source, official=False)

    def test_materializes_legacy_orientation_and_race_metadata(self) -> None:
        output = self.root / "output"
        report = materialize_legacy_input(
            self.source, output, years=(2025,), official=False,
        )
        self.assertEqual(report["selection"]["race_count"], 1)
        with gzip.open(output / "races.jsonl.gz", "rt", encoding="utf-8") as handle:
            race = json.loads(next(handle))
        self.assertEqual(race["race_id"], "2025-01-01_1_01")
        self.assertEqual(race["arrival"], [2, 1, 3])
        self.assertEqual(race["scratched"], [4])
        self.assertEqual(race["sales"]["총매출액"], "2,800원")

        month = load_month(output, "2025-01")["2025-01-01_1_01"]
        self.assertEqual(month["exacta"][(1, 2)], 12.1)
        self.assertEqual(month["trifecta"][(1, 2, 3)], 123.1)
        self.assertEqual(month["trio"][frozenset((1, 2, 3))], 12.3)
        with gzip.open(
            output / "cells/page_key=Scm/2025-01.csv.gz", "rt", encoding="utf-8", newline=""
        ) as handle:
            self.assertEqual(tuple(csv.DictReader(handle).fieldnames or ()), CELL_FIELDS)

    def test_refuses_to_overwrite_materialized_input(self) -> None:
        output = self.root / "output"
        materialize_legacy_input(self.source, output, years=(2025,), official=False)
        with self.assertRaises(FileExistsError):
            materialize_legacy_input(self.source, output, years=(2025,), official=False)

    def test_partitions_are_complete_gzip_streams(self) -> None:
        output = self.root / "partitions"
        writers = _PartitionWriters(output)
        row = {name: "" for name in CELL_FIELDS}
        row.update(section="body", cell_raw="1.0", rowspan="1", colspan="1", spanned="0")
        for index in range(100):
            page = "Scm" if index % 2 else "Both"
            month = f"2025-{index % 3 + 1:02d}"
            row.update(race_id=str(index), page_key=page)
            writers.writerow(page, month, row)
        writers.close()
        for path in output.glob("cells/*/*.csv.gz"):
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                self.assertGreater(sum(1 for _ in csv.DictReader(handle)), 0)


if __name__ == "__main__":
    unittest.main()
