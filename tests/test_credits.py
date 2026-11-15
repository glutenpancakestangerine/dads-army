"""Credits: the thank-you and the names from CREDITS.md, and the "Check GitHub for new names" button.
The app's own copy works offline; GitHub is only asked when someone taps the button."""
import json
import os
import tempfile

from feeds import FakeFeeds
from support import AppTest, server

NEWER = """# Credits

<!-- notes for editors, never shown -->

Thank you.

Everyone here wants households across the UK to be ready.

## Built by

- Parker Veese Development (@parkerveese-cloud): started Dads Army
- Jane Smith (@janesmith): tested the warnings

## Open data and maps

- Met Office: weather warnings
"""

PEOPLE = [
    {"login": "parkerveese-cloud", "type": "User", "contributions": 40},   # already named, so not repeated
    {"login": "JaneSmith", "type": "User", "contributions": 3},            # named, in another case
    {"login": "newcomer", "type": "User", "contributions": 1},
    {"login": "dependabot[bot]", "type": "Bot", "contributions": 9},
    {"login": "bad login!", "type": "User", "contributions": 2},
]


class ParseTest(AppTest):

    def test_the_file_that_ships_with_the_app(self):
        c = server.credits_view()
        self.assertEqual(c["source"], "app")
        self.assertEqual(c["message"][0], "Thank you.")
        self.assertIn("households across the UK", " ".join(c["message"]))
        self.assertNotIn("How this file works", json.dumps(c))   # the editors' notes stay hidden
        titles = [g["title"] for g in c["groups"]]
        self.assertEqual(titles, ["Built by", "Open data and maps"])
        first = c["groups"][0]["people"][0]
        self.assertEqual(first["name"], "Parker Veese Development")
        self.assertEqual(first["handle"], "parkerveese-cloud")
        self.assertEqual(first["url"], "https://github.com/parkerveese-cloud")
        self.assertTrue(first["note"].startswith("started Dads Army"))
        osm = c["groups"][1]["people"][0]
        self.assertEqual(osm["name"], "OpenStreetMap contributors")
        self.assertEqual(osm["url"], "https://www.openstreetmap.org/copyright")
        self.assertIn("Open Database Licence", osm["note"])
        self.assertEqual(c["count"], sum(len(g["people"]) for g in c["groups"]))
        self.assertEqual(c["edit_url"], server.CREDITS_EDIT)

    def test_ways_of_writing_a_name(self):
        e = server._credit_entry
        self.assertEqual(e("@jane: tests"), {"name": "@jane", "handle": "jane", "url": "https://github.com/jane", "note": "tests"})
        self.assertEqual(e("Jane Smith"), {"name": "Jane Smith", "handle": None, "url": None, "note": ""})
        self.assertEqual(e("**Jane** — ideas")["note"], "ideas")
        self.assertEqual(e("**Jane** — ideas")["name"], "Jane")
        self.assertEqual(e("Mary-Jane Lee - testing")["name"], "Mary-Jane Lee")
        self.assertIsNone(e("Jane (jane@example.com)")["handle"])   # an email address isn't a GitHub name
        self.assertEqual(e("[Jane](https://jane.example): design")["url"], "https://jane.example")
        bad = e("[click](javascript:alert(1))")   # only https links become links
        self.assertIsNone(bad["url"])
        self.assertIsNone(e("** **"))
        self.assertEqual(len(e("x" * 500)["name"]), 120)

    def test_odd_files(self):
        p = server.parse_credits("- Someone\n\n---\n\nNo heading yet <!-- an unfinished comment\n## Hidden\n- Nobody")
        self.assertEqual(p["message"], [])
        self.assertEqual(p["groups"][0]["title"], "Contributors")
        self.assertEqual([x["name"] for x in p["groups"][0]["people"]], ["Someone"])
        self.assertEqual(p["groups"][0]["about"], ["No heading yet"])
        self.assertEqual(server.parse_credits("")["groups"], [])
        many = server.parse_credits("## A\n" + "\n".join("- Person %d" % i for i in range(400)))
        self.assertEqual(len(many["groups"][0]["people"]), 300)

    def test_github_contributors(self):
        people = server.parse_contributors(PEOPLE + ["junk", {"login": "t", "type": "User", "contributions": True}])
        self.assertEqual([p["login"] for p in people], ["parkerveese-cloud", "JaneSmith", "newcomer"])
        with self.assertRaises(ValueError):
            server.parse_contributors({"message": "API rate limit exceeded"})
        merged = server.credits_merge(server.parse_credits(NEWER), people)
        self.assertEqual([g["title"] for g in merged["groups"]], ["Built by", "Code on GitHub", "Open data and maps"])
        self.assertEqual(merged["groups"][1]["people"],
                         [{"name": "@newcomer", "handle": "newcomer", "url": "https://github.com/newcomer", "note": "1 change"}])

    def test_no_file_still_says_thank_you(self):
        old = server.CREDITS_FILE
        server.CREDITS_FILE = os.path.join(tempfile.gettempdir(), "no-such-credits.md")
        try:
            c = server.credits_view()
        finally:
            server.CREDITS_FILE = old
        self.assertEqual(c["message"], [server.CREDITS_FALLBACK])
        self.assertEqual(c["groups"], [])


