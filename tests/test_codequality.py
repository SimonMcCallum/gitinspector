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
from xml.etree import ElementTree

try:
	import unittest2 as unittest
except ImportError:
	import unittest

from gitinspector import codequality, filtering, interval
from .harness import Repository, __inside__, analyze_changes
from .test_options import run_inside

#What a first-year hands in at midnight: untyped, a debug print, magic numbers, a long function,
#deep nesting, a block of commented-out code and the same line pasted three times.
ROUGH = """extends Node

var hp = 100
var speed = 7.5
var dmg = 13

func update_stuff(delta, thing):
	print("updating")
	if thing:
		if thing.hp > 0:
			if thing.speed > 3.7:
				if thing.pos.x > 240:
					if thing.pos.y > 180:
						thing.pos.x = thing.pos.x - 17
	thing.hp = thing.hp - 13
	thing.hp = thing.hp - 13
	thing.hp = thing.hp - 13
	# var old_hp = hp
	# if old_hp < 0:
	# print(old_hp)
	speed = speed * 1.07
	speed = speed * 1.07
	speed = speed * 1.07
	if hp < 23:
		speed = 4.2
	elif hp < 57:
		speed = 5.9
	thing.dmg = thing.dmg + 3
	thing.dmg = thing.dmg + 3
	thing.dmg = thing.dmg + 3
	return hp

func do_thing(a, b, c):
	var x = a * 3.3
	var y = b * 4.4
	if x > y:
		return x + 17
	return y + 19
"""

#What a generator hands back: typed through, a doc comment on every function, sentence-case
#explanatory comments before each step, long descriptive names, section headers, nothing left over.
POLISHED = """extends Node

# --- Player health -----------------------------------------------------------

## The number of hit points the player starts a run with.
const STARTING_HEALTH_POINTS: int = 100

## Current hit points, clamped between zero and the starting value.
var current_health_points: int = STARTING_HEALTH_POINTS

## Movement speed in pixels per second.
var movement_speed_pixels: float = 7.5

## Apply damage to the player and return the remaining hit points.
func apply_damage(damage_amount: int) -> int:
	# Ensure the damage amount is never negative before applying it.
	var sanitized_damage_amount: int = max(damage_amount, 0)
	# Reduce the current health and keep it within the valid range.
	current_health_points = clampi(current_health_points - sanitized_damage_amount, 0, STARTING_HEALTH_POINTS)
	# Returns the remaining health so callers can react to it.
	return current_health_points

## Heal the player by the given amount without exceeding the maximum.
func apply_healing(healing_amount: int) -> int:
	# Ensure the healing amount is positive before applying it.
	var sanitized_healing_amount: int = max(healing_amount, 0)
	# Update the current health and clamp it to the starting value.
	current_health_points = clampi(current_health_points + sanitized_healing_amount, 0, STARTING_HEALTH_POINTS)
	return current_health_points

# --- Movement ----------------------------------------------------------------

## Check if the player is still alive.
func is_player_alive() -> bool:
	# Returns true while there are hit points left.
	return current_health_points > 0

## Calculate the distance the player moves in one frame.
func calculate_frame_distance(delta_seconds: float) -> float:
	# Multiply the speed by the elapsed time to get the distance.
	return movement_speed_pixels * delta_seconds

## Update the movement speed, ignoring values that are not positive.
func set_movement_speed(new_speed_pixels: float) -> void:
	# Ensure the new speed is positive before storing it.
	if new_speed_pixels > 0.0:
		movement_speed_pixels = new_speed_pixels

## Restore the player to full health.
func restore_full_health() -> void:
	# Reset the current health to the starting value.
	current_health_points = STARTING_HEALTH_POINTS

## Determine whether the player is below half health.
func is_health_low() -> bool:
	# Compare the current health with half of the starting value.
	return current_health_points * 2 < STARTING_HEALTH_POINTS

## Convert hit points to a fraction of the starting value.
func health_fraction() -> float:
	# Divide the current health by the starting value.
	return float(current_health_points) / float(STARTING_HEALTH_POINTS)

## Describe the health state as a short label for the user interface.
func describe_health_state() -> String:
	# Returns a label that reflects how much health is left.
	if is_health_low():
		return "low"
	return "healthy"

## Apply a speed multiplier for a temporary boost.
func apply_speed_multiplier(speed_multiplier: float) -> void:
	# Ensure the multiplier is positive before applying it.
	if speed_multiplier > 0.0:
		movement_speed_pixels = movement_speed_pixels * speed_multiplier
"""

