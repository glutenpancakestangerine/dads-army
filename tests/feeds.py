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


def places():
    """Home's area, for which Emergency Alerts count (postcodes.io's reverse lookup)."""
    return json.dumps({"status": 200, "result": [{"admin_county": "North Yorkshire", "admin_district": "Scarborough",
                                                  "region": "Yorkshire and The Humber", "country": "England"}]}).encode()


class FakeFeeds(object):
    """Serves each feed at /<key>. EXTRA lets a test add more (the live information feeds)."""

    def __init__(self, extra=None):
        self.log, self.broken = [], {}
        self.routes = {"met": (met, "application/xml"), "floods": (lambda: json.dumps(FLOODS).encode(), "application/json"),
                       "govalerts": (govalerts, "application/xml"), "gdacs": (gdacs, "application/xml"),
                       "ukhsa": (ukhsa, "application/xml"), "who": (who, "application/json"),
                       "fires": (fires, "text/csv"), "fires_modis": (fires_modis, "text/csv"),
                       "places": (places, "application/json")}
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
                "fires": b + "fires", "fires_modis": b + "fires_modis", "places": b + "places"}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# -- More of the wider picture (1.15.0): stand-ins for the threat level, NCSC, FCDO, the drought report, the
# flood guidance statement, rain gauges, boreholes, carbon intensity, frequency, margins and water incidents.
def threat():
    return ('<?xml version="1.0"?><rss version="2.0"><channel><lastBuildDate>%s</lastBuildDate><item>'
            '<title>Current national threat level is SUBSTANTIAL</title><description>The threat to the UK (England, '
            'Wales, Scotland and Northern Ireland) from terrorism is SUBSTANTIAL. The threat to Northern Ireland from '
            'Northern Ireland-related terrorism is SUBSTANTIAL.</description></item></channel></rss>'
            % rfc(ago(days=200))).encode()


def ncsc():
    def item(title, when):
        return ("<item><title>%s</title><description>%s</description><link>https://www.ncsc.gov.uk/news/x-%d</link>"
                "<pubDate>%s</pubDate></item>" % (title, title, int(when.timestamp()), rfc(when)))
    return ('<?xml version="1.0"?><rss version="2.0"><channel>' +
            item("Critical vulnerability in a widely used router, actively exploited", ago(days=1)) +
            item("NCSC annual review published", ago(days=5)) + item("Old news", ago(days=40)) +
            '</channel></rss>').encode()


def fcdo():
    def entry(country, text, when):
        return ('<entry><title>%s</title><updated>%s</updated><link rel="alternate" '
                'href="https://www.gov.uk/foreign-travel-advice/%s"/><summary>%s</summary></entry>'
                % (country, when.isoformat(), country.lower(), text))
    return ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">' +
            entry("Ruritania", "The FCDO now advises against all travel to Ruritania.", ago(days=1)) +
            entry("Freedonia", "Updated information on local laws.", ago(days=2)) +
            entry("Atlantis", "Old change.", ago(days=10)) + '</feed>').encode()


DROUGHT_BODY = ('<h2>Summary</h2><p>It has been a dry week.</p><p>Total reservoir storage for England fell to 61.5% of '
                'capacity, which is 12.3% below the average for this time of year.</p>'
                '<h2>Areas in drought</h2><ul><li>East Anglia</li><li>Thames</li></ul>'
                '<h2>Areas in prolonged dry weather</h2><ul><li>Wessex</li></ul>'
                '<h2>Temporary use bans</h2><ul><li>Thames Water: a hosepipe ban from 14 July</li></ul>'
                '<h2>Thames Water</h2><p>Reservoirs are lower than usual.</p>')


def dsearch():
    return json.dumps({"results": [{"title": "Dry weather and drought in England: weekly report",
                                    "link": "/government/publications/dry-weather-drought", "public_timestamp": "2026-11-10"}]}).encode()


def govuk():
    end = ago(days=4).date()
    return json.dumps({"details": {"attachments": [
        {"title": "Dry weather and drought in England, %s to %s" % ((end - dt.timedelta(days=6)).strftime("%-d %B"),
                                                                    end.strftime("%-d %B %Y")),
         "url": "/government/publications/dry-weather-drought/week"}], "body": DROUGHT_BODY}}).encode()


def floodrisk():
    return json.dumps({"statements": [{"headline": "The flood risk is MEDIUM on Saturday in the north east.",
                                       "issued_at": ago(hours=3).isoformat(), "flood_risk_trend": {"day1": "increasing"},
                                       "public_forecast": {"england_forecast": "River flooding is possible in the north east."},
                                       "pdf_url": "https://flood-warning-information.service.gov.uk/fgs.pdf"}]}).encode()


