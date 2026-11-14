"""The stores: stock, expiry, targets, pets, the starter list, usage and the daily history."""
import datetime as dt

from support import AppTest, days_from_today, server


def below(s, name):
    return [e for e in s["supply_run"]["below_target"] if e["name"] == name]


class StockTest(AppTest):
    def test_use_takes_the_oldest_first(self):
        i = self.add("Beans", 2, days_from_today(300))
        self.stock(i, 3, days_from_today(30))
        server.api_use({"qty": 4}, {}, str(i))
        b = self.item(i)["batches"]
        self.assertEqual([(x["qty"], x["expiry"]) for x in b], [(1, days_from_today(300))])

    def test_adding_the_same_batch_again_tops_it_up(self):
        i = self.add("Beans", 2, days_from_today(300), unit="tin")
        self.stock(i, 3, days_from_today(300))
        self.assertEqual(len(self.item(i)["batches"]), 1)
        self.assertEqual(self.total(i), 5)

    def test_hold_out_counts_only_food_and_water_in_date(self):
        server.api_settings({"adults": 1, "children": 0, "kcal_adult": 2000, "water_per_person": 2}, {})
        self.add("Rice", 1, days_from_today(100), category="food", kcal_per_unit=4000)
        self.add("Old rice", 5, days_from_today(-3), category="food", kcal_per_unit=4000)
        self.add("Water", 3, None, category="water", litres_per_unit=2)
        s = server.summary()
        self.assertEqual(s["food_days"], 2)
        self.assertEqual(s["water_days"], 3)
        self.assertEqual(s["hold_out_days"], 2)
        self.assertEqual(s["runs_out_first"], "food")


class ExpiredStockTest(AppTest):
    """Out-of-date stock doesn't count towards targets, so it shows as needing replacing."""

    def test_expired_tins_are_on_the_supply_run(self):
        i = self.add("Beans", 4, days_from_today(-10), unit="tin", target_qty=6)
        self.stock(i, 1, days_from_today(200))
        s = server.summary()
        e = below(s, "Beans")[0]
        self.assertEqual((e["have"], e["get"], e["out_of_date"]), (1, 5, 4))
        self.assertIn("4 out of date", e["text"])
        self.assertTrue(any(x["name"] == "Beans" for x in s["low_stock"]))

    def test_all_expired_counts_as_out_of_stock(self):
        self.add("Plasters", 3, days_from_today(-1), category="medical", target_qty=2)
        s = server.summary()
        self.assertEqual([x["name"] for x in s["out_of_stock"]], ["Plasters"])
        self.assertEqual(s["kit_stocked_pct"], 0)

    def test_in_date_stock_meets_the_target(self):
        self.add("Candles", 10, None, category="power", target_qty=10)
        s = server.summary()
        self.assertEqual(s["supply_run"]["below_target"], [])
        self.assertEqual(s["kit_stocked_pct"], 100)


class ExpiryWarningByCategoryTest(AppTest):
    def test_medicines_can_warn_earlier(self):
        self.add("Paracetamol", 1, days_from_today(60), category="medical")
        self.add("Beans", 1, days_from_today(60), category="food")
        self.assertEqual(server.summary()["expiring_soon"], [])
        server.api_settings({"warn_by_cat": {"medical": 90}}, {})
        s = server.summary()
        self.assertEqual([x["name"] for x in s["expiring_soon"]], ["Paracetamol"])
        self.assertEqual(s["warn_by_cat"], {"medical": 90})

    def test_clearing_a_category_goes_back_to_the_usual(self):
        server.api_settings({"warn_by_cat": {"medical": 90, "food": 10}}, {})
        server.api_settings({"warn_by_cat": {"medical": None, "food": 10}}, {})
        self.assertEqual(server.get_settings()["warn_by_cat"], {"food": 10})


class PetsTest(AppTest):
    def test_pets_water_counts_towards_the_household(self):
        server.api_settings({"adults": 1, "water_per_person": 3}, {})
        self.add("Water", 6, None, category="water", litres_per_unit=1)
        self.assertEqual(server.summary()["water_days"], 2)
        server.api_settings({"dogs": 1, "cats": 2}, {})   # 1 + 2 x 0.25 = 1.5 litres more a day
        s = server.summary()
        self.assertEqual(s["water_days"], 1.3)
        self.assertEqual(s["pets"]["water_litres"], 1.5)
        self.assertEqual(s["pets"]["count"], 3)

    def test_pet_food_days_come_from_its_daily_use(self):
        server.api_settings({"dogs": 1}, {})
        self.add("Dog food", 3, None, category="pets", unit="bag", per_day=0.15)
        s = server.summary()
        self.assertEqual(s["pets"]["food_days"], 20)
        self.assertEqual(s["pets"]["food_runs_out_first"], "Dog food")

    def test_starter_list_adds_pet_food_only_with_pets(self):
        server.api_seed({}, {})
        names = [it["name"] for it in server.all_items()]
        self.assertNotIn("Dry dog food (2kg bag)", names)
        server.api_settings({"dogs": 2, "target_days": 30}, {})
        server.api_seed({}, {})
        dog = [it for it in server.all_items() if it["name"] == "Dry dog food (2kg bag)"][0]
        self.assertEqual(dog["target_qty"], 9)       # 2 dogs x 30 days x 0.15 bags
        self.assertEqual(dog["per_day"], 0.3)
        self.assertNotIn("Dry cat food (2kg bag)", [it["name"] for it in server.all_items()])


