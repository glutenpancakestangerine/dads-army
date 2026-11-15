#!/usr/bin/env python3
"""Check that a release says the same version everywhere, and print it.

Home Assistant offers an update as soon as the version in dadsarmy/config.yaml changes on main,
whether it was pushed or came in with a pull request. This checks that VERSION in
dadsarmy/server.py and the newest entry in dadsarmy/CHANGELOG.md say the same.

GitHub runs it on every pull request and push (.github/workflows/release.yml), and tags each
new version on main as vX.Y.Z, with its changelog entry as the tag's message.

Run it yourself from the repository folder with:

    python3 tools/release_check.py           # check, and print the version
    python3 tools/release_check.py --notes   # print this version's changelog entry
"""
import argparse
import os
import re
import sys

CONFIG = "dadsarmy/config.yaml"
SERVER = "dadsarmy/server.py"
CHANGELOG = "dadsarmy/CHANGELOG.md"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CONFIG_RE = re.compile(r"""^version:\s*["']?([^"'\s#]+)""", re.M)
SERVER_RE = re.compile(r"""^VERSION\s*=\s*["']([^"']+)["']""", re.M)
HEADING_RE = re.compile(r"^##\s+v?(\S+)\s*$")   # "## 1.13.0"; "###" isn't one


def config_version(text):
    m = CONFIG_RE.search(text)
    return m.group(1) if m else None


def server_version(text):
    m = SERVER_RE.search(text)
    return m.group(1) if m else None


def changelog_versions(text):
    """The versions in the changelog, newest first."""
    return [m.group(1) for m in map(HEADING_RE.match, text.splitlines()) if m]


def notes(text, version):
    """The changelog entry for one version, without its heading."""
    out, inside = [], False
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if inside:
                break
            inside = m.group(1) == version
        elif inside:
            out.append(line)
    return "\n".join(out).strip()


def _read(root, path):
    try:
        with open(os.path.join(root, path), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def check(root):
    """Returns (version, problems). The version is the one in config.yaml, which is what
    Home Assistant offers."""
    version = config_version(_read(root, CONFIG))
    problems = []
    if not version or not VERSION_RE.match(version):
        problems.append("%s: no version like 1.2.3 (found %s)" % (CONFIG, version or "nothing"))
        return version, problems
    srv = server_version(_read(root, SERVER))
    if srv != version:
        problems.append("%s: VERSION is %s, but %s says %s. Make them the same."
                        % (SERVER, srv or "missing", CONFIG, version))
    logged = changelog_versions(_read(root, CHANGELOG))
    if not logged or logged[0] != version:
        problems.append("%s: the newest entry is %s, but %s says %s. Add '## %s' at the top, "
                        "saying what's changed." % (CHANGELOG, logged[0] if logged else "missing",
                                                     CONFIG, version, version))
    return version, problems


def main(argv=None):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Check the release version agrees everywhere.")
    ap.add_argument("--root", default=here, help="the repository folder")
    ap.add_argument("--notes", action="store_true", help="print this version's changelog entry")
    args = ap.parse_args(argv)

    version, problems = check(args.root)
    if problems:
        on_github = os.environ.get("GITHUB_ACTIONS") == "true"
        for p in problems:
            print(("::error::" if on_github else "") + p, file=sys.stderr)
        return 1
    if args.notes:
        print(notes(_read(args.root, CHANGELOG), version))
    else:
        print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
