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
from .. import llm, terminal
from .outputable import Outputable, html_card, html_header_cell, html_table, json_block, xml_element

ASSESSMENT_INFO_TEXT = N_("The following assessment was written by {0} from the statistics in this report")
ASSESSMENT_FAILED_TEXT = N_("No assessment could be written by {0}: {1}")
SUMMARY_TEXT = N_("Summary")
PROCESS_TEXT = N_("How the team worked")
MEMBERS_TEXT = N_("Members")
MILESTONES_TEXT = N_("Plan and milestones")
RISKS_TEXT = N_("Things that may distort the picture")
QUESTIONS_TEXT = N_("Questions to ask")
CONFIDENCE_TEXT = N_("Confidence")
NOT_VERIFIED_TEXT = N_("A model wrote this from the numbers alone; check anything you rely on against the tables above.")

class LLMOutput(Outputable):
	def __init__(self, settings, assessment=None, error=None):
		self.settings = settings
		self.assessment = assessment
		self.error = error
		Outputable.__init__(self)

	def __writer__(self):
		return llm.describe(self.settings)

	def __paragraph__(self, title, text):
		if not text:
			return
		terminal.printb(title)
		print(textwrap.fill(text, width=terminal.get_size()[0]) + "\n")

	def output_text(self):
		if self.assessment is None:
			print("\n" + textwrap.fill(_(ASSESSMENT_FAILED_TEXT).format(self.__writer__(), self.error or ""),
			                           width=terminal.get_size()[0]))
			return

		print("\n" + textwrap.fill(_(ASSESSMENT_INFO_TEXT).format(self.__writer__()) + ". " + _(NOT_VERIFIED_TEXT),
		                           width=terminal.get_size()[0]) + "\n")
		self.__paragraph__(_(SUMMARY_TEXT), self.assessment["summary"])
		self.__paragraph__(_(PROCESS_TEXT), self.assessment["process"])

		if self.assessment["members"]:
			terminal.printb(_(MEMBERS_TEXT))
			for member in self.assessment["members"]:
				head = member["name"] + (" — " + member["role"] if member["role"] else "")
				print(terminal.__bold__ + head + terminal.__normal__)
				for (label, key) in ((None, "contribution"), (_("Evidence"), "evidence"), (_("Concerns"), "concerns")):
					if member[key]:
						text = (label + ": " if label else "") + member[key]
						print(textwrap.fill(text, width=terminal.get_size()[0], initial_indent="  ", subsequent_indent="  "))
				print("")

		self.__paragraph__(_(MILESTONES_TEXT), self.assessment["milestones"])

		for (title, key) in ((_(RISKS_TEXT), "risks"), (_(QUESTIONS_TEXT), "questions")):
			if self.assessment[key]:
				terminal.printb(title)
				for item in self.assessment[key]:
					print(textwrap.fill(item, width=terminal.get_size()[0], initial_indent="  - ", subsequent_indent="    "))
				print("")

		terminal.printb(_(CONFIDENCE_TEXT) + ": " + self.assessment["confidence"])

	def output_html(self):
		if self.assessment is None:
			print(html_card(_(ASSESSMENT_FAILED_TEXT).format(self.__writer__(), self.error or ""), "", pad=True))
			return

		body = ""
		for (title, key) in ((_(SUMMARY_TEXT), "summary"), (_(PROCESS_TEXT), "process")):
			if self.assessment[key]:
				body += "<h2>" + escape(title) + "</h2><p>" + escape(self.assessment[key]) + "</p>"

		if self.assessment["members"]:
			rows = ""
			for member in self.assessment["members"]:
				rows += ("<tr data-gi-searchable=\"authors\"><td>" + escape(member["name"]) + "</td><td>" + escape(member["role"]) +
				         "</td><td>" + escape(member["contribution"]) + "</td><td>" + escape(member["evidence"]) +
				         "</td><td>" + escape(member["concerns"]) + "</td></tr>")
			headers = ("<thead><tr>" + html_header_cell(_("Member")) + html_header_cell(_("Role")) +
			           html_header_cell(_("Contribution")) + html_header_cell(_("Evidence")) +
			           html_header_cell(_("Concerns")) + "</tr></thead>")
			body += "<h2>" + escape(_(MEMBERS_TEXT)) + "</h2>" + html_table("assessment", headers + "<tbody>" + rows + "</tbody>")

		if self.assessment["milestones"]:
			body += "<h2>" + escape(_(MILESTONES_TEXT)) + "</h2><p>" + escape(self.assessment["milestones"]) + "</p>"

		for (title, key) in ((_(RISKS_TEXT), "risks"), (_(QUESTIONS_TEXT), "questions")):
			if self.assessment[key]:
				body += ("<h2>" + escape(title) + "</h2><ul>" +
				         "".join("<li>" + escape(item) + "</li>" for item in self.assessment[key]) + "</ul>")

		body += "<div class=\"gi-sub\">" + escape(_(CONFIDENCE_TEXT) + ": " + self.assessment["confidence"]) + "</div>"
		print(html_card(_(ASSESSMENT_INFO_TEXT).format(self.__writer__()), body, subtitle=_(NOT_VERIFIED_TEXT), pad=True))

	def __document__(self):
		document = {"writer": self.__writer__(), "backend": self.settings.backend,
		            "model": self.settings.resolved_model() or ""}
		if self.assessment is None:
			document["error"] = self.error or ""
		else:
			document.update(self.assessment)
			document["message"] = _(ASSESSMENT_INFO_TEXT).format(self.__writer__())
		return document

	def output_json(self):
		print(",\n\t\t\"assessment\": " + json_block(self.__document__(), 2).lstrip("\t"), end="")

	def output_xml(self):
		print(xml_element("assessment", self.__document__(), 1), end="")
