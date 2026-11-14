"""Keeping Home Assistant up to date: the sensors, "ran out" events (which aren't lost while Home Assistant
can't be reached), a Home Assistant restart, and map points that are no longer wanted."""
from support import AppTest, FakeHA, server


class HomeAssistantTest(AppTest):
    def setUp(self):
        super().setUp()
        self.ha = FakeHA()
        server.HA_TOKEN = "test-token"
        server.HA_API = self.ha.api
        self.state = server.ha_state_new()

    def tearDown(self):
        self.ha.close()
        super().tearDown()

    def once(self):
        return server.ha_once(self.state)

    def test_sensors_are_published(self):
        self.add("Rice", 2, None, category="food", kcal_per_unit=4400, target_qty=4)
        self.assertTrue(self.once())
        st = self.ha.states
        for eid in ("sensor.dads_army_hold_out", "sensor.dads_army_readiness", "sensor.dads_army_low_stock",
                    "sensor.dads_army_alert_level", "sensor.dads_army_resilience", "binary_sensor.dads_army_attention"):
            self.assertIn(eid, st)
        self.assertEqual(st["sensor.dads_army_hold_out"]["state"], "0")   # food for 2 days, but no water
        self.assertEqual(st["sensor.dads_army_low_stock"]["state"], "1")

    def test_nothing_is_sent_twice(self):
        self.once()
        n = len(self.ha.requests)
        self.once()
        posts = [r for r in self.ha.requests[n:] if r[0] == "POST" and r[1].startswith("/api/states/")]
        self.assertEqual(posts, [])

    def test_a_restart_of_home_assistant_gets_everything_again(self):
        self.once()
        self.ha.states.clear()          # Home Assistant restarted and forgot them
        self.once()
        self.assertIn("sensor.dads_army_hold_out", self.ha.states)

    def test_ran_out_event(self):
        i = self.add("Beans", 1, unit="tin", target_qty=4)
        self.once()
        server.api_use({"qty": 1}, {}, str(i))
        self.once()
        ev = self.ha.events_of("dads_army_ran_out")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["names"], "Beans")
        self.assertIn("on the supply run", ev[0]["message"])

    def test_ran_out_while_home_assistant_was_down_is_sent_later(self):
        i = self.add("Beans", 1)
        j = self.add("Rice", 2)
        self.once()
        self.ha.down = True
        server.api_use({"qty": 1}, {}, str(i))
        self.assertFalse(self.once())
        server.api_use({"qty": 2}, {}, str(j))
        self.assertFalse(self.once())
        self.assertEqual(self.ha.events_of("dads_army_ran_out"), [])
        self.ha.down = False
        self.assertTrue(self.once())
        ev = self.ha.events_of("dads_army_ran_out")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["count"], 2)
        self.assertEqual(ev[0]["names"], "Beans and Rice")
        self.once()
        self.assertEqual(len(self.ha.events_of("dads_army_ran_out")), 1)   # told once only

    def test_restocked_before_home_assistant_was_back_isnt_sent(self):
        i = self.add("Beans", 1)
        self.once()
        self.ha.down = True
        server.api_use({"qty": 1}, {}, str(i))
        self.once()
        self.stock(i, 6)
        self.ha.down = False
        self.once()
        self.assertEqual(self.ha.events_of("dads_army_ran_out"), [])

    def test_a_restore_isnt_things_running_out(self):
        self.add("Beans", 1)
        self.once()
        server.api_restore({"app": "dadsarmy", "items": [{"name": "Beans", "batches": []}]}, {})
        self.once()
        self.assertEqual(self.ha.events_of("dads_army_ran_out"), [])

    def test_map_points_no_longer_wanted_are_taken_off(self):
        server.api_warnings_set({"lat": 54.486, "lon": -0.615}, {})
        server.api_places({"places": [{"name": "Gran's", "lat": 54.3, "lon": -0.5, "kind": "family"}]}, {})
        self.once()
        own = [e for e in self.ha.states if e.startswith("geo_location.dads_army_own_")]
        self.assertEqual(len(own), 1)
        server.api_places({"places": []}, {})
        self.once()
        self.assertIn(own[0], self.ha.deleted)
        self.assertNotIn(own[0], self.ha.states)

    def test_history_is_filled_in_from_home_assistant_once(self):
        import datetime as dt
        day = lambda n: (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).replace(hour=12).isoformat()  # noqa: E731
        self.ha.history = [
            [{"entity_id": "sensor.dads_army_food_days", "state": "4.5", "last_changed": day(5)},
             {"state": "3", "last_changed": day(3)}, {"state": "unavailable", "last_changed": day(2)}],
            [{"entity_id": "sensor.dads_army_water_days", "state": "2", "last_changed": day(4)}],
            [{"entity_id": "sensor.somebody_else", "state": "99", "last_changed": day(4)}]]
        self.once()
        rows = dict((r["day"], r) for r in server.api_history({}, {"days": ["30"]})["rows"])
        d = lambda n: (dt.date.today() - dt.timedelta(days=n)).isoformat()  # noqa: E731
        self.assertEqual([rows[d(n)]["food_days"] for n in (5, 4, 3, 2, 1)], [4.5, 4.5, 3, 3, 3])
        self.assertEqual(rows[d(5)]["water_days"], -1)      # not known yet that day
        self.assertEqual(rows[d(4)]["water_days"], 2)
        self.assertNotIn(d(0), [k for k, r in rows.items() if r["water_days"] == -1])
        n = len([r for r in self.ha.requests if "/history/period/" in r[1]])
        self.once()
        self.assertEqual(len([r for r in self.ha.requests if "/history/period/" in r[1]]), n)

    def test_the_alert_level_event_only_fires_on_a_change(self):
        self.once()
        self.once()
        self.assertEqual(self.ha.events_of("dads_army_alert_level"), [])
