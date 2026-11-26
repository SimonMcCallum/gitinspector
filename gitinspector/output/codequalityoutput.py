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

from __future__ import print_function
from __future__ import unicode_literals
import textwrap
from xml.sax.saxutils import escape
from ..localization import N_
from .. import codequality, terminal
from .outputable import (Outputable, author_indices, html_author_cell, html_card, html_header_cell, html_meter_cell,
                         html_number_cell, html_table, json_block, xml_element)

QUALITY_INFO_TEXT = N_("The following reads the script lines each author owns and rates them")
QUALITY_NOTE_TEXT = N_("Scores run 0 to 100 and are made of clarity (naming, comments, documented functions), structure "
                       "(function length, nesting, branching), robustness (typing, checks) and hygiene (no debug prints, "
                       "magic numbers, commented-out or duplicated code). Good, fair and poor are shares of the author's "
                       "code lines by the polish of the chunk they were added in. Polished is the share in chunks that "
                       "carry the marks of generated or AI-assisted code. It is a heuristic, noted for information only: "
                       "generated code is allowed and does not count against the score.")
FLAGGED_TEXT = N_("Chunks that look generated or AI-assisted (noted only, allowed)")
NO_SCRIPTS_TEXT = N_("No script lines were found to rate")
WHAT_TEXT = N_("What")
DASH = "-"

def __value__(value, digits=0):
	if value is None:
		return DASH
	return ("{0:." + str(digits) + "f}").format(value)

