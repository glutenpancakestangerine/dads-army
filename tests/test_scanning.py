"""Scanning (1.13.0): how long the food lasts, barcodes, what Open Food Facts and the AI give back, pack sizes, using part of one,
opened packs, and the AI settings. Nothing here reaches the internet or a real AI."""
import json

from support import AppTest, days_from_today, server


class TestBarcodes(AppTest):
    def test_a_barcode_goes_to_its_item_and_survives_a_restore(self):
        beans = self.add("Baked beans", 2, days_from_today(300), category="food", unit="tin")
        self.assertApiError(400, server.api_scan_barcode, {}, {"code": ["abc"]})
        made = server.api_item_create({"name": "Beanz (415g)", "category": "food", "unit": "tin", "qty": 1,
                                       "barcode": "5000157024671", "product": "Beanz"}, {})["id"]
        self.assertEqual(server.api_scan_barcode({}, {"code": ["5000157024671"]})["item_id"], made)
        # Another brand on the same line: the barcode points at the item you already keep.
        server.api_scan_link({"code": "5010251605466", "item_id": beans}, {})
        self.assertEqual(server.api_scan_barcode({}, {"code": ["5010251605466"]})["item_id"], beans)
        self.assertApiError(404, server.api_scan_link, {"code": "5010251605467", "item_id": 999999}, {})
        backup = json.loads(server.api_backup({}, {}).data.decode("utf-8"))
        self.assertEqual(sorted(c["code"] for it in backup["items"] for c in it["barcodes"]), ["5000157024671", "5010251605466"])
        server.api_restore(backup, {})
        beans_now = [it for it in server.all_items() if it["name"] == "Baked beans"][0]["id"]
        self.assertEqual(server.api_scan_barcode({}, {"code": ["5010251605466"]})["item_id"], beans_now)
        server.api_item_delete({}, {}, str(beans_now))   # the item's barcodes go with it
        server.OFF_CACHE["5010251605466"] = None          # (and Open Food Facts doesn't know it)
        self.assertIsNone(server.api_scan_barcode({}, {"code": ["5010251605466"]})["item_id"])

    def test_barcodes_come_back_with_undo_and_older_backups(self):
        rice = self.add("Rice", 1, unit="bag", barcode="5000157024671", product="Rice")
        res = server.api_item_delete({}, {}, str(rice))
        server.api_restore_item(res["undo"], {})
        self.assertEqual(server.api_scan_barcode({}, {"code": ["5000157024671"]})["item_id"], rice)
        # A backup from before barcodes: the ones you have stay, matched up by name.
        old = json.loads(server.api_backup({}, {}).data.decode("utf-8"))
        for it in old["items"]:
            it.pop("barcodes", None)
        server.api_restore(old, {})
        rice = [it for it in server.all_items() if it["name"] == "Rice"][0]["id"]
        self.assertEqual(server.api_scan_barcode({}, {"code": ["5000157024671"]})["item_id"], rice)
        # Product names come back too, and one damaged barcode doesn't stop the restore.
        b = json.loads(server.api_backup({}, {}).data.decode("utf-8"))
        self.assertEqual(b["items"][0]["barcodes"], [{"code": "5000157024671", "product": "Rice"}])
        b["items"][0]["barcodes"].append("not-a-code")
        server.api_restore(b, {})
        # A 12-digit UPC-A and the same code with a 0 in front are one barcode.
        rice = [it for it in server.all_items() if it["name"] == "Rice"][0]["id"]
        server.api_scan_link({"code": "012345678905", "item_id": rice}, {})
        self.assertEqual(server.api_scan_barcode({}, {"code": ["0012345678905"]})["item_id"], rice)

    def test_open_food_facts(self):
        sample = {"product": {"product_name": "Baked Beans in Tomato Sauce", "brands": "Heinz,Kraft Heinz", "quantity": "415 g",
                              "product_quantity": "415", "product_quantity_unit": "g", "nutriments": {"energy-kcal_100g": 78},
                              "categories_tags": ["en:canned-foods"]}}
        seen = []
        server.http_get = lambda url, **kw: seen.append(url) or json.dumps(sample).encode()
        server.OFF_CACHE.clear()
        p = server.off_product("5000157024671")
        self.assertEqual((p["name"], p["kcal_per_unit"], p["category"], p["unit"], p["count"]),
                         ("Heinz Baked Beans in Tomato Sauce (415 g)", 324, "food", "tin", 0))
        self.assertIn("/5000157024671.json", seen[0])   # only the barcode goes to Open Food Facts
        sample["product"].update(quantity="6 x 330 ml", product_name="Cola", categories_tags=[])
        server.OFF_CACHE.clear()
        self.assertEqual(server.off_product("5449000000996")["count"], 6)
        # A product only named in German: with no AI set up, the German name stays rather than failing.
        sample["product"].update(product_name="Linseneintopf", lang="de", quantity="800 g")
        server.OFF_CACHE.clear()
        self.assertTrue(server.off_product("4000000000000")["name"].endswith("Linseneintopf (800 g)"))


