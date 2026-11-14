"""Input checking: numbers, dates, ids and text are strictly validated, and the web server refuses anything
that isn't a JSON object."""
import json

from support import AppServer, AppTest, server


class CleanNumTest(AppTest):
    def test_plain_numbers_are_accepted(self):
        self.assertEqual(server.clean_num(3), 3)
        self.assertEqual(server.clean_num("2.5"), 2.5)
        self.assertEqual(server.clean_num(" 7 "), 7)
        self.assertEqual(server.clean_num(None, 4), 4)
        self.assertEqual(server.clean_num("", 4), 4)

    def test_odd_numbers_are_refused(self):
        for bad in (True, "1e3", "1_000", "nan", "inf", "0x10", "١٢", "5 5", "+5", [1], {"a": 1}, float("nan"),
                    float("inf"), "12" * 20):
            self.assertApiError(400, server.clean_num, bad, 0, 0, 1e7, "Quantity")

    def test_out_of_range_is_refused_not_quietly_changed(self):
        e = self.assertApiError(400, server.clean_num, -1, 0, 0, 100, "Quantity")
        self.assertIn("less than zero", e.message)
        e = self.assertApiError(400, server.clean_num, 101, 0, 0, 100, "Target")
        self.assertIn("between 0 and 100", e.message)


class CleanDateAndIdTest(AppTest):
    def test_dates(self):
        self.assertEqual(server.clean_date("2027-03-31"), "2027-03-31")
        self.assertIsNone(server.clean_date(""))
        for bad in ("2027-02-30", "31/03/2027", "2027-3-31", "２０２７-03-31", "2027-03-31\n2027", 20270331,
                    "0001-01-01", "9999-12-31"):
            self.assertApiError(400, server.clean_date, bad)

    def test_ids(self):
        self.assertEqual(server.as_int_id(5), 5)
        self.assertEqual(server.as_int_id("12"), 12)
        for bad in (True, 0, -3, 1.5, "1.0", "1e3", "", None, "12a", " 3", [1], 2 ** 60):
            self.assertApiError(400, server.as_int_id, bad)

    def test_text_drops_control_characters(self):
        self.assertEqual(server.clean_text("Tins\x00 of\x1b beans\x7f", 50), "Tins of beans")
        self.assertEqual(server.clean_text("Line one\nline two", 50), "Line one\nline two")
        self.assertApiError(400, server.clean_text, {"x": 1}, 50)
        self.assertApiError(400, server.clean_text, float("nan"), 50)


class ItemInputTest(AppTest):
    def test_item_with_a_bad_quantity_is_refused_and_nothing_is_added(self):
        self.assertApiError(400, server.api_item_create, {"name": "Beans", "qty": "lots"}, {})
        self.assertApiError(400, server.api_item_create, {"name": "Beans", "qty": -2}, {})
        self.assertApiError(400, server.api_item_create, {"name": "Beans", "expiry": "next week"}, {})
        self.assertEqual(server.all_items(), [])

    def test_using_more_than_there_is_and_bad_ids(self):
        i = self.add("Beans", 2)
        self.assertApiError(400, server.api_use, {"qty": 0}, {}, str(i))
        self.assertApiError(400, server.api_use, {"qty": "1e2"}, {}, str(i))
        self.assertApiError(404, server.api_use, {"qty": 1}, {}, "999")
        self.assertEqual(server.api_use({"qty": 5}, {}, str(i))["used"], 2)

    def test_settings_are_checked(self):
        self.assertApiError(400, server.api_settings, {"adults": 500}, {})
        self.assertApiError(400, server.api_settings, {"dogs": -1}, {})
        self.assertApiError(400, server.api_settings, {"warn_by_cat": {"medical": 0.5}}, {})
        self.assertApiError(400, server.api_settings, {"warn_by_cat": {"spaceships": 30}}, {})
        self.assertApiError(400, server.api_settings, {"warn_by_cat": [90]}, {})
        self.assertEqual(server.get_settings()["adults"], 2)

    def test_own_places_need_real_coordinates(self):
        self.assertApiError(400, server.api_places, {"places": [{"name": "Gran's", "lat": True, "lon": 1}]}, {})
        self.assertApiError(400, server.api_places, {"places": [{"name": "Gran's", "lat": 95, "lon": 1}]}, {})
        out = server.api_places({"places": [{"name": "Gran's", "lat": "54.12345", "lon": "-1.54321",
                                             "hazards": "flood"}]}, {})
        p = server.own_places()[0]
        self.assertEqual((p["lat"], p["lon"], p["hazards"]), (54.12345, -1.54321, []))
        self.assertTrue(out)


class HttpTest(AppTest):
    def setUp(self):
        super().setUp()
        self.web = AppServer()

    def tearDown(self):
        self.web.close()
        super().tearDown()

    def test_writes_must_be_json(self):
        status, _ = self.web.json("POST", "/api/items", {"name": "Beans"}, ctype="application/x-www-form-urlencoded")
        self.assertEqual(status, 415)
        status, _ = self.web.json("POST", "/api/items", raw=b"name=Beans")
        self.assertEqual(status, 400)
        status, _ = self.web.json("POST", "/api/items", raw=json.dumps(["Beans"]).encode())
        self.assertEqual(status, 400)
        self.assertEqual(server.all_items(), [])

    def test_errors_come_back_as_json_with_a_message(self):
        status, out = self.web.json("POST", "/api/items", {"name": "Beans", "qty": True})
        self.assertEqual(status, 400)
        self.assertIn("number", out["error"])
        status, out = self.web.json("PUT", "/api/items/abc", {"name": "x"})
        self.assertEqual(status, 404)
        status, out = self.web.json("GET", "/api/history?days=abc")
        self.assertEqual(status, 400)

    def test_security_headers(self):
        status, _, headers = self.web.call("GET", "/api/health", ctype=None)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
