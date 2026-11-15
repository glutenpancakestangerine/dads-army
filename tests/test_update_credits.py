"""tools/update_credits.py: GitHub runs it after every push, to add anyone new to CREDITS.md.
People already named are left alone, bots and AI assistants aren't people, and no email address
is ever written."""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("update_credits", os.path.join(ROOT, "tools", "update_credits.py"))
uc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uc)

with open(os.path.join(ROOT, "dadsarmy", "CREDITS.md"), encoding="utf-8") as _f:
    REAL = _f.read()

SMALL = """# Credits

<!--
    - Jane Smith (@janesmith): an example in the notes
## Not a heading
-->

Thank you.

## Built by

- Parker Veese Development (@parkerveese-cloud): started it

## Open data and maps

- Met Office: weather warnings
"""


def commit(sha, name, email, files=("dadsarmy/server.py",), body="A change\n"):
    return {"sha": sha, "name": name, "email": email, "body": body, "files": list(files)}


def no_lookup(repo, sha, token=None):
    raise AssertionError("GitHub shouldn't be asked")


class RulesTest(unittest.TestCase):

    def test_whats_already_in_the_real_file(self):
        names, logins = uc.known(REAL)
        self.assertIn("parker veese development", names)
        self.assertIn("parkerveese-cloud", logins)
        self.assertIn("openstreetmap contributors", names)
        self.assertNotIn("janesmith", logins)   # the example in the editors' notes isn't a person

    def test_who_counts(self):
        people = uc.people_from([
            commit("a1", "Parker Veese Development", "dev@parkerveese.io",
                   body="Add things\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"),
            commit("a2", "Jane Smith", "12345+janesmith@users.noreply.github.com",
                   body="Fix floods\n\nCo-authored-by: Sam Jones <sam@example.org>\n"),
            commit("a3", "dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
            commit("a4", "github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com",
                   files=["dadsarmy/CREDITS.md"]),
            commit("a5", "Lee", "lee@example.org", files=["dadsarmy/CREDITS.md"]),   # only added their name
            commit("a6", "Jane Smith", "12345+janesmith@users.noreply.github.com"),   # again
            commit("a7", "Web Editor", "web@example.org", files=[]),
        ])
        self.assertEqual([(p["name"], p["login"], p["sha"]) for p in people],
                         [("Parker Veese Development", None, "a1"), ("Jane Smith", "janesmith", "a2"),
                          ("Sam Jones", None, None), ("Web Editor", None, "a7")])

    def test_new_entries(self):
        people = uc.people_from([
            commit("a1", "Parker Veese Development", "dev@parkerveese.io"),
            commit("a2", "jane", "12345+JaneSmith@users.noreply.github.com"),
            commit("a3", "Sam: the *best* [tester]", "sam@example.org"),
            commit("a4", "sam@example.org", "sam2@example.org"),
            commit("a5", "Copilot", "175728472+Copilot@users.noreply.github.com"),
        ])
        new = uc.new_entries(SMALL, people, repo=None, lookup=no_lookup)
        self.assertEqual(new, ["- jane (@JaneSmith): contributed code", "- Sam the best tester: contributed code"])
        self.assertFalse(any("example.org" in line for line in new))

    def test_github_names_are_looked_up(self):
        asked = []

        def lookup(repo, sha, token=None):
            asked.append((repo, sha))
            return {"b1": ("sammy", False), "b2": ("parkerveese-cloud", False), "b3": ("renovate[bot]", True),
                    "b4": (None, False)}[sha]
        people = uc.people_from([commit("b1", "Sam Jones", "sam@example.org"),
                                 commit("b2", "PVD laptop", "other@parkerveese.io"),
                                 commit("b3", "Renovate", "bot@renovateapp.com"),
                                 commit("b4", "Ana", "ana@example.org")])
        new = uc.new_entries(SMALL, people, repo="owner/repo", lookup=lookup)
        self.assertEqual(new, ["- Sam Jones (@sammy): contributed code", "- Ana: contributed code"])
        self.assertEqual([s for _, s in asked], ["b1", "b2", "b3", "b4"])

    def test_names_go_under_built_by(self):
        out = uc.add_lines(SMALL, ["- Ana: contributed code"])
        self.assertIn("- Parker Veese Development (@parkerveese-cloud): started it\n- Ana: contributed code\n\n## Open data",
                      out)
        self.assertEqual(out.replace("- Ana: contributed code\n", ""), SMALL)   # nothing else changed
        self.assertEqual(uc.new_entries(out, [{"name": "Ana", "email": "a@x.org", "login": None, "sha": None}],
                                        lookup=no_lookup), [])

    def test_built_by_is_made_if_missing(self):
        text = "Thank you.\n\n## Open data and maps\n\n- Met Office: weather warnings\n"
        self.assertEqual(uc.add_lines(text, ["- Ana: contributed code"]),
                         "Thank you.\n\n## Built by\n\n- Ana: contributed code\n\n## Open data and maps\n\n"
                         "- Met Office: weather warnings\n")
        self.assertEqual(uc.add_lines("Thank you.\n", ["- Ana: contributed code"]),
                         "Thank you.\n\n## Built by\n\n- Ana: contributed code\n")
        self.assertEqual(uc.add_lines("## Built by\n\n## Data\n", ["- Ana: contributed code"]),
                         "## Built by\n\n- Ana: contributed code\n\n## Data\n")

    def test_the_real_file_now(self):
        """The repository as it is: everyone who has changed it is already credited."""
        if not shutil.which("git") or not os.path.isdir(os.path.join(ROOT, ".git")) and not os.path.isfile(
                os.path.join(ROOT, ".git")):
            self.skipTest("needs git and the repository")
        try:
            people = uc.people_from(uc.git_commits(ROOT))
        except (subprocess.CalledProcessError, OSError):
            self.skipTest("git couldn't read the repository here")
        self.assertEqual(uc.new_entries(REAL, people, repo=None, lookup=no_lookup), [])


@unittest.skipUnless(shutil.which("git"), "needs git")
class EndToEndTest(unittest.TestCase):
    """A throwaway repository with a few people's commits, run the way GitHub runs it."""

    def git(self, *args, **who):
        env = dict(os.environ, GIT_AUTHOR_NAME=who.get("name", "Parker Veese Development"),
                   GIT_AUTHOR_EMAIL=who.get("email", "dev@parkerveese.io"), GIT_COMMITTER_NAME="Test",
                   GIT_COMMITTER_EMAIL="test@example.org", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        subprocess.run(["git", "-C", self.dir] + list(args), check=True, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def change(self, path, msg, **who):
        full = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, **who)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="credits-git-")
        self.git("init", "-q")
        os.makedirs(os.path.join(self.dir, "dadsarmy"))
        with open(os.path.join(self.dir, uc.CREDITS_PATH), "w", encoding="utf-8", newline="\n") as f:
            f.write(SMALL)
        self.change("dadsarmy/server.py", "Start\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
        self.change("dadsarmy/server.py", "Rivers", name="Jane Smith", email="12345+janesmith@users.noreply.github.com")
        self.change("dadsarmy/CREDITS.md", "Add me", name="Lee", email="lee@example.org")
        self.change("README.md", "Typos\n\nCo-authored-by: Sam Jones <sam@example.org>", name="Ana", email="ana@example.org")
        self.change("README.md", "Bump", name="dependabot[bot]", email="49699333+dependabot[bot]@users.noreply.github.com")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def read(self):
        with open(os.path.join(self.dir, uc.CREDITS_PATH), encoding="utf-8") as f:
            return f.read()

    def test_run_twice(self):
        os.environ.pop("GITHUB_REPOSITORY", None)
        self.assertEqual(uc.main(["--git", self.dir]), 0)
        text = self.read()
        self.assertIn("- Parker Veese Development (@parkerveese-cloud): started it\n"
                      "- Jane Smith (@janesmith): contributed code\n"
                      "- Ana: contributed code\n"
                      "- Sam Jones: contributed code\n\n## Open data", text)
        for gone in ("Claude", "Lee", "dependabot", "example.org", "noreply"):
            self.assertNotIn(gone, text.split("-->")[1])
        self.assertEqual(uc.main(["--git", self.dir]), 0)
        self.assertEqual(self.read(), text)   # nothing added twice

    def test_check_changes_nothing(self):
        before = self.read()
        self.assertEqual(uc.main(["--git", self.dir, "--check"]), 0)
        self.assertEqual(self.read(), before)
