"""Stand-ins for the public feeds, served from this machine. Each records the requests it gets, so the
tests can check that nothing about where you live is ever sent."""
import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOW = dt.datetime.now(dt.timezone.utc)


def ago(**kw):
    return NOW - dt.timedelta(**kw)


def rfc(d):
    return d.strftime("%a, %d %b %Y %H:%M:%S GMT")


def met():
    items = [("Amber warning of wind affecting Yorkshire &amp; Humber",
              "Amber warning of wind affecting Yorkshire &amp; Humber: North Yorkshire valid from 0600 Fri to 2359 Fri", "w1"),
             ("Yellow warning of rain affecting London &amp; South East England",
              "Yellow warning of rain affecting London &amp; South East England: Kent valid from 0000 Sat", "w2")]
    body = "".join("<item><title>%s</title><link>https://www.metoffice.gov.uk/weather/warnings-and-advice/uk-warnings#?id=%s"
                   "</link><description>%s</description><pubDate>%s</pubDate><guid isPermaLink=\"false\">%s</guid></item>"
                   % (t, g, d, rfc(ago(hours=2)), g) for t, d, g in items)
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Met Office</title>%s'
            '</channel></rss>' % body).encode()


FLOODS = {"items": [
    {"floodAreaID": "NEAR1", "severityLevel": 3, "severity": "Flood alert", "description": "River Esk at Sleights",
     "message": "River levels are rising.", "floodArea": {"county": "North Yorkshire", "notation": "NEAR1"},
     "timeRaised": ago(hours=1).strftime("%Y-%m-%dT%H:%M:%S")},
    {"floodAreaID": "FAR1", "severityLevel": 1, "severity": "Severe flood warning", "description": "Thames at Putney",
     "message": "Danger to life.", "floodArea": {"county": "Greater London", "notation": "FAR1"},
     "timeRaised": ago(hours=2).strftime("%Y-%m-%dT%H:%M:%S")}]}
CENTRES = {"NEAR1": (54.46, -0.67), "FAR1": (51.46, -0.22)}


def govalerts():
    def entry(eid, area, sent, stopped, text):
        stamp = lambda d: d.strftime("%Y-%m-%d %H:%M") + " GMT"   # noqa: E731
        summ = "Alert area: %s. Sent: x [%s]." % (area, stamp(sent)) + (" Stopped: y [%s]" % stamp(stopped) if stopped else "")
        return ("<entry><id>https://www.gov.uk/alerts/%s</id><title>%s</title><updated>%s</updated>"
                "<content type=\"xhtml\"><div xmlns=\"http://www.w3.org/1999/xhtml\"><p>%s</p></div></content>"
                "<link href=\"https://www.gov.uk/alerts/%s\"/><summary>%s</summary><published>%s</published></entry>"
                % (eid, area, sent.isoformat(), text, eid, summ, sent.isoformat()))
    return ('<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Alerts</title>' +
            entry("live", "North Yorkshire", ago(hours=1), None, "Severe flooding. Leave the area now if it is safe.") +
            entry("test", "England", ago(hours=3), ago(minutes=10), "This is a test of Emergency Alerts. You do not need to take any action.") +
            '</feed>').encode()


def gdacs():
    def item(guid, title, lvl, lat, lon):
        return ('<item><title>%s</title><description>%s</description><link>https://www.gdacs.org/report.aspx?eventid=%s</link>'
                '<pubDate>%s</pubDate><gdacs:iscurrent>true</gdacs:iscurrent><gdacs:alertlevel>%s</gdacs:alertlevel>'
                '<gdacs:country>X</gdacs:country><guid isPermaLink="false">%s</guid><georss:point>%s %s</georss:point></item>'
                % (title, title, guid, rfc(ago(hours=3)), lvl, guid, lat, lon))
    return ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0" xmlns:gdacs="http://www.gdacs.org" '
            'xmlns:georss="http://www.georss.org/georss"><channel>' +
            item("EQ1", "Orange earthquake in Norway", "Orange", 60.4, 5.3) +
            item("TC1", "Red tropical cyclone in the Philippines", "Red", 13.0, 122.0) + '</channel></rss>').encode()


def ukhsa():
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>UKHSA</title>'
            '<entry><id>tag:x,2005:cold</id><updated>%s</updated><link rel="alternate" type="text/html" '
            'href="https://www.gov.uk/government/news/cold"/><title>Cold-health alert</title><summary>Cold</summary>'
            '</entry></feed>' % ago(days=1).isoformat()).encode()


def who():
    return json.dumps({"value": [{"UrlName": "2026-DON625", "PublicationDateAndTime": ago(days=3).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  "UseOverrideTitle": False, "Title": "Ebola disease - DRC"}]}).encode()


def fires():
    d = NOW.strftime("%Y-%m-%d")
    return ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight\n"
            "54.52,-0.55,330.1,0.4,0.4,%s,0124,N20,nominal,2.0NRT,280.1,5.2,N\n"
            "54.521,-0.552,331.0,0.4,0.4,%s,0124,N20,high,2.0NRT,281.0,7.9,N\n"
            "60.1,5.3,320.0,0.4,0.4,%s,0124,N20,high,2.0NRT,280.0,3.0,N\n" % (d, d, d)).encode()


def fires_modis():
    return b"latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,confidence,version,bright_t31,frp,daynight\n"


class FakeFeeds(object):
    """Serves each feed at /<key>. EXTRA lets a test add more (the live information feeds)."""

    def __init__(self, extra=None):
        self.log, self.broken = [], {}
        self.routes = {"met": (met, "application/xml"), "floods": (lambda: json.dumps(FLOODS).encode(), "application/json"),
                       "govalerts": (govalerts, "application/xml"), "gdacs": (gdacs, "application/xml"),
                       "ukhsa": (ukhsa, "application/xml"), "who": (who, "application/json"),
                       "fires": (fires, "text/csv"), "fires_modis": (fires_modis, "text/csv")}
        self.routes.update(extra or {})
        feeds = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                feeds.log.append({"path": self.path, "ua": self.headers.get("User-Agent", ""),
                                  "headers": dict(self.headers)})
                key = self.path.strip("/").split("/")[0].split("?")[0]
                if key in feeds.broken:
                    return self.send(feeds.broken[key], b"broken", "text/plain")
                if key == "floodarea":
                    nid = self.path.rsplit("/", 1)[1]
                    if nid not in CENTRES:
                        return self.send(404, b"{}", "application/json")
                    lat, lon = CENTRES[nid]
                    return self.send(200, json.dumps({"items": {"lat": lat, "long": lon}}).encode(), "application/json")
                if key not in feeds.routes:
                    return self.send(404, b"no", "text/plain")
                fn, ctype = feeds.routes[key]
                self.send(200, fn(), ctype)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.base = "http://127.0.0.1:%d/" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def urls(self):
        b = self.base
        return {"metoffice": b + "met", "floods": b + "floods", "floodarea": b + "floodarea/{id}",
                "govalerts": b + "govalerts", "gdacs": b + "gdacs", "ukhsa": b + "ukhsa", "who": b + "who",
                "fires": b + "fires", "fires_modis": b + "fires_modis"}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