class TestPacks(AppTest):
    def test_part_of_a_pack_and_opened_batches(self):
        pasta = self.add("Pasta", 2, days_from_today(300), category="food", unit="bag", pack_size=500, pack_unit="g", open_days=30)
        it = self.item(pasta)
        self.assertEqual((it["pack_size"], it["pack_unit"], it["open_days"]), (500, "g", 30))
        self.assertApiError(400, server.api_item_create, {"name": "Odd", "pack_size": 5, "pack_unit": "stone"}, {})
        # 200 g of a 500 g bag: one stays sealed, the rest of the opened one is its own batch.
        server.api_use({"qty": 0.4}, {}, str(pasta))
        self.assertEqual(sorted((b["qty"], bool(b["opened_at"])) for b in self.item(pasta)["batches"]), [(0.6, True), (1, False)])
        # New stock with the same date doesn't join the opened bag.
        self.stock(pasta, 1, days_from_today(300))
        self.assertEqual(sorted((b["qty"], bool(b["opened_at"])) for b in self.item(pasta)["batches"]), [(0.6, True), (2, False)])
        # The opened bag is used first; finishing it leaves only sealed bags.
        server.api_use({"qty": 0.6}, {}, str(pasta))
        self.assertEqual([(b["qty"], b["opened_at"]) for b in self.item(pasta)["batches"]], [(2, None)])

    def test_undo_keeps_an_opened_pack(self):
        rice = self.add("Rice", 1, days_from_today(200), unit="bag", pack_size=1, pack_unit="kg")
        server.api_use({"qty": 0.5}, {}, str(rice))
        res = server.api_use({"qty": 0.25}, {}, str(rice))
        server.api_restore_item(res["undo"], {})
        self.assertEqual([(b["qty"], bool(b["opened_at"])) for b in self.item(rice)["batches"]], [(0.5, True)])

    def test_cans_from_multipacks_add_up(self):
        cola = self.add("Cola", 3, category="water", unit="pack", pack_size=6, pack_unit="each")
        for _ in range(6):   # one can at a time, as the app sends it
            server.api_use({"qty": round(1 / 6.0, 3)}, {}, str(cola))
        self.assertEqual([(b["qty"], b["opened_at"]) for b in self.item(cola)["batches"]], [(2, None)])   # not 1 + 0.998
        tuna = self.add("Tuna", 1, unit="pack", pack_size=3, pack_unit="each")
        for _ in range(3):
            server.api_use({"qty": round(1 / 3.0, 3)}, {}, str(tuna))
        self.assertEqual(self.item(tuna)["batches"], [])   # nothing tiny left over

    def test_restore_keeps_an_opened_pack(self):
        beans = self.add("Beans", 2, days_from_today(300), unit="tin", pack_size=400, pack_unit="g", open_days=3)
        server.api_use({"qty": 0.5}, {}, str(beans))
        server.api_restore(json.loads(server.api_backup({}, {}).data.decode("utf-8")), {})
        beans = [it for it in server.all_items() if it["name"] == "Beans"][0]
        self.assertEqual(sorted((b["qty"], bool(b["opened_at"])) for b in beans["batches"]), [(0.5, True), (1, False)])
        # Home Assistant sees the opened tin go off at its "use within 3 days", not its best before.
        opened = [b for b in server.open_dated(server.all_items())[0]["batches"] if b["opened_at"]][0]
        self.assertEqual(opened["expiry"], days_from_today(3))

    def test_use_from_the_batch_in_your_hand(self):
        soup = self.add("Soup", 2, days_from_today(100), unit="tin")
        self.stock(soup, 3, days_from_today(500))
        later = [b for b in self.item(soup)["batches"] if b["expiry"] == days_from_today(500)][0]["id"]
        server.api_use({"qty": 1, "batch_id": later}, {}, str(soup))
        self.assertEqual(sorted((b["expiry"], b["qty"]) for b in self.item(soup)["batches"]),
                         [(days_from_today(100), 2), (days_from_today(500), 2)])
        server.api_use({"qty": 3, "batch_id": later}, {}, str(soup))   # more than the batch: the rest from the oldest
        self.assertEqual([(b["expiry"], b["qty"]) for b in self.item(soup)["batches"]], [(days_from_today(100), 1)])
        self.assertApiError(404, server.api_use, {"qty": 1, "batch_id": later}, {}, str(soup))


