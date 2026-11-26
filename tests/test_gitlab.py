# coding: utf-8
#
# Copyright © 2012-2026 Ejwa Hosting AB. All rights reserved.
#
# This file is part of gitinspector.
#
# gitinspector is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# gitinspector is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with gitinspector. If not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals
import json
import os
import tempfile
from xml.etree import ElementTree

try:
	import unittest2 as unittest
except ImportError:
	import unittest

from gitinspector import gitlab, interval
from .harness import Repository
from .test_options import run_inside

def write_dump(path, **overrides):
	"""A dump the way the GitLab API hands the objects over, trimmed to the fields that matter."""
	dump = {
		"project": {"id": 7, "path_with_namespace": "course/team1", "web_url": "https://gitlab.example/course/team1"},
		"members": [{"username": "alice", "name": "Alice Able"}, {"username": "bob", "name": "Bob Baker"},
		            {"username": "carol", "name": "Carol Cole"}],
		"milestones": [{"iid": 1, "title": "Prototype", "state": "closed", "due_date": "2015-01-15T00:00:00Z"},
		               {"iid": 2, "title": "Final", "state": "active", "due_date": "2015-02-01T00:00:00Z"}],
		"issues": [
			{"iid": 1, "title": "Player movement", "state": "closed", "author": {"username": "alice", "name": "Alice Able"},
			 "assignees": [{"username": "bob"}], "labels": ["feature"], "milestone": {"title": "Prototype"},
			 "closed_by": {"username": "alice"}, "weight": 3},
			{"iid": 2, "title": "Menu", "state": "closed", "author": {"username": "alice", "name": "Alice Able"},
			 "assignees": [{"username": "alice"}], "labels": ["feature"], "milestone": {"title": "Prototype"},
			 "closed_by": {"username": "bob"}},
			{"iid": 3, "title": "Sound", "state": "opened", "author": {"username": "bob", "name": "Bob Baker"},
			 "assignees": [{"username": "carol"}], "labels": [], "milestone": {"title": "Final"}},
			{"iid": 4, "title": "Credits", "state": "opened", "author": {"username": "bob", "name": "Bob Baker"},
			 "assignees": [], "labels": ["bug"], "milestone": None},
		],
	}
	dump.update(overrides)

	with open(path, "wb") as handle:
		handle.write(json.dumps(dump).encode("utf-8"))

	return path

class RemoteParsingTest(unittest.TestCase):
	def test_ssh_and_https_remotes_name_the_same_project(self):
		for url in ("git@gitlab.example:course/team1/game.git", "https://gitlab.example/course/team1/game.git",
		            "ssh://git@gitlab.example:2222/course/team1/game", "https://gitlab.example/course/team1/game/"):
			self.assertEqual(gitlab.project_from_remote(url), ("https://gitlab.example/api/v4", "course/team1/game"), url)

	def test_a_remote_without_a_namespace_is_not_a_project(self):
		self.assertIsNone(gitlab.project_from_remote("https://gitlab.example/game.git"))
		self.assertIsNone(gitlab.project_from_remote(""))
		self.assertIsNone(gitlab.project_from_remote("/home/me/game"))

class ReferenceParsingTest(unittest.TestCase):
	def test_issue_numbers_are_found_but_colours_and_fragments_are_not(self):
		self.assertEqual(gitlab.ISSUE_REFERENCE.findall("Fix #12 and #3, see #123abc and x#9 and ##4"), ["12", "3"])

	def test_closing_words_are_recognised(self):
		self.assertEqual(gitlab.CLOSING_REFERENCE.findall("Closes #4; fixed the #5 bug; resolve issue #6; touches #7"),
		                 ["4", "5", "6"])

class UserMatchingTest(unittest.TestCase):
	def setUp(self):
		self.users = [gitlab.UserStats("alice", "Alice Able"), gitlab.UserStats("bbaker1", "Bob Baker")]

	def test_the_address_the_name_and_the_tokens_all_match(self):
		self.assertEqual(gitlab.match_user("Someone", "bbaker1@uni.example", self.users), "bbaker1")
		self.assertEqual(gitlab.match_user("alice able", "x@y", self.users), "alice")
		self.assertEqual(gitlab.match_user("Bob", "bob@gmail.example", self.users), "bbaker1")
		#A name that holds all the tokens of a member's name is that member, double-barrelled or not.
		self.assertEqual(gitlab.match_user("Bob Baker-Smith", "", self.users), "bbaker1")
		self.assertEqual(gitlab.match_user("bbaker1 on laptop", "", self.users), "bbaker1")
		self.assertEqual(gitlab.match_user("Nobody", "nobody@example", self.users), None)

	def test_an_alias_wins_over_every_heuristic(self):
		aliases = {"nobody@example": "alice", "someone": "bbaker1"}
		self.assertEqual(gitlab.match_user("Nobody", "nobody@example", self.users, aliases), "alice")
		self.assertEqual(gitlab.match_user("Someone", "", self.users, aliases), "bbaker1")
		self.assertEqual(gitlab.match_user("alice able", "x@y", self.users, aliases), "alice")

