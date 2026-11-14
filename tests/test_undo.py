"""Undo puts things back as they were, but never over a newer change made since (on another phone, or by
Home Assistant)."""
from support import AppTest, days_from_today, server


class UndoTest(AppTest):
    def test_undo_a_use(self):
        i = self.add("Beans", 3, days_from_today(100))
        undo = server.api_use({"qty": 2}, {}, str(i))["undo"]
        self.assertEqual(self.total(i), 1)
        out = server.api_restore_item(undo, {})
        self.assertEqual(out["restored"], 1)
        self.assertEqual(self.total(i), 3)

    def test_undo_a_delete(self):
        i = self.add("Beans", 3, days_from_today(100), notes="Top shelf")
        undo = server.api_item_delete({}, {}, str(i))["undo"]
        self.assertEqual(server.all_items(), [])
        server.api_restore_item(undo, {})
        it = self.item(i)
        self.assertEqual((it["notes"], self.total(i)), ("Top shelf", 3))

    def test_undo_wont_overwrite_a_newer_use(self):
        i = self.add("Beans", 5)
        undo = server.api_use({"qty": 1}, {}, str(i))["undo"]       # this phone
        server.api_use({"qty": 2}, {}, str(i))                     # another phone, just after
        e = self.assertApiError(409, server.api_restore_item, undo, {})
        self.assertIn("changed since", e.message)
        self.assertEqual(self.total(i), 2)

    def test_undo_wont_bring_back_something_deleted_since(self):
        i = self.add("Beans", 5)
        undo = server.api_use({"qty": 1}, {}, str(i))["undo"]
        server.api_item_delete({}, {}, str(i))
        self.assertApiError(409, server.api_restore_item, undo, {})
        self.assertEqual(server.all_items(), [])

    def test_undo_wont_overwrite_new_stock_or_an_edit(self):
        i = self.add("Beans", 5)
        undo = server.api_use({"qty": 1}, {}, str(i))["undo"]
        self.stock(i, 10)
        self.assertApiError(409, server.api_restore_item, undo, {})
        undo = server.api_use({"qty": 1}, {}, str(i))["undo"]
        server.api_item_update({"notes": "Moved to the garage"}, {}, str(i))
        self.assertApiError(409, server.api_restore_item, undo, {})
        self.assertEqual(self.total(i), 13)

    def test_undoing_twice_does_nothing_the_second_time(self):
        i = self.add("Beans", 5)
        undo = server.api_use({"qty": 1}, {}, str(i))["undo"]
        server.api_restore_item(undo, {})
        self.assertApiError(409, server.api_restore_item, undo, {})
        self.assertEqual(self.total(i), 5)

    def test_bulk_undo_puts_back_what_it_can(self):
        a, b = self.add("Beans", 1), self.add("Rice", 2)
        undo = server.api_items_delete({"ids": [a, b]}, {})["undo"]
        server.api_restore_item({"item": undo["many"][0]["item"], "batches": undo["many"][0]["batches"],
                                 "after": None}, {})     # put back already, on another phone
        out = server.api_restore_item(undo, {})
        self.assertEqual((out["restored"], out["skipped"]), (1, ["Beans"]))
        self.assertEqual(sorted(it["name"] for it in server.all_items()), ["Beans", "Rice"])

    def test_batch_edits_can_be_undone(self):
        i = self.add("Beans", 4, days_from_today(50))
        bid = self.item(i)["batches"][0]["id"]
        undo = server.api_batch_update({"qty": 1}, {}, str(bid))["undo"]
        server.api_restore_item(undo, {})
        self.assertEqual(self.total(i), 4)
        bid = self.item(i)["batches"][0]["id"]
        undo = server.api_batch_delete({}, {}, str(bid))["undo"]
        self.assertEqual(self.total(i), 0)
        server.api_restore_item(undo, {})
        self.assertEqual(self.total(i), 4)

    def test_an_undo_from_an_older_app_still_works(self):
        i = self.add("Beans", 3)
        undo = server.api_use({"qty": 1}, {}, str(i))["undo"]
        undo.pop("after")
        server.api_restore_item(undo, {})
        self.assertEqual(self.total(i), 3)


class CheckUndoTest(AppTest):
    def setUp(self):
        super().setUp()
        self.cid = server.api_check_create({"name": "Test the alarms", "every_days": 30}, {})["id"]

    def test_undo_a_tick(self):
        undo = server.api_check_done({}, {}, str(self.cid))["undo"]
        server.api_check_restore(undo, {})
        self.assertIsNone(server.all_checks()[0]["last_done"])

    def test_undo_wont_overwrite_a_newer_change(self):
        undo = server.api_check_done({}, {}, str(self.cid))["undo"]
        server.api_check_update({"every_days": 60}, {}, str(self.cid))
        self.assertApiError(409, server.api_check_restore, undo, {})
        self.assertEqual(server.all_checks()[0]["every_days"], 60)

    def test_undo_a_delete(self):
        undo = server.api_check_delete({}, {}, str(self.cid))["undo"]
        server.api_check_restore(undo, {})
        self.assertEqual([c["name"] for c in server.all_checks()], ["Test the alarms"])
        self.assertApiError(409, server.api_check_restore, undo, {})