def lines_of(text, extension="gd"):
	profile = codequality.profile_of(extension)
	result = []
	inside = False
	for (number, content) in enumerate(text.splitlines()):
		(comments, inside) = codequality.comment.handle_comment_block(inside, extension, content)
		result.append(codequality.Line("a", "r", content, comments > 0, codequality.__indent__(content, profile.indent_tabs),
		                               number + 1))
	return result

def measure(text, extension="gd"):
	return codequality.measure(lines_of(text, extension), codequality.profile_of(extension), lambda line: True)

class MeasureTest(unittest.TestCase):
	def test_rough_code_is_caught_on_every_count(self):
		rough = measure(ROUGH)

		self.assertEqual(rough.functions, 2)
		self.assertEqual(rough.params, 5)
		self.assertEqual(rough.params_typed, 0)
		self.assertEqual(rough.functions_typed_return, 0)
		self.assertEqual(rough.functions_documented, 0)
		self.assertEqual(rough.vars, 5)
		self.assertEqual(rough.vars_typed, 0)
		self.assertEqual(rough.debug_prints, 1)
		self.assertEqual(rough.commented_code, 3)
		self.assertGreaterEqual(rough.magic_numbers, 10)
		self.assertEqual(rough.max_nesting, 6)
		self.assertEqual(rough.duplicates, 9)
		self.assertEqual(rough.function_lengths, [25, 6])
		self.assertEqual(rough.typing(), 0.0)
		self.assertLess(rough.hygiene(), 40.0)
		self.assertLess(rough.score(), codequality.POOR_POLISH)
		self.assertEqual(rough.level(), "beginning")

	def test_polished_code_scores_high_and_carries_the_marks_of_generation(self):
		polished = measure(POLISHED)

		self.assertEqual(polished.functions, 10)
		self.assertEqual((polished.params, polished.params_typed), (5, 5))
		self.assertEqual(polished.functions_typed_return, 10)
		self.assertEqual(polished.functions_documented, 10)
		self.assertEqual(polished.functions_doc_syntax, 10)
		self.assertEqual((polished.vars, polished.vars_typed), (5, 5))
		self.assertEqual(polished.typing(), 1.0)
		self.assertEqual(polished.debug_prints, 0)
		self.assertEqual(polished.commented_code, 0)
		self.assertEqual(polished.section_headers, 2)
		self.assertGreaterEqual(polished.explanatory, 7)
		self.assertGreaterEqual(polished.explain_words, 4)
		self.assertEqual(polished.names_conforming, polished.names)
		self.assertGreater(polished.score(), 75.0)
		self.assertEqual(polished.level(), "strong")
		signals = [name for (name, present) in polished.signals() if present]
		for expected in ("fully typed", "doc comment on most functions", "sentence-case explanatory comments",
		                 "section-header comments", "long descriptive names", "explanatory wording in comments"):
			self.assertIn(expected, signals)
		rough_signals = [name for (name, present) in measure(ROUGH).signals() if present]
		for unexpected in ("fully typed", "doc comment on most functions", "sentence-case explanatory comments",
		                   "section-header comments", "long descriptive names", "nothing left over"):
			self.assertNotIn(unexpected, rough_signals)
		self.assertLessEqual(len(rough_signals), 1)

	def test_other_languages_have_a_profile_and_a_fallback(self):
		csharp = measure("public class Player {\n    /// <summary>Hits.</summary>\n    public int TakeDamage(int amount) {\n"
		                 "        Debug.Log(amount);\n        return amount;\n    }\n}\n", "cs")
		self.assertEqual((csharp.functions, csharp.functions_documented, csharp.debug_prints), (1, 1, 1))
		self.assertIsNone(csharp.typing())

		python = measure("def go(x: int) -> int:\n    \"\"\"Doc.\"\"\"\n    print(x)\n    return x\n", "py")
		self.assertEqual((python.functions, python.functions_documented, python.params_typed, python.debug_prints), (1, 1, 1, 1))

		shader = measure("void fragment() {\n\tALBEDO = vec3(0.2, 0.4, 0.6);\n}\n", "gdshader")
		self.assertEqual(shader.functions, 1)
		self.assertIsNone(shader.typing())
		self.assertIsNone(codequality.profile_of("tscn"))