class StarterTargetsTest(AppTest):
    def starter(self, name):
        return [it for it in server.all_items() if it["name"] == name][0]

    def test_targets_follow_the_household(self):
        server.api_settings({"adults": 2, "children": 0, "target_days": 30}, {})
        server.api_seed({}, {})
        water = self.starter("Bottled water (5L)")["target_qty"]
        rolls = self.starter("Toilet roll")
        out = server.api_settings({"adults": 4}, {})
        self.assertGreater(out["rescaled"], 10)
        self.assertEqual(self.starter("Bottled water (5L)")["target_qty"], water * 2)
        self.assertEqual(self.starter("Toilet roll")["per_day"], rolls["per_day"] * 2)
        server.api_settings({"target_days": 60}, {})
        self.assertEqual(self.starter("Bottled water (5L)")["target_qty"], water * 4)

    def test_a_target_you_set_yourself_stays(self):
        server.api_seed({}, {})
        rice = self.starter("Rice (1kg bag)")
        server.api_item_update({"target_qty": 50}, {}, str(rice["id"]))
        server.api_settings({"adults": 5}, {})
        self.assertEqual(self.starter("Rice (1kg bag)")["target_qty"], 50)
        self.assertEqual(self.starter("Rice (1kg bag)")["auto_target"], 0)

    def test_items_not_from_the_starter_list_are_left_alone(self):
        i = self.add("My own beans", 0, None, target_qty=7)
        server.api_settings({"adults": 6}, {})
        self.assertEqual(self.item(i)["target_qty"], 7)

    def test_an_older_database_has_its_starter_items_found(self):
        server.api_seed({}, {})
        rice = self.starter("Rice (1kg bag)")
        server.DB.execute("UPDATE items SET starter = '', auto_target = 0")
        server.DB.execute("UPDATE items SET target_qty = 99 WHERE id = ?", (rice["id"],))
        server.DB.execute("DELETE FROM settings WHERE key = 'starter_marked'")
        server.init_db()
        self.assertEqual(self.starter("Rice (1kg bag)")["auto_target"], 0)        # changed: yours
        self.assertEqual(self.starter("Pasta (500g)")["auto_target"], 1)          # as the list made it
        self.assertEqual(self.starter("Pasta (500g)")["starter"], "Pasta (500g)")


class UsageTest(AppTest):
    def test_how_fast_it_goes(self):
        i = self.add("Beans", 12, None, unit="tin")
        today = dt.date.today()
        for d in range(0, 28, 7):   # 2 tins every week for four weeks
            server.DB.execute("INSERT INTO usage(item_id, ts, qty) VALUES (?, ?, ?)",
                              (i, (today - dt.timedelta(days=27 - d)).isoformat() + " 12:00:00", 2))
        u = server.usage_rates(server.all_items())[i]
        self.assertEqual(u["text"], "about 2 tins a week, lasts 6 weeks")
        self.assertEqual(u["uses"], 4)

    def test_one_use_isnt_enough_to_say(self):
        i = self.add("Beans", 5, None, unit="tin")
        server.api_use({"qty": 1}, {}, str(i))
        self.assertNotIn(i, server.usage_rates(server.all_items()))
        server.api_use({"qty": 1}, {}, str(i))
        self.assertEqual(server.usage_rates(server.all_items())[i]["text"], "about 2 tins a week, lasts 10 days")

    def test_undoing_a_use_takes_it_off(self):
        i = self.add("Beans", 5, None, unit="tin")
        server.api_use({"qty": 1}, {}, str(i))
        undo = server.api_use({"qty": 1}, {}, str(i))["undo"]
        server.api_restore_item(undo, {})
        self.assertEqual(server.DB.execute("SELECT COUNT(*) FROM usage").fetchone()[0], 1)

    def test_words(self):
        self.assertEqual(server.rate_words(3), "about 3 a day")
        self.assertEqual(server.rate_words(1.5 / 7, "pack"), "about 1.5 packs a week")
        self.assertEqual(server.rate_words(0.5 / 7), "about 2 a month")
        self.assertEqual(server.rate_words(1 / 30.44, "bottle"), "about 1 bottle a month")
        self.assertEqual(server.rate_words(0.001), "less than one a month")


class HistoryTest(AppTest):
    def test_a_row_a_day(self):
        self.add("Rice", 2, None, category="food", kcal_per_unit=4400)
        row = server.record_history()
        self.assertEqual(row["items"], 1)
        server.record_history()
        rows = server.api_history({}, {"days": ["30"]})["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["day"], dt.date.today().isoformat())
        self.assertEqual(rows[0]["food_days"], 2)

    def test_old_rows_are_cleared(self):
        old = (dt.date.today() - dt.timedelta(days=server.HISTORY_KEEP_DAYS + 5)).isoformat()
        server.DB.execute("INSERT INTO history(day) VALUES (?)", (old,))
        server.record_history()
        self.assertEqual([r["day"] for r in server.DB.execute("SELECT day FROM history")], [dt.date.today().isoformat()])
