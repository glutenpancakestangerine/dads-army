"""The warnings feeds: what's picked out of each, that nothing is fetched while they're off, that a failing
feed keeps its last good result, and that where you live is never sent anywhere."""
import datetime as dt

from feeds import FakeFeeds, NOW, fires, gdacs, govalerts, met
from support import AppTest, server

HOME = (54.486, -0.615)   # Whitby


class ParseTest(AppTest):
    def test_met_office_picks_your_region(self):
        rows = server.parse_met(met(), "Yorkshire & Humber")
        self.assertEqual([r["severity"] for r in rows], [2])
        self.assertIn("wind", rows[0]["title"].lower())
        self.assertEqual(len(server.parse_met(met(), "")), 2)

    def test_emergency_alerts_tests_are_low_key(self):
        rows = dict((r["area"], r) for r in server.parse_govalerts(govalerts(), NOW))
        self.assertEqual((rows["North Yorkshire"]["severity"], rows["North Yorkshire"]["level"]), (3, "Emergency Alert"))
        self.assertEqual((rows["England"]["severity"], rows["England"]["level"]), (1, "Test"))

    def test_disasters_only_nearby(self):
        home = {"lat": HOME[0], "lon": HOME[1]}
        rows = server.parse_gdacs(gdacs(), home, 1500)
        self.assertEqual([r["title"] for r in rows], ["Orange earthquake in Norway"])

    def test_fire_detections(self):
        pts = server.parse_firms(fires())
        self.assertEqual(len(pts), 3)
        self.assertAlmostEqual(pts[0][0], 54.52)

    def test_feeds_that_arent_xml_are_refused_safely(self):
        with self.assertRaises(Exception):
            server.parse_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><feed>&a;</feed>')


class WarningsRunTest(AppTest):
    def setUp(self):
        super().setUp()
        self.feeds = FakeFeeds()
        server.FEED_URLS.update(self.feeds.urls())

    def tearDown(self):
        self.feeds.close()
        super().tearDown()

    def switch_on(self, **kw):
        body = {"on": True, "lat": HOME[0], "lon": HOME[1],
                "sources": {"metoffice": True, "floods": True, "govalerts": True, "gdacs": True, "ukhsa": True,
                            "who": True, "fires": True}}
        body["sources"].update(dict((k, False) for k in server.LIVE_KEYS))   # those are in test_live
        body.update(kw)
        server.api_warnings_set(body, {})

    def test_nothing_is_fetched_while_warnings_are_off(self):
        server.warnings_run()
        self.assertEqual(self.feeds.log, [])

    def test_warnings_near_you(self):
        self.switch_on()
        server.warnings_run()
        w = server.warn_public()
        sources = set(i["source"] for i in w["items"])
        self.assertTrue({"metoffice", "floods", "govalerts", "fires"} <= sources, sources)
        floods = [i for i in w["items"] if i["source"] == "floods"]
        self.assertEqual([f["title"] for f in floods], ["Flood alert: River Esk at Sleights"])
        self.assertTrue(all(s["ok"] for s in w["sources"].values()), w["sources"])

    def test_where_you_live_is_never_sent(self):
        self.switch_on()
        server.warnings_run()
        self.assertTrue(self.feeds.log)
        for req in self.feeds.log:
            for needle in ("54.4", "54.5", "0.61", "0.62", "lat", "lon", "postcode"):
                self.assertNotIn(needle, req["path"].lower(), req["path"])
            self.assertTrue(req["ua"].startswith("DadsArmy/"), req["ua"])
            self.assertNotIn("Cookie", req["headers"])
            self.assertNotIn("Referer", req["headers"])

    def test_a_failing_feed_keeps_its_last_result(self):
        self.switch_on()
        server.warnings_run()
        before = [i for i in server.warn_public()["items"] if i["source"] == "metoffice"]
        self.feeds.broken["met"] = 500
        server.warnings_run()
        w = server.warn_public()
        self.assertFalse(w["sources"]["metoffice"]["ok"])
        self.assertIn("500", w["sources"]["metoffice"]["error"])
        self.assertEqual([i for i in w["items"] if i["source"] == "metoffice"], before)

    def test_a_new_warning_is_news_only_once(self):
        server.HA_TOKEN = ""
        self.switch_on()
        server.warnings_run()
        seen = dict(server.WARN_STATE["seen"])
        server.warnings_run()
        self.assertEqual(set(server.WARN_STATE["seen"]), set(seen))

    def test_no_location_means_no_local_feeds(self):
        self.switch_on(lat=None, lon=None)
        server.warnings_run()
        w = server.warn_public()
        self.assertIn("location", w["sources"]["floods"]["error"])
        self.assertTrue(w["sources"]["metoffice"]["ok"])
        self.assertFalse([r for r in self.feeds.log if "floods" in r["path"]])

    def test_dates_in_the_past_day(self):
        self.switch_on()
        server.warnings_run()
        checked = server.warn_public()["checked_at"]
        self.assertTrue(checked.startswith(dt.date.today().isoformat()))
