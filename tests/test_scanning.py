"""Scanning (1.12.0): barcodes, what Open Food Facts and the AI give back, pack sizes, using part of one,
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
        self.assertEqual(sorted(c for it in backup["items"] for c in it["barcodes"]), ["5000157024671", "5010251605466"])
        server.api_restore(backup, {})
        beans_now = [it for it in server.all_items() if it["name"] == "Baked beans"][0]["id"]
        self.assertEqual(server.api_scan_barcode({}, {"code": ["5010251605466"]})["item_id"], beans_now)
        server.api_item_delete({}, {}, str(beans_now))   # the item's barcodes go with it
        server.OFF_CACHE["5010251605466"] = None          # (and Open Food Facts doesn't know it)
        self.assertIsNone(server.api_scan_barcode({}, {"code": ["5010251605466"]})["item_id"])

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