class CheckTest(AppTest):

    def setUp(self):
        super().setUp()
        self.feeds = FakeFeeds({"credits": (lambda: NEWER.encode(), "text/markdown"),
                                "contributors": (lambda: json.dumps(PEOPLE).encode(), "application/json")})
        server.FEED_URLS.update({"credits": self.feeds.base + "credits", "contributors": self.feeds.base + "contributors"})

    def tearDown(self):
        self.feeds.close()
        super().tearDown()

    def test_opening_credits_asks_nobody(self):
        server.api_credits({}, {})
        self.assertEqual(self.feeds.log, [])

    def test_check_brings_new_names(self):
        res = server.api_credits_check({}, {})
        self.assertTrue(res["ok"])
        c = res["credits"]
        self.assertEqual(c["source"], "github")
        self.assertIsNone(c["check_error"])
        names = [p["name"] for g in c["groups"] for p in g["people"]]
        self.assertIn("Jane Smith", names)
        self.assertIn("@newcomer", names)
        self.assertNotIn("@JaneSmith", names)
        self.assertNotIn("@dependabot[bot]", names)
        # Two fixed addresses, with only Dads Army's name: no cookies, no referrer, nothing about the household.
        self.assertEqual(sorted(r["path"] for r in self.feeds.log), ["/contributors", "/credits"])
        for r in self.feeds.log:
            self.assertTrue(r["ua"].startswith("DadsArmy/"))
            self.assertFalse(set(h.lower() for h in r["headers"]) & {"cookie", "referer", "authorization"})
        # Kept for next time, and still shown with no internet.
        server.FEED_URLS.update({"credits": "http://127.0.0.1:9/x", "contributors": "http://127.0.0.1:9/y"})
        self.assertIn("Jane Smith", json.dumps(server.api_credits({}, {})))

    def test_a_failed_check_keeps_what_it_had(self):
        server.api_credits_check({}, {})
        self.feeds.broken.update({"credits": 500, "contributors": 403})
        res = server.api_credits_check({}, {})
        self.assertFalse(res["ok"])
        c = res["credits"]
        self.assertIn("the credits list: the site answered 500", c["check_error"])
        self.assertIn("code contributors: the site answered 403", c["check_error"])
        names = [p["name"] for g in c["groups"] for p in g["people"]]
        self.assertIn("Jane Smith", names)
        self.assertIn("@newcomer", names)

    def test_a_page_with_no_names_is_not_used(self):
        self.feeds.routes["credits"] = (lambda: b"<html><body>Sign in</body></html>", "text/html")
        res = server.api_credits_check({}, {})
        self.assertFalse(res["ok"])
        self.assertEqual(res["credits"]["source"], "app")
        self.assertEqual(res["credits"]["message"][0], "Thank you.")

    def test_an_update_brings_its_own_copy(self):
        server.api_credits_check({}, {})
        with server.tx() as db:
            cache = server.credits_cache()
            cache["version"] = "0.0.1"   # checked on an older version
            server.set_setting_raw(db, "credits_cache", cache)
        with server.LOCK:
            c = server.credits_view()
        self.assertEqual(c["source"], "app")
        names = [p["name"] for g in c["groups"] for p in g["people"]]
        self.assertNotIn("Jane Smith", names)
        self.assertIn("@newcomer", names)   # GitHub's code contributors are still known

    def test_not_in_backups(self):
        server.api_credits_check({}, {})
        backup = server.api_backup({}, {}).data
        backup = backup.decode("utf-8") if isinstance(backup, bytes) else backup
        self.assertIn('"settings"', backup)
        self.assertNotIn("credits", backup)
