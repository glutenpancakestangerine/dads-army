#!/usr/bin/env python3
"""Add anyone new who has changed Dads Army to dadsarmy/CREDITS.md.

GitHub runs this after every push to main (.github/workflows/credits.yml), and commits the
file if anyone was added. It reads the whole history each time, so it's safe to run again:

- people already in the file, by GitHub name or by name, are left alone
- nothing else in the file is changed, so names and notes can be edited by hand afterwards
- email addresses are never written to the file or printed

Run it yourself from the repository folder with:

  python3 tools/update_credits.py --check     # just say who would be added
  python3 tools/update_credits.py             # add them to the file

Only the Python standard library is used.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDITS_PATH = "dadsarmy/CREDITS.md"
GROUP = "Built by"            # the heading new names go under (made if it's missing)
NOTE = "contributed code"     # the words after each new name; edit them in the file afterwards

# Not people, so not credited: GitHub's own commits, bots, and the "Co-authored-by" lines AI coding
# assistants add. To credit one of them, take it out of these lists.
SKIP_EMAILS = {
    "noreply@anthropic.com",   # Claude Code
    "noreply@github.com",      # GitHub's web interface
}
SKIP_LOGINS = {"copilot"}      # GitHub Copilot

LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
NOREPLY_RE = re.compile(r"^(?:\d+\+)?(" + LOGIN + r")@users\.noreply\.github\.com$", re.I)
HANDLE_RE = re.compile(r"(?<![\w.@])@(" + LOGIN + r")(?![\w-])")
TRAILER_RE = re.compile(r"^co-authored-by:\s*(.+?)\s*<([^>\n]*)>\s*$", re.I | re.M)
LINK_RE = re.compile(r"\[([^\]\n]+)\]\([^)\s]*\)")
COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
BULLET_RE = re.compile(r"\s*[-*+]\s+(.*)$")
HEADING_RE = re.compile(r"\s*##\s+(.*)$")


def norm(name):
    """A name for comparing: no markdown, brackets or case."""
    s = LINK_RE.sub(r"\1", name or "")
    s = re.sub(r"[*_`()\[\]<>]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def is_bot(name, email, login=None):
    e, n, lg = (email or "").lower(), (name or "").lower(), (login or "").lower()
    return e in SKIP_EMAILS or "[bot]" in e or n.endswith("[bot]") or lg in SKIP_LOGINS or lg.endswith("[bot]")


# -- what's in the file already ------------------------------------------------------------
def known(text):
    """The names and GitHub names already in the file (not counting the editors' notes)."""
    names, logins = set(), set()
    for line in COMMENT_RE.sub("", text).splitlines():
        m = BULLET_RE.match(line)
        if not m:
            continue
        entry = LINK_RE.sub(r"\1", m.group(1))
        logins.update(h.lower() for h in HANDLE_RE.findall(entry))
        who = re.split(r":\s|\s[—–-]\s", entry, 1)[0]
        who = norm(HANDLE_RE.sub("", who))
        if who:
            names.add(who)
    return names, logins


def add_lines(text, new):
    """The file with NEW lines added to the end of the GROUP list, or in a new GROUP section."""
    lines = text.split("\n")
    hidden, at = set(), 0
    spans = [(m.start(), m.end()) for m in COMMENT_RE.finditer(text)]
    for i, line in enumerate(lines):   # lines inside the editors' notes don't count
        if any(a <= at < b for a, b in spans):
            hidden.add(i)
        at += len(line) + 1
    heads = [i for i, line in enumerate(lines) if i not in hidden and HEADING_RE.match(line)]
    group = next((i for i in heads if norm(HEADING_RE.match(lines[i]).group(1)) == norm(GROUP)), None)
    if group is None:
        block = ["## " + GROUP, ""] + new + [""]
        if heads:
            lines[heads[0]:heads[0]] = block
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += [""] + block
    else:
        end = next((i for i in heads if i > group), len(lines))
        bullets = [i for i in range(group + 1, end) if BULLET_RE.match(lines[i])]
        if bullets:
            lines[bullets[-1] + 1:bullets[-1] + 1] = new
        else:
            lines[group + 1:group + 1] = [""] + new
    return "\n".join(lines)


# -- who has changed something --------------------------------------------------------------
def git_commits(repo):
    """Every commit, oldest first (merges left out: what was merged counts, not who merged it)."""
    fmt = "%x1e%H%x1f%aN%x1f%aE%x1f%B%x1f"   # %aN and %aE follow .mailmap, to join up anyone's two names
    out = subprocess.run(["git", "-C", repo, "log", "--reverse", "--no-merges", "--format=" + fmt, "--name-only"],
                         stdout=subprocess.PIPE, check=True).stdout.decode("utf-8", "replace")
    commits = []
    for rec in out.split("\x1e")[1:]:
        parts = rec.split("\x1f")
        if len(parts) >= 5:
            commits.append({"sha": parts[0].strip(), "name": parts[1].strip(), "email": parts[2].strip(),
                            "body": parts[3], "files": [f.strip() for f in parts[4].splitlines() if f.strip()]})
    return commits


def people_from(commits):
    """Everyone who changed more than the credits file, first come first: authors and co-authors."""
    seen, out = set(), []
    for c in commits:
        if c["files"] and all(f == CREDITS_PATH for f in c["files"]):
            continue   # adding names to the credits isn't a code change
        who = [(c["name"], c["email"], c["sha"])] + [(n, e, None) for n, e in TRAILER_RE.findall(c["body"])]
        for name, email, sha in who:
            key = (email or name).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            if is_bot(name, email):
                continue
            m = NOREPLY_RE.match(email or "")
            out.append({"name": name.strip(), "email": email, "login": m.group(1) if m else None, "sha": sha})
    return out


def api_login(repo, sha, token=None):
    """The GitHub account a commit's author is linked to: (login or None, is it a bot)."""
    req = urllib.request.Request("https://api.github.com/repos/%s/commits/%s" % (repo, sha),
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "dads-army-credits"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            author = json.loads(r.read().decode("utf-8")).get("author") or {}
    except Exception:
        return None, False
    login = author.get("login")
    if not isinstance(login, str) or not re.fullmatch(LOGIN + r"(\[bot\])?", login):
        return None, False
    return login, author.get("type") == "Bot" or login.endswith("[bot]")


def entry(person):
    """'- Name (@login): contributed code'. Never an email address."""
    name = re.sub(r"[\x00-\x1f\x7f:*_`#()\[\]<>]", " ", person["name"] or "")
    name = re.sub(r"\s+", " ", name).strip()[:80]
    if "@" in name:   # an email address typed as a name
        name = ""
    login = person.get("login")
    if login and (not name or name.lower() == login.lower()):
        return "- @%s: %s" % (login, NOTE)
    if login:
        return "- %s (@%s): %s" % (name, login, NOTE)
    return "- %s: %s" % (name, NOTE) if name else None


def new_entries(text, people, repo=None, token=None, lookup=api_login):
    names, logins = known(text)
    new = []
    for p in people:
        if (p["login"] and p["login"].lower() in logins) or norm(p["name"]) in names:
            continue
        if not p["login"] and p["sha"] and repo:
            login, bot = lookup(repo, p["sha"], token)
            if bot or (login and login.lower() in logins):
                continue
            p = dict(p, login=login)
        if is_bot(p["name"], p["email"], p["login"]):
            continue
        line = entry(p)
        if line:
            new.append(line)
            names.add(norm(p["name"]))
            if p["login"]:
                logins.add(p["login"].lower())
    return new


def main(argv=None):
    ap = argparse.ArgumentParser(description="Add anyone new who has changed Dads Army to the credits.")
    ap.add_argument("--check", action="store_true", help="only say who would be added")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                    help="owner/name on GitHub, to find people's GitHub names (set by GitHub Actions)")
    ap.add_argument("--git", default=ROOT, help="the repository folder")
    ap.add_argument("--file", default=None, help="the credits file (default: dadsarmy/CREDITS.md in the repository)")
    args = ap.parse_args(argv)
    path = args.file or os.path.join(args.git, CREDITS_PATH)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    new = new_entries(text, people_from(git_commits(args.git)), args.repo, os.environ.get("GITHUB_TOKEN"))
    if not new:
        print("Nobody new to credit.")
        return 0
    print("New in the credits:\n" + "\n".join(new))
    if not args.check:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(add_lines(text, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