class TestFoodDays(AppTest):
    def test_food_that_goes_off_first_does_not_count(self):
        server.api_settings({"adults": 2, "children": 0, "kcal_adult": 2200}, {})
        # 4,400 kcal a day. 10 days of bread that goes off in 2 days (today, tomorrow and the day after),
        # and 5 days of tins with no date: 3 + 5 days, with 7 days of bread wasted.
        self.add("Bread", 10, days_from_today(2), category="food", unit="loaf", kcal_per_unit=4400)
        self.add("Tins", 5, category="food", unit="tin", kcal_per_unit=4400)
        s = server.summary()
        self.assertEqual((s["food_days"], s["food_wasted_days"]), (8, 7))
        # Drinks count as food (calories), not as drinking water.
        self.add("Orange juice", 10, category="drinks", unit="carton", kcal_per_unit=440)
        self.assertEqual(server.summary()["food_days"], 9)

    def test_eating_what_goes_off_first(self):
        import datetime as dt
        t = dt.date(2027, 1, 1)
        d = lambda n: (t + dt.timedelta(days=n)).isoformat()
        self.assertEqual(server.lasts_days([(10, None)], 2, t), (5.0, 0.0))
        self.assertEqual(server.lasts_days([(4, None), (6, d(2))], 1, t), (7.0, 3.0))
        self.assertEqual(server.lasts_days([(5, d(-1))], 1, t), (0.0, 5.0))
        self.assertEqual(server.lasts_days([(3, d(1)), (3, d(3))], 1, t), (4.0, 2.0))

    def test_multipacks_count_the_whole_pack(self):
        self.assertEqual(server.multipack_total("6 x 330 ml"), (6, 1980.0))
        self.assertIsNone(server.multipack_total("415 g"))
        p = server.product_from("5000000000001", {"product_name_en": "Orange juice", "quantity": "6 x 200 ml",
                                                   "product_quantity": "200", "product_quantity_unit": "ml",
                                                   "nutriments": {"energy-kcal_100g": 45}, "categories_tags": ["en:juices"]})
        self.assertEqual((p["kcal_per_unit"], p["count"], p["category"], p["unit"]), (540, 6, "drinks", "pack"))
        lab = server.parse_label_reply('{"name": "Cola", "size": "6 x 330 ml", "grams": 330, "kcal_100g": 42, "count": 6, '
                                       '"category": "drinks", "unit": "pack"}')
        self.assertEqual(lab["kcal_per_unit"], round(42 * 1980 / 100.0))

    def test_nutrition_label(self):
        r = server.parse_nutrition_reply('{"kcal_100g": 78, "grams": 415, "kcal_serving": 160, "serving_g": 207}')
        self.assertEqual((r["kcal_per_unit"], r["how"]), (324, "78 kcal per 100 g × 415 g = 324 kcal"))
        self.assertEqual(server.parse_nutrition_reply('{"kcal_100g": 120, "grams": null}', grams=400)["kcal_per_unit"], 480)
        self.assertEqual(server.parse_nutrition_reply('{"kcal_100g": null, "kcal_pack": 1010}')["kcal_per_unit"], 1010)
        r = server.parse_nutrition_reply('{"kcal_100g": 45}')   # no weight anywhere: says so rather than guessing
        self.assertIsNone(r["kcal_per_unit"])
        self.assertIsNone(server.parse_nutrition_reply("I can't see a label"))
        self.assertApiError(400, server.api_scan_nutrition, {"image": "/9j/4AAQSkZJRgABAQ=="}, {})   # no AI here

    def test_fill_in_is_checked_then_marked_until_changed(self):
        asked = {1: ["kcal_per_unit", "pack_size", "open_days"], 2: ["kcal_per_unit"]}
        got = server.parse_fill_reply('[{"id": 1, "kcal_per_unit": 320.4, "pack_size": 400, "pack_unit": "g", "open_days": 3}, '
                                      '{"id": 2, "kcal_per_unit": "lots"}, {"id": 3, "kcal_per_unit": 100}]', asked)
        self.assertEqual(got, {1: {"kcal_per_unit": 320, "pack_size": 400, "pack_unit": "g", "open_days": 3}})
        rice = self.add("Rice (1kg)", 1, category="food", unit="bag")
        server.api_ai_fill_apply({"items": [{"id": rice, "kcal_per_unit": 3600, "open_days": 365}]}, {})
        it = self.item(rice)
        self.assertEqual((it["kcal_per_unit"], it["open_days"], it["ai_guessed"]), (3600, 365, "kcal_per_unit,open_days"))
        server.api_item_update({"kcal_per_unit": 3600, "open_days": 365}, {}, str(rice))   # saved unchanged: still marked
        self.assertEqual(self.item(rice)["ai_guessed"], "kcal_per_unit,open_days")
        server.api_item_update({"kcal_per_unit": 3500}, {}, str(rice))                     # changed by hand: not a guess
        self.assertEqual(self.item(rice)["ai_guessed"], "open_days")
        self.assertApiError(400, server.api_ai_fill_apply, {"items": []}, {})