def rainst():
    return json.dumps({"items": [{"notation": "R1", "label": "Near gauge", "lat": 54.47, "long": -0.62},
                                 {"notation": "R2", "label": "Far gauge", "lat": 51.5, "long": -0.1}]}).encode()


def rain():
    return json.dumps({"items": [{"dateTime": ago(hours=h).strftime("%Y-%m-%dT%H:%M:%SZ"), "value": 3.0}
                                 for h in range(1, 12)] + [{"dateTime": ago(days=3).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                            "value": 5.0}]}).encode()


def gwst():
    return json.dumps({"items": [{"label": "NEAR BOREHOLE", "lat": 54.45, "long": -0.6,
                                  "measures": [{"@id": "http://environment.data.gov.uk/hydrology/id/measures/abc-gw-dipped-i-mAOD-qualified"}]}]}).encode()


def gw():
    rows = []
    for y in range(1, 9):   # the same time of year in earlier years: 10 to 17 m
        rows.append({"date": (NOW.date() - dt.timedelta(days=365 * y + 5)).isoformat(), "value": 10.0 + y})
    rows.append({"date": (NOW.date() - dt.timedelta(days=10)).isoformat(), "value": 9.0})
    return json.dumps({"items": rows}).encode()


def ci():
    return json.dumps({"data": [{"from": ago(minutes=10).isoformat(), "intensity": {"forecast": 150, "actual": 140,
                                                                                    "index": "moderate"}}]}).encode()


def cimix():
    return json.dumps({"data": {"generationmix": [{"fuel": "wind", "perc": 40}, {"fuel": "gas", "perc": 30},
                                                  {"fuel": "coal", "perc": 0}]}}).encode()


def freq():
    return json.dumps({"data": [{"frequency": 50.01}, {"frequency": 49.97}, {"frequency": 50.02}]}).encode()


def margin():
    t = NOW.replace(minute=0, second=0, microsecond=0)
    return json.dumps({"data": [{"startTime": (t + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "publishTime": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "deratedMargin": 2500 + 400 * h,
                                 "lossOfLoadProbability": 0} for h in range(4)]}).encode()


def margind():
    return json.dumps({"data": [{"forecastDate": (NOW.date() + dt.timedelta(days=d)).isoformat(), "margin": 4000 + 100 * d}
                                for d in range(1, 5)]}).encode()


def dfs():
    return json.dumps({"result": {"records": [
        {"Delivery Date": NOW.date().isoformat(), "From_Local": "17:00", "To_Local": "17:30", "Event Type": "Down",
         "Service Requirement MW": 300},
        {"Delivery Date": NOW.date().isoformat(), "From_Local": "17:30", "To_Local": "18:00", "Event Type": "Down",
         "Service Requirement MW": 350}]}}).encode()


def water():
    return json.dumps({"features": [{"attributes": {"Region__c": "C", "JobGroup__c": "Supply", "JobType__c": "NO WATER",
                                                    "ReportedDate__c": int(ago(hours=2).timestamp() * 1000)},
                                     "geometry": {"x": -0.12, "y": 51.51}}]}).encode()


def wider_routes():
    return {"threat": (threat, "application/xml"), "ncsc": (ncsc, "application/xml"), "fcdo": (fcdo, "application/xml"),
            "dsearch": (dsearch, "application/json"), "govuk": (govuk, "application/json"),
            "floodrisk": (floodrisk, "application/json"), "rainst": (rainst, "application/json"),
            "rain": (rain, "application/json"), "gwst": (gwst, "application/json"), "gw": (gw, "application/json"),
            "ci": (ci, "application/json"), "cimix": (cimix, "application/json"), "freq": (freq, "application/json"),
            "margin": (margin, "application/json"), "margind": (margind, "application/json"),
            "dfs": (dfs, "application/json"), "water": (water, "application/json"),
            "places": (places, "application/json")}


def wider_urls(b):
    return {"threat": b + "threat", "cyber": b + "ncsc", "travel": b + "fcdo", "drought_search": b + "dsearch",
            "govuk_content": b + "govuk", "floodrisk": b + "floodrisk", "rain_stations": b + "rainst",
            "rain": b + "rain/{id}?since={since}", "gw_stations": b + "gwst", "gw": b + "gw/{id}?since={since}",
            "ci_now": b + "ci", "ci_mix": b + "cimix", "frequency": b + "freq?from={start}&to={end}",
            "margin": b + "margin?from={start}&to={end}", "margin_daily": b + "margind", "dfs": b + "dfs?",
            "water": b + "water", "places": b + "places"}
