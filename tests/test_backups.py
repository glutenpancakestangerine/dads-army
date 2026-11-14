"""Backups: the automatic copies are checked before they're kept and never overwrite each other; a backup
file restores everything; an empty one asks first; and the spreadsheet can't be made to run formulas."""
import csv
import io
import json
import os
import sqlite3
from unittest import mock

from support import AppTest, days_from_today, server


class AutomaticBackupTest(AppTest):
    def test_a_backup_is_a_sound_copy(self):
        self.add("Beans", 3)
        path = server.make_backup("auto")
        conn = sqlite3.connect(path)
        self.assertEqual(conn.execute("SELECT name FROM items").fetchall(), [("Beans",)])
        conn.close()
        self.assertEqual(os.listdir(server.BACKUP_DIR), [os.path.basename(path)])

    def test_two_backups_in_the_same_second_dont_overwrite_each_other(self):
        with mock.patch.object(server.dt, "datetime", wraps=server.dt.datetime) as fake:
            fake.now.return_value = server.dt.datetime(2026, 11, 14, 9, 30, 0)
            a = server.make_backup("auto")
            self.add("Beans", 1)
            b = server.make_backup("auto")
        self.assertNotEqual(a, b)
        self.assertTrue(os.path.basename(b).startswith("dadsarmy-20261114-093000a-"))
        self.assertEqual(sorted(server.list_backups()), [os.path.basename(a), os.path.basename(b)])

    def test_a_bad_copy_isnt_kept_and_the_old_ones_stay(self):
        old = [server.make_backup("auto")]
        with mock.patch.object(server, "check_backup", side_effect=server.BackupError("the copy is damaged")):
            with self.assertRaises(server.BackupError):
                server.make_backup("auto")
        self.assertEqual(server.list_backups(), [os.path.basename(p) for p in old])
        self.assertFalse([f for f in os.listdir(server.BACKUP_DIR) if f.endswith(".tmp")])

    def test_the_check_spots_a_damaged_file(self):
        bad = os.path.join(self.dir, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\xff" * 5000)
        with self.assertRaises(server.BackupError):
            server.check_backup(bad)
        other = os.path.join(self.dir, "other.db")
        sqlite3.connect(other).execute("CREATE TABLE x (y)").connection.close()
        with self.assertRaises(server.BackupError):
            server.check_backup(other)

    def test_only_the_newest_are_kept(self):
        for n in range(server.KEEP_BACKUPS + 3):
            open(os.path.join(server.BACKUP_DIR, "dadsarmy-2020010%02d-000000-auto.db" % n), "w").close()
        server.make_backup("auto")
        kept = server.list_backups()
        self.assertEqual(len(kept), server.KEEP_BACKUPS)
        self.assertTrue(kept[-1] > "dadsarmy-2026")


class BackupFileTest(AppTest):
    def fill(self):
        server.api_settings({"adults": 3, "dogs": 1, "warn_by_cat": {"medical": 90}}, {})
        server.api_seed({}, {})
        i = self.add("Beans", 4, days_from_today(100), unit="tin", target_qty=8, notes="Cupboard")
        server.api_use({"qty": 1}, {}, str(i))
        server.api_use({"qty": 1}, {}, str(i))
        server.api_check_create({"name": "Test the alarms", "every_days": 30}, {})
        server.api_shop_add({"text": "Matches"}, {})
        server.record_history()
        return json.loads(server.api_backup({}, {}).data.decode("utf-8"))

    def test_round_trip(self):
        backup = self.fill()
        self.assertEqual(backup["app"], "dadsarmy")
        beans = [it for it in backup["items"] if it["name"] == "Beans"][0]
        self.assertEqual(len(beans["usage"]), 2)
        self.assertEqual(len(backup["history"]), 1)
        before = server.summary()
        # Start again from nothing, then restore.
        server.api_items_delete({"ids": [it["id"] for it in server.all_items()]}, {})
        server.api_settings({"adults": 1, "dogs": 0, "warn_by_cat": {}}, {})
        out = server.api_restore(backup, {})
        self.assertEqual(out["items"], len(backup["items"]))
        after = server.summary()
        for k in ("hold_out_days", "water_days", "items_total", "pets"):
            self.assertEqual(after[k], before[k], k)
        st = server.get_settings()
        self.assertEqual((st["adults"], st["dogs"], st["warn_by_cat"]), (3, 1, {"medical": 90}))
        beans = [it for it in server.all_items() if it["name"] == "Beans"][0]
        self.assertIn(beans["id"], server.usage_rates(server.all_items()))
        rice = [it for it in server.all_items() if it["name"] == "Rice (1kg bag)"][0]
        self.assertEqual((rice["starter"], rice["auto_target"]), ("Rice (1kg bag)", 1))
        self.assertEqual(len(server.api_history({}, {})["rows"]), 1)
        self.assertTrue([f for f in os.listdir(server.BACKUP_DIR) if f.endswith("-pre-restore.db")])

    def test_an_empty_backup_asks_first(self):
        self.add("Beans", 4)
        empty = {"app": "dadsarmy", "items": []}
        e = self.assertApiError(409, server.api_restore, empty, {})
        self.assertEqual(e.code, "empty_backup")
        self.assertIn("delete all 1 things", e.message)
        self.assertEqual(len(server.all_items()), 1)
        server.api_restore(dict(empty, confirm_empty=True), {})
        self.assertEqual(server.all_items(), [])

    def test_an_empty_backup_into_empty_stores_needs_no_question(self):
        self.assertEqual(server.api_restore({"app": "dadsarmy", "items": []}, {})["items"], 0)

    def test_a_damaged_backup_changes_nothing(self):
        self.add("Beans", 4)
        for bad in ({"app": "something else", "items": []},
                    {"app": "dadsarmy", "items": [{"name": "Rice", "batches": [{"qty": "lots"}]}]},
                    {"app": "dadsarmy", "items": [{"name": "Rice", "batches": "x"}]},
                    {"app": "dadsarmy", "items": [{"name": "Rice"}], "settings": {"adults": 900}},
                    {"app": "dadsarmy", "items": [{"name": "Rice", "batches": [{"qty": 1, "expiry": "soon"}]}]}):
            self.assertApiError(400, server.api_restore, bad, {})
        self.assertEqual([it["name"] for it in server.all_items()], ["Beans"])
        self.assertEqual(server.list_backups("-pre-restore.db"), [])

    def test_an_older_backup_still_restores(self):
        old = {"app": "dadsarmy", "version": "1.4.0", "settings": {"adults": 2},
               "items": [{"name": "Rice (1kg bag)", "category": "food", "unit": "bag", "kcal_per_unit": 3600,
                          "target_qty": 1, "batches": [{"qty": 2, "expiry": None, "location": "Larder"}]}]}
        server.api_restore(old, {})
        rice = server.all_items()[0]
        self.assertEqual((rice["name"], rice["batches"][0]["location"], rice["starter"]),
                         ("Rice (1kg bag)", "Larder", "Rice (1kg bag)"))


class SpreadsheetTest(AppTest):
    def rows(self):
        data = server.api_export_csv({}, {}).data.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(data)))

    def test_cells_cant_run_formulas(self):
        self.add("=HYPERLINK(\"http://example.com\",\"Click\")", 1, location="+cmd|' /C calc'!A0",
                 notes="@SUM(A1:A9)", unit="-tin")
        self.add(" =1+1", 1)
        rows = self.rows()
        for r in rows[1:]:
            for cell in (r[1], r[3], r[5], r[11]):
                self.assertFalse(cell.lstrip(" ").startswith(("=", "+", "-", "@")), r)
        names = [r[1] for r in rows[1:]]
        self.assertIn("'=HYPERLINK(\"http://example.com\",\"Click\")", names)
        self.assertIn("'=1+1", names)   # names are trimmed when saved

    def test_ordinary_values_are_left_as_they_are(self):
        self.add("Beans", 3, days_from_today(30), unit="tin", notes="Top shelf", price=0.85)
        r = self.rows()[1]
        self.assertEqual((r[1], r[2], r[3], r[11], r[10]), ("Beans", "3", "tin", "Top shelf", "0.85"))