class TestAI(AppTest):
    def test_dates_and_labels(self):
        self.assertEqual(server.read_date_reply("Best before: 2027-03-31."), "2027-03-31")
        self.assertIsNone(server.read_date_reply("NONE"))
        self.assertIsNone(server.read_date_reply("2027-02-30"))
        p = server.parse_label_reply('Here:\n```json\n{"name": "Lentil stew", "size": "800 g", "grams": 800, "kcal_100g": 92, '
                                     '"category": "food", "unit": "tin", "best_before": "2027-06-30"}\n```')
        self.assertEqual((p["name"], p["kcal_per_unit"], p["unit"], p["expiry"], p["from_ai"]),
                         ("Lentil stew (800 g)", 736, "tin", "2027-06-30", True))
        water = server.parse_label_reply('{"name": "Spring water", "grams": 5000, "category": "water", "count": 2}')
        self.assertEqual((water["litres_per_unit"], water["count"]), (5.0, 2))
        odd = server.parse_label_reply('{"name": "Thing", "category": "rockets", "grams": "lots", "unit": "x y z"}')
        self.assertEqual((odd["category"], odd["grams"], odd["unit"]), ("food", None, "pack"))
        self.assertIsNone(server.parse_label_reply("I can't see a product"))

    def test_photos_need_an_ai(self):
        self.assertApiError(400, server.api_scan_date, {"image": "not base64!"}, {})
        self.assertApiError(400, server.api_scan_date, {"image": "aGVsbG8="}, {})        # not a JPEG
        self.assertApiError(400, server.api_scan_date, {"image": "/9j/4AAQSkZJRgABAQ=="}, {})   # no AI anywhere
        self.assertApiError(400, server.api_scan_label, {"image": "/9j/4AAQSkZJRgABAQ=="}, {})

    def test_claude_request(self):
        seen = {}

        def fake(url, body, headers, timeout=60):
            seen.update(url=url, body=body, headers=headers)
            return {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "2027-03-31"}]}
        orig = server._post_json
        server._post_json = fake
        try:
            reply = server.ai_direct("anthropic", "k", "", server.DATE_PROMPT, "QUJD")
        finally:
            server._post_json = orig
        self.assertEqual(server.read_date_reply(reply), "2027-03-31")
        self.assertEqual((seen["url"], seen["body"]["model"]), ("https://api.anthropic.com/v1/messages", "claude-haiku-5-5"))
        img = seen["body"]["messages"][0]["content"][0]
        self.assertEqual((img["type"], img["source"]["media_type"]), ("image", "image/jpeg"))

    def test_choice_of_ai_and_keys_stay_private(self):
        self.assertEqual(server.api_scan_ai_get({}, {})["provider"], "ha")
        self.assertApiError(400, server.api_scan_ai_put, {"provider": "skynet"}, {})
        self.assertApiError(400, server.api_scan_ai_put, {"key_anthropic": "short"}, {})
        key = "sk-ant-api03-" + "A1b2C3d4" * 6
        got = server.api_scan_ai_put({"provider": "anthropic", "key_anthropic": key}, {})
        self.assertEqual((got["provider"], got["keys_set"]), ("anthropic", ["anthropic"]))
        self.assertNotIn(key, json.dumps(server.api_scan_ai_get({}, {})))
        self.assertNotIn(key, json.dumps(server.api_state({}, {}), default=str))
        self.assertNotIn(key.encode(), server.api_backup({}, {}).data)
        server.api_scan_ai_put({"key_anthropic": ""}, {})            # an empty box leaves it
        self.assertEqual(server.api_scan_ai_get({}, {})["keys_set"], ["anthropic"])
        server.api_scan_ai_put({"key_anthropic": None, "provider": "ha"}, {})   # null removes it
        self.assertEqual(server.api_scan_ai_get({}, {})["keys_set"], [])

    def test_keys_stay_out_of_database_copies(self):
        key = "sk-ant-api03-" + "Z9y8X7w6" * 6
        server.api_scan_ai_put({"key_anthropic": key}, {})
        path = server.make_backup("test")
        with open(path, "rb") as f:
            self.assertNotIn(key.encode(), f.read())
        self.assertEqual(server.api_scan_ai_get({}, {})["keys_set"], ["anthropic"])   # still there to use

    def test_spend_and_monthly_limit(self):
        server.DB.execute("DELETE FROM ai_calls")
        server.record_ai("anthropic", "claude-haiku-5-5", "Dads Army best before", {"in": 1500, "out": 40}, True)
        server.record_ai("anthropic", "claude-haiku-5-5", "Dads Army label", {"in": 1600, "out": 200}, False, "busy")
        server.record_ai("ai_task.google_ai_task", "", "Dads Army best before", {}, True)
        server.record_ai("openai", "some-new-model", "Dads Army label", {"in": 1000, "out": 100}, True)
        st = server.ai_stats()
        self.assertEqual((st["calls"], st["ok"], st["failed"], st["tasks"]["dates"], st["tasks"]["labels"]), (4, 3, 1, 2, 1))
        # Tokens are costed even on a failed call; Home Assistant's AI Task isn't costed here; an unknown
        # model is costed on the high side, so the limit still stops it.
        want = (1500 * 0.10 + 40 * 0.50 + 1600 * 0.10 + 200 * 0.50) / 1e6 + (1000 * 3.0 + 100 * 15.0) / 1e6
        self.assertAlmostEqual(st["cost_usd"], want, places=9)
        server.ai_limit_check({"limit_usd": 0})
        server.ai_limit_check({"limit_usd": 1.0})
        self.assertApiError(402, server.ai_limit_check, {"limit_usd": 0.0001})
        server.api_scan_ai_put({"limit_usd": 5}, {})
        self.assertEqual(server.api_scan_ai_get({}, {})["stats"]["limit_usd"], 5.0)

    def test_errors_in_plain_words(self):
        f = server.friendly_ai_error
        self.assertIn("busy right now", f("ai_task.google_ai_task", '{"error": {"code": 503, "message": "high demand"}}'))
        self.assertIn("no credit left", f("ai_task.openai_ai_task", "Insufficient funds"))
        self.assertIn("allowance is used up", f("google", "HTTP 429: RESOURCE_EXHAUSTED quota"))
        self.assertIn("didn't accept the API key", f("anthropic", "HTTP 401: invalid x-api-key"))
        self.assertIn("took too long", f("google", "The read operation timed out"))
        self.assertTrue(f("google", "error id 15030").startswith("Gemini couldn't answer"))
        self.assertNotIn("abcdef123456", f("openai", "Incorrect key: sk-abcdef123456****"))


