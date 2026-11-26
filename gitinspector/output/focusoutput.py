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
from .. import focus, terminal
from .outputable import (Outputable, author_indices, html_author_cell, html_card, html_header_cell, html_number_cell,
                         html_table, json_block, xml_element)

FOCUS_INFO_TEXT = N_("The following shows where each author's changes went, by kind of file")
FOCUS_NOTE_TEXT = N_("Shares are of authored lines (scripts, shaders, scenes, docs, data, config). Scene files are "
                     "written by the editor as a level is laid out; asset and generated files are counted as files, "
                     "since their line counts say nothing about who wrote what.")
NO_CHANGES_TEXT = N_("No changes were found in the interval")

class FocusOutput(Outputable):
	def __init__(self, data):
		self.data = data
		Outputable.__init__(self)

	def output_text(self):
		entries = self.data.get_entries()
		print("\n" + textwrap.fill(_(FOCUS_INFO_TEXT) + ":", width=terminal.get_size()[0]))
		print(textwrap.fill(_(FOCUS_NOTE_TEXT), width=terminal.get_size()[0]) + "\n")

		if not entries:
			print(_(NO_CHANGES_TEXT) + ".")
			return

		terminal.printb(terminal.ljust(_("Author"), 21) + terminal.rjust(_("Scripts"), 8) + terminal.rjust(_("Shaders"), 8) +
		                terminal.rjust(_("Scenes"), 7) + terminal.rjust(_("Docs"), 6) + terminal.rjust(_("Data"), 6) +
		                terminal.rjust(_("Assets"), 7) + terminal.rjust(_("Gen."), 6) + "  " + _("Focus"))

		for (author, entry) in sorted(entries.items()):
			print(terminal.ljust(author, 20)[0:20 - terminal.get_excess_column_count(author)], end=" ")
			print("{0}".format(entry.lines["scripts"]).rjust(7), "{0}".format(entry.lines["shaders"]).rjust(7),
			      "{0}".format(entry.lines["scenes"]).rjust(6), "{0}".format(entry.lines["docs"]).rjust(5),
			      "{0}".format(entry.lines["data"]).rjust(5), "{0}f".format(entry.files["assets"]).rjust(6),
			      "{0}f".format(entry.files["generated"]).rjust(5), " " + entry.label())

	def output_html(self):
		entries = self.data.get_entries()
		if not entries:
			print(html_card(_(FOCUS_INFO_TEXT), "<div class=\"gi-card-head\"><div class=\"gi-sub\">" +
			                escape(_(NO_CHANGES_TEXT)) + ".</div></div>"))
			return

		indices = author_indices(entries.keys())
		rows = ""
		for (author, entry) in sorted(entries.items()):
			rows += "<tr data-gi-searchable=\"authors\">" + html_author_cell(author, indices[author])
			for category in ("scripts", "shaders", "scenes", "docs", "data"):
				rows += html_number_cell(_(focus.CATEGORY_TEXT[category]), entry.lines[category])
			rows += html_number_cell(_("Asset files"), entry.files["assets"])
			rows += html_number_cell(_("Generated files"), entry.files["generated"])
			rows += "<td>" + escape(entry.label()) + "</td></tr>"

		headers = ("<thead><tr>" + html_header_cell(_("Author")) + html_header_cell(_("Scripts"), True) +
		           html_header_cell(_("Shaders"), True) + html_header_cell(_("Scenes"), True) +
		           html_header_cell(_("Docs"), True) + html_header_cell(_("Data"), True) +
		           html_header_cell(_("Asset files"), True) + html_header_cell(_("Generated files"), True) +
		           html_header_cell(_("Focus")) + "</tr></thead>")
		print(html_card(_(FOCUS_INFO_TEXT), html_table("focus", headers + "<tbody>" + rows + "</tbody>"),
		                subtitle=_(FOCUS_NOTE_TEXT)))

	def output_json(self):
		data = self.data.as_dict()
		data["message"] = _(FOCUS_INFO_TEXT)
		print(",\n\t\t\"focus\": " + json_block(data, 2).lstrip("\t"), end="")

	def output_xml(self):
		data = self.data.as_dict()
		data["message"] = _(FOCUS_INFO_TEXT)
		print(xml_element("focus", data, 1), end="")