class RepositoryTest(unittest.TestCase):
	def setUp(self):
		self.repository = Repository()
		self.repository.commit("rough", {"rough.gd": ROUGH}, "Bob Baker", "bob@example.com", "2015-01-01T12:00:00+0000")
		self.repository.commit("more rough", {"rough2.gd": ROUGH.replace("update_stuff", "other_stuff")}, "Bob Baker",
		                       "bob@example.com", "2015-01-02T12:00:00+0000")
		self.repository.commit("and more", {"rough3.gd": ROUGH.replace("update_stuff", "third_stuff")}, "Bob Baker",
		                       "bob@example.com", "2015-01-03T12:00:00+0000")
		self.repository.commit("polished", {"health.gd": POLISHED}, "Bob Baker", "bob@example.com", "2015-01-04T12:00:00+0000")
		self.repository.commit("scene", {"health.tscn": "[gd_scene]\n"}, "Ada Able", "ada@example.com", "2015-01-05T12:00:00+0000")
		interval.clear()
		filtering.clear()

	def tearDown(self):
		self.repository.remove()

	def analyse(self):
		changes = analyze_changes(self.repository)
		return __inside__(self.repository, lambda: codequality.CodeQuality(None, changes))

	def test_the_polished_chunk_stands_out_against_the_authors_usual(self):
		quality = self.analyse()
		bob = quality.get_authors()["Bob Baker"]
		self.assertNotIn("Ada Able", quality.get_authors())
		self.assertEqual(bob.functions, 16)
		self.assertEqual(len([chunk for chunk in quality.chunks if chunk.author == "Bob Baker"]), 4)

		flagged = quality.flagged
		self.assertEqual([chunk.filename for chunk in flagged], ["health.gd"])
		self.assertEqual(flagged[0].verdict, "polished")
		self.assertGreater(flagged[0].polish, flagged[0].baseline + 20)
		self.assertIn("fully typed", flagged[0].reasons)

		ratios = quality.ratios["Bob Baker"]
		self.assertEqual(ratios["chunks"], 4)
		self.assertEqual(ratios["flagged"], 1)
		self.assertGreater(ratios["poor"], 50.0)
		self.assertGreater(ratios["polished"], 20.0)
		self.assertAlmostEqual(ratios["good"] + ratios["fair"] + ratios["poor"], 100.0, places=5)

	def test_the_section_appears_in_every_output_format(self):
		(status, output, errors) = run_inside(self.repository.location, "-F", "json", "-f", "**", "--code-quality")
		self.assertEqual(status, 0, errors)
		section = json.loads(output)["gitinspector"]["code_quality"]
		self.assertEqual([author["name"] for author in section["authors"]], ["Bob Baker"])
		self.assertEqual(section["flagged_chunks"][0]["file"], "health.gd")
		self.assertIn(section["authors"][0]["level"], ("beginning", "developing", "competent", "strong"))

		(status, output, errors) = run_inside(self.repository.location, "-F", "xml", "-f", "**", "-Q")
		self.assertEqual(status, 0, errors)
		root = ElementTree.fromstring(output.encode("utf-8")).find("code-quality")
		self.assertEqual(root.find("flagged-chunks")[0].findtext("file"), "health.gd")

		(status, output, errors) = run_inside(self.repository.location, "-F", "text", "-f", "**", "--grading")
		self.assertEqual(status, 0, errors)
		self.assertIn("health.gd @", output)
		self.assertIn("against a usual", output)

		(status, output, errors) = run_inside(self.repository.location, "-F", "html", "-f", "**", "--code-quality")
		self.assertEqual(status, 0, errors)
		self.assertIn("id=\"quality\"", output)
		self.assertIn("health.gd", output)

	def test_the_option_can_come_from_the_git_config(self):
		self.repository.git("config", "inspector.code-quality", "true")
		(status, output, errors) = run_inside(self.repository.location, "-F", "json", "-f", "**")
		self.assertEqual(status, 0, errors)
		self.assertIn("code_quality", json.loads(output)["gitinspector"])
