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
from xml.etree import ElementTree

try:
	import unittest2 as unittest
except ImportError:
	import unittest

from gitinspector import filtering, focus, interval
from .harness import Repository, __inside__
from .test_options import run_inside

class CategoryTest(unittest.TestCase):
	def test_files_are_sorted_by_folder_first_and_extension_second(self):
		self.assertEqual(focus.categorize("Battle/attack.gd"), "scripts")
		self.assertEqual(focus.categorize("Scripts/Player.cs"), "scripts")
		self.assertEqual(focus.categorize("shaders/wow.gdshader"), "shaders")
		self.assertEqual(focus.categorize("Battle/battle.tscn"), "scenes")
		self.assertEqual(focus.categorize("project.godot"), "scenes")
		self.assertEqual(focus.categorize("README.md"), "docs")
		self.assertEqual(focus.categorize("data/levels.json"), "data")
		self.assertEqual(focus.categorize(".gitignore"), "config")
		self.assertEqual(focus.categorize("art/hero.png"), "assets")
		self.assertEqual(focus.categorize("art/hero.png.import"), "generated")
		self.assertEqual(focus.categorize(".godot/imported/hero.ctex"), "generated")
		self.assertEqual(focus.categorize("Library/metadata/thing"), "generated")
		self.assertEqual(focus.categorize("notes.unknown"), "other")

class FocusTest(unittest.TestCase):
	def setUp(self):
		self.repository = Repository()
		self.repository.commit("scripts", {"player.gd": "extends Node\n\nfunc _ready():\n\tpass\n" * 5,
		                                   "player.tscn": "[gd_scene]\n" * 10}, "Ada", "ada@example.com")
		self.repository.commit("docs and art", {"README.md": "# Game\n" * 20, "hero.png": "\x89PNG binary",
		                                        "hero.png.import": "[remap]\n"}, "Bob", "bob@example.com",
		                       "2015-01-02T12:00:00+0000")
		self.repository.commit("more art", {"tree.png": "\x89PNG other binary"}, "Bob", "bob@example.com",
		                       "2015-01-03T12:00:00+0000")
		interval.clear()
		filtering.clear()

	def tearDown(self):
		self.repository.remove()

	def analyse(self):
		return __inside__(self.repository, lambda: focus.Focus(None))

	def test_lines_and_files_land_in_their_categories_per_author(self):
		entries = self.analyse().get_entries()
		(ada, bob) = (entries["Ada"], entries["Bob"])

		self.assertEqual((ada.lines["scripts"], ada.lines["scenes"], ada.files["scripts"], ada.commits), (20, 10, 1, 1))
		self.assertEqual((bob.lines["docs"], bob.files["assets"], bob.files["generated"], bob.commits), (20, 2, 1, 2))
		self.assertEqual(ada.shares()["scripts"], 100.0 * 20 / 30)
		self.assertEqual(ada.label(), "scripts 67%, scenes 33%")
		self.assertEqual(bob.label(), "docs 100%, 2 asset files, 1 generated")

	def test_the_interval_and_the_filters_apply(self):
		interval.set_since("2015-01-02")
		try:
			entries = self.analyse().get_entries()
			self.assertNotIn("Ada", entries)
		finally:
			interval.clear()

		filtering.add("author:Bob")
		try:
			entries = self.analyse().get_entries()
			self.assertEqual(sorted(entries), ["Ada"])
		finally:
			filtering.clear()

	def test_the_section_appears_in_every_output_format(self):
		(status, output, errors) = run_inside(self.repository.location, "-F", "json", "-f", "**", "--focus")
		self.assertEqual(status, 0, errors)
		section = json.loads(output)["gitinspector"]["focus"]
		self.assertEqual([author["name"] for author in section["authors"]], ["Ada", "Bob"])
		self.assertEqual(section["authors"][1]["files"]["assets"], 2)
		self.assertEqual(section["total"]["lines"]["scripts"], 20)

		(status, output, errors) = run_inside(self.repository.location, "-F", "xml", "-f", "**", "-C")
		self.assertEqual(status, 0, errors)
		self.assertEqual(len(ElementTree.fromstring(output.encode("utf-8")).find("focus").find("authors")), 2)

		(status, output, errors) = run_inside(self.repository.location, "-F", "text", "-f", "**", "--grading")
		self.assertEqual(status, 0, errors)
		self.assertIn("scripts 67%, scenes 33%", output)

		(status, output, errors) = run_inside(self.repository.location, "-F", "html", "-f", "**", "--focus")
		self.assertEqual(status, 0, errors)
		self.assertIn("id=\"focus\"", output)