class JoinedHistoryTest(unittest.TestCase):
	def setUp(self):
		self.repository = Repository()
		self.repository.commit("Start #1 movement", {"player.py": "x = 1\n"}, "Bob Baker", "bob@example.com",
		                       "2015-01-02T12:00:00+0000")
		self.repository.commit("Closes #2 menu done", {"menu.py": "y = 2\n"}, "Alice Able", "alice@example.com",
		                       "2015-01-03T12:00:00+0000")
		self.repository.commit("More on #1 and #3", {"player.py": "x = 2\n"}, "Bob Baker", "bob@example.com",
		                       "2015-01-04T12:00:00+0000")
		self.repository.commit("Unrelated tidy up", {"readme.md": "hi\n"}, "Mystery Person", "ghost@example.com",
		                       "2015-01-05T12:00:00+0000")
		self.dump = write_dump(os.path.join(self.repository.location, "dump.json"))
		interval.clear()

	def tearDown(self):
		self.repository.remove()

	def join(self):
		return gitlab.GitLabData.from_dump(self.dump).join(self.repository.location)

	def test_commits_are_tied_to_the_issues_they_name(self):
		data = self.join()
		issues = dict((issue.iid, issue) for issue in data.issues)

		self.assertEqual(issues[1].committers, {"bob": 2})
		self.assertEqual(issues[2].committers, {"alice": 1})
		self.assertEqual(issues[2].closing_committers, {"alice": 1})
		self.assertEqual(issues[3].committers, {"bob": 1})
		self.assertEqual(issues[4].committers, {})

	def test_the_statistics_say_who_planned_and_who_delivered(self):
		data = self.join()
		(alice, bob, carol) = (data.stats["alice"], data.stats["bob"], data.stats["carol"])

		self.assertEqual((alice.issues_created, alice.issues_assigned, alice.issues_closed), (2, 1, 1))
		self.assertEqual((alice.commits, alice.commits_linked, alice.commits_closing), (1, 1, 1))
		self.assertEqual(alice.assigned_done_self, 1)
		self.assertEqual((bob.commits, bob.commits_linked, sorted(bob.issues_referenced)), (2, 2, [1, 3]))
		self.assertEqual((bob.assigned_done_self, bob.assigned_done_other, bob.assigned_untouched), (1, 0, 0))
		#Carol was assigned the sound issue and Bob committed against it.
		self.assertEqual((carol.commits, carol.assigned_done_other, carol.assigned_untouched), (0, 1, 0))
		self.assertEqual(data.unmatched, {"Mystery Person": 1})
		self.assertEqual([issue.iid for issue in data.misassigned()], [3])

	def test_milestones_count_their_issues_and_know_when_they_are_late(self):
		data = self.join()
		(prototype, final) = data.milestones

		self.assertEqual((prototype.title, len(prototype.issues), len(prototype.closed_issues())), ("Prototype", 2, 2))
		self.assertEqual(prototype.completion(), 100.0)
		self.assertFalse(prototype.is_overdue())
		self.assertEqual((final.title, len(final.issues), len(final.open_issues())), ("Final", 1, 1))
		self.assertTrue(final.is_overdue("2015-03-01"))
		self.assertFalse(final.is_overdue("2015-01-20"))
		self.assertEqual((prototype.linked_commits(), final.linked_commits()), (3, 1))

	def test_the_totals_add_up(self):
		totals = self.join().totals()

		self.assertEqual((totals["issues"], totals["open"], totals["closed"]), (4, 2, 2))
		self.assertEqual((totals["unassigned"], totals["without_milestone"]), (1, 1))
		self.assertEqual((totals["commits"], totals["commits_linked"], totals["referenced_by_commits"]), (4, 3, 3))

	def test_the_interval_limits_the_joined_history(self):
		interval.set_since("2015-01-03")
		try:
			data = self.join()
			self.assertEqual(data.totals()["commits"], 3)
		finally:
			interval.clear()

	def test_an_aliases_file_attributes_commits_from_personal_addresses(self):
		aliases = os.path.join(self.repository.location, "aliases.json")
		with open(aliases, "wb") as handle:
			handle.write(json.dumps({"aliases": {"ghost@example.com": "carol"}}).encode("utf-8"))

		data = gitlab.GitLabData.from_dump(self.dump)
		data.aliases = gitlab.load_aliases(aliases)
		data.join(self.repository.location)

		self.assertEqual(data.unmatched, {})
		self.assertEqual((data.stats["carol"].commits, sorted(data.stats["carol"].git_authors)), (1, ["Mystery Person"]))

		(status, output, errors) = run_inside(self.repository.location, "-F", "json", "-f", "**", "--gitlab-dump", self.dump,
		                                      "--gitlab-aliases", aliases)
		self.assertEqual(status, 0, errors)
		self.assertEqual(json.loads(output)["gitinspector"]["gitlab"]["unmatched_authors"], [])

		with self.assertRaises(gitlab.GitLabError):
			gitlab.load_aliases(os.path.join(self.repository.location, "missing.json"))

	def test_members_without_any_activity_are_set_aside(self):
		write_dump(self.dump, members=[{"username": "alice", "name": "Alice Able"}, {"username": "bob", "name": "Bob Baker"},
		                               {"username": "carol", "name": "Carol Cole"}, {"username": "staff", "name": "A Tutor"}])
		data = self.join()

		self.assertEqual([user.username for user in data.active_users()], ["alice", "bob", "carol"])
		self.assertEqual([user.username for user in data.inactive_users()], ["staff"])
		self.assertEqual(data.as_dict()["inactive_members"], ["staff"])
		self.assertEqual([user["username"] for user in data.as_dict()["users"]], ["alice", "bob", "carol"])

	def test_an_unreadable_dump_is_an_error_with_a_message(self):
		with self.assertRaises(gitlab.GitLabError):
			gitlab.GitLabData.from_dump(os.path.join(self.repository.location, "missing.json"))

	def test_the_section_appears_in_every_output_format(self):
		(status, output, errors) = run_inside(self.repository.location, "-F", "json", "-f", "**", "--gitlab-dump", self.dump)
		self.assertEqual(status, 0, errors)
		section = json.loads(output)["gitinspector"]["gitlab"]
		self.assertEqual(section["project"], "course/team1")
		self.assertEqual(section["totals"]["issues"], 4)
		self.assertEqual([user["username"] for user in section["users"]], ["alice", "bob", "carol"])
		self.assertEqual([milestone["title"] for milestone in section["milestones"]], ["Prototype", "Final"])

		(status, output, errors) = run_inside(self.repository.location, "-F", "xml", "-f", "**", "--gitlab-dump", self.dump)
		self.assertEqual(status, 0, errors)
		section = ElementTree.fromstring(output.encode("utf-8")).find("gitlab")
		self.assertEqual(section.findtext("project"), "course/team1")
		self.assertEqual(len(section.find("users")), 3)

		(status, output, errors) = run_inside(self.repository.location, "-F", "text", "-f", "**", "--gitlab-dump", self.dump)
		self.assertEqual(status, 0, errors)
		self.assertIn("Mystery Person", output)
		self.assertIn("Prototype", output)

		(status, output, errors) = run_inside(self.repository.location, "-F", "html", "-f", "**", "--gitlab-dump", self.dump)
		self.assertEqual(status, 0, errors)
		self.assertIn("gitlab-milestones", output)

	def test_a_missing_dump_fails_the_run_with_a_message(self):
		(status, output, errors) = run_inside(self.repository.location, "-f", "**", "--gitlab-dump", "nowhere.json")
		self.assertEqual(status, 2)
		self.assertIn("nowhere.json", errors)

	def test_the_dump_can_come_from_the_git_config(self):
		self.repository.git("config", "inspector.gitlab-dump", self.dump)
		(status, output, errors) = run_inside(self.repository.location, "-F", "json", "-f", "**")
		self.assertEqual(status, 0, errors)
		self.assertIn("gitlab", json.loads(output)["gitinspector"])

class TokenTest(unittest.TestCase):
	def test_the_option_beats_the_environment_which_beats_the_config(self):
		previous = os.environ.get("GITLAB_TOKEN")
		os.environ["GITLAB_TOKEN"] = "from-env"
		try:
			self.assertEqual(gitlab.resolve_token("from-option", "from-config"), "from-option")
			self.assertEqual(gitlab.resolve_token(None, "from-config"), "from-env")
			del os.environ["GITLAB_TOKEN"]
			self.assertEqual(gitlab.resolve_token(None, "from-config"), "from-config")
			self.assertIsNone(gitlab.resolve_token(None, None))
		finally:
			if previous is not None:
				os.environ["GITLAB_TOKEN"] = previous
			else:
				os.environ.pop("GITLAB_TOKEN", None)