class CodeQualityOutput(Outputable):
	def __init__(self, data):
		self.data = data
		Outputable.__init__(self)

	def output_text(self):
		authors = self.data.get_authors()
		print("\n" + textwrap.fill(_(QUALITY_INFO_TEXT) + ":", width=terminal.get_size()[0]))
		print(textwrap.fill(_(QUALITY_NOTE_TEXT), width=terminal.get_size()[0]) + "\n")

		if not authors:
			print(_(NO_SCRIPTS_TEXT) + ".")
			return

		terminal.printb(terminal.ljust(_("Author"), 21) + terminal.rjust(_("Lines"), 6) + terminal.rjust(_("Funcs"), 6) +
		                terminal.rjust(_("Typed%"), 7) + terminal.rjust(_("Doc%"), 5) + terminal.rjust(_("Names%"), 7) +
		                terminal.rjust(_("Fn len"), 7) + terminal.rjust(_("Nest"), 5) + terminal.rjust(_("Dbg"), 5) +
		                terminal.rjust(_("Magic"), 6) + terminal.rjust(_("Dup%"), 5) + terminal.rjust(_("Score"), 6) +
		                "  " + _("Level"))

		for (author, measures) in sorted(authors.items()):
			facts = measures.as_dict()
			print(terminal.ljust(author, 20)[0:20 - terminal.get_excess_column_count(author)], end=" ")
			print("{0}".format(facts["code_lines"]).rjust(5), "{0}".format(facts["functions"]).rjust(5),
			      __value__(facts["typed_pct"]).rjust(6), __value__(facts["functions_documented_pct"]).rjust(4),
			      __value__(facts["naming_conforming_pct"]).rjust(6), __value__(facts["median_function_length"]).rjust(6),
			      "{0}".format(facts["max_nesting"]).rjust(4), __value__(facts["debug_prints_per_100"], 1).rjust(4),
			      __value__(facts["magic_numbers_per_100"], 1).rjust(5), __value__(facts["duplicate_lines_pct"]).rjust(4),
			      __value__(facts["score"]).rjust(5), " " + _(codequality.LEVEL_TEXT[facts["level"]]))

		print("")
		terminal.printb(terminal.ljust(_("Author"), 21) + terminal.rjust(_("Good%"), 6) + terminal.rjust(_("Fair%"), 6) +
		                terminal.rjust(_("Poor%"), 6) + terminal.rjust(_("Polished%"), 10) + terminal.rjust(_("Chunks"), 7) +
		                terminal.rjust(_("AI-like"), 8))
		for author in sorted(authors):
			ratios = self.data.ratios.get(author, {})
			print(terminal.ljust(author, 20)[0:20 - terminal.get_excess_column_count(author)], end=" ")
			print(__value__(ratios.get("good")).rjust(5), __value__(ratios.get("fair")).rjust(5),
			      __value__(ratios.get("poor")).rjust(5), __value__(ratios.get("polished")).rjust(9),
			      "{0}".format(ratios.get("chunks", 0)).rjust(6), "{0}".format(ratios.get("flagged", 0)).rjust(7))

		if self.data.flagged:
			print("\n" + _(FLAGGED_TEXT) + ":")
			for chunk in self.data.flagged[:15]:
				print(textwrap.fill("{0}: {1} @ {2}, {3} lines, polish {4:.0f} against a usual {5:.0f}: {6}".format(
				      chunk.author, chunk.filename, chunk.revision[:8], chunk.measures.code, chunk.polish, chunk.baseline,
				      ", ".join(chunk.reasons)), width=terminal.get_size()[0], initial_indent="  ", subsequent_indent="      "))

	def output_html(self):
		authors = self.data.get_authors()
		if not authors:
			print(html_card(_(QUALITY_INFO_TEXT), "<div class=\"gi-card-head\"><div class=\"gi-sub\">" +
			                escape(_(NO_SCRIPTS_TEXT)) + ".</div></div>"))
			return

		indices = author_indices(authors.keys())
		rows = ""
		for (author, measures) in sorted(authors.items()):
			facts = measures.as_dict()
			ratios = self.data.ratios.get(author, {})
			rows += "<tr data-gi-searchable=\"authors\">" + html_author_cell(author, indices[author])
			rows += html_number_cell(_("Lines"), facts["code_lines"])
			rows += html_number_cell(_("Functions"), facts["functions"])
			for (label, key) in ((_("Typed %"), "typed_pct"), (_("Documented %"), "functions_documented_pct"),
			                     (_("Names %"), "naming_conforming_pct"), (_("Median function length"), "median_function_length")):
				rows += html_number_cell(label, __value__(facts[key]))
			rows += html_number_cell(_("Nesting"), facts["max_nesting"])
			for (label, key) in ((_("Debug prints /100"), "debug_prints_per_100"), (_("Magic numbers /100"), "magic_numbers_per_100"),
			                     (_("Duplicate %"), "duplicate_lines_pct")):
				rows += html_number_cell(label, __value__(facts[key], 1))
			rows += html_meter_cell(_("Score"), facts["score"] or 0.0)
			rows += "<td>" + escape(_(codequality.LEVEL_TEXT[facts["level"]])) + "</td>"
			rows += html_number_cell(_("Good %"), __value__(ratios.get("good")))
			rows += html_number_cell(_("Poor %"), __value__(ratios.get("poor")))
			rows += html_number_cell(_("Polished %"), __value__(ratios.get("polished")))
			rows += "</tr>"

		headers = ("<thead><tr>" + html_header_cell(_("Author")) + html_header_cell(_("Lines"), True) +
		           html_header_cell(_("Functions"), True) + html_header_cell(_("Typed %"), True) +
		           html_header_cell(_("Documented %"), True) + html_header_cell(_("Names %"), True) +
		           html_header_cell(_("Median function length"), True) + html_header_cell(_("Nesting"), True) +
		           html_header_cell(_("Debug prints /100"), True) + html_header_cell(_("Magic numbers /100"), True) +
		           html_header_cell(_("Duplicate %"), True) + html_header_cell(_("Score"), True) +
		           html_header_cell(_("Level")) + html_header_cell(_("Good %"), True) + html_header_cell(_("Poor %"), True) +
		           html_header_cell(_("Polished %"), True) + "</tr></thead>")
		body = html_table("quality", headers + "<tbody>" + rows + "</tbody>")

		if self.data.flagged:
			items = "".join("<li><strong>{0}</strong>: {1} @ {2}, {3} lines, polish {4:.0f} against a usual {5:.0f}: {6}</li>".format(
			                escape(chunk.author), escape(chunk.filename), chunk.revision[:8], chunk.measures.code, chunk.polish,
			                chunk.baseline, escape(", ".join(chunk.reasons))) for chunk in self.data.flagged[:15])
			body += "<div class=\"gi-card-head\"><div class=\"gi-sub\">" + escape(_(FLAGGED_TEXT)) + ":</div><ul>" + items + "</ul></div>"

		print(html_card(_(QUALITY_INFO_TEXT), body, subtitle=_(QUALITY_NOTE_TEXT)))

	def output_json(self):
		data = self.data.as_dict()
		data["message"] = _(QUALITY_INFO_TEXT)
		data["note"] = _(QUALITY_NOTE_TEXT)
		print(",\n\t\t\"code_quality\": " + json_block(data, 2).lstrip("\t"), end="")

	def output_xml(self):
		data = self.data.as_dict()
		data["message"] = _(QUALITY_INFO_TEXT)
		data["note"] = _(QUALITY_NOTE_TEXT)
		print(xml_element("code-quality", data, 1), end="")