class TestOfflineList(AppTest):
    def export(self, uk_rows):
        """A small stand-in for Open Food Facts' export: tab-separated, gzipped, with extra columns."""
        import gzip
        import os
        cols = ["code", "url", "product_name", "brands", "quantity", "product_quantity", "categories_tags",
                "countries_en", "energy-kcal_100g", "other"]
        lines = ["\t".join(cols)]
        for i in range(uk_rows):
            lines.append("\t".join(["50%011d" % i, "", "Baked beans %d" % i, "Heinz", "415 g", "415", "en:canned-foods",
                                    "United Kingdom", "78", "x"]))
        lines.append("\t".join(["3000000000001", "", "Pâte à tartiner", "Bovetti", "350 g", "350", "", "France", "617", "x"]))
        lines.append("\t".join(["0012345678905", "", "Root beer", "Brand", "6 x 330 ml", "1980", "", "United States,United Kingdom", "40", "x"]))
        lines.append("short\tline")   # a damaged line is skipped
        path = os.path.join(self.dir, "export.csv.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return "file://" + path

    def test_build_and_look_up(self):
        server.offline_save(enabled=True)
        self.assertTrue(server.build_offline(self.export(1500)))
        st = server.offline_status()
        self.assertEqual((st["count"], st["error"], st["building"]), (1501, "", False))   # the French one left out
        server.OFF_CACHE.clear()
        server.http_get = lambda url, **kw: self.fail("looked up online: " + url)
        p = server.off_product("50" + "%011d" % 7)
        self.assertEqual((p["name"], p["kcal_per_unit"], p["unit"], p["offline"]), ("Heinz Baked beans 7 (415 g)", 324, "tin", True))
        self.assertEqual(server.offline_lookup("012345678905")["product_name"], "Root beer")   # a 12-digit UPC finds its EAN-13
        self.assertIsNone(server.offline_lookup("3000000000001"))
        self.assertFalse(server.build_offline(self.export(10)))        # a broken download keeps the old list
        self.assertEqual(server.offline_status()["count"], 1501)
        server.offline_save(enabled=False)
        self.assertIsNone(server.offline_lookup("50" + "%011d" % 7))

    def test_when_it_updates(self):
        import datetime as dt
        night, day = dt.datetime(2026, 12, 20, 3), dt.datetime(2026, 12, 20, 14)
        cfg = {"enabled": True, "built_at": None, "tried_at": None}
        self.assertTrue(server.offline_due(cfg, day))                  # never built: straight away
        cfg["built_at"] = "2026-11-01T03:00:00"
        self.assertTrue(server.offline_due(cfg, night))                # a month on, at night
        self.assertFalse(server.offline_due(cfg, day))                 # but not in the day
        cfg["tried_at"] = "2026-12-20T02:30:00"
        self.assertFalse(server.offline_due(cfg, night))               # tried tonight already
