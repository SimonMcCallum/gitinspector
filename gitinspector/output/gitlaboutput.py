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
from .. import format, terminal
from .outputable import (Outputable, grouped, html_card, html_header_cell, html_number_cell, html_stats,
                         html_table, json_block, percentage, xml_element)

ISSUES_INFO_TEXT = N_("The following issue and milestone information was gathered from GitLab for the project '{0}'")
ISSUES_TOTALS_TEXT = N_("{0} issues ({1} open, {2} closed); {3} without an assignee, {4} without a milestone; "
                        "{5} of {6} commits reference an issue ({7:.1f}%); {8} issues are referenced by a commit")
MILESTONES_TEXT = N_("Milestones")
NO_MILESTONES_TEXT = N_("No milestones were found")
NO_ISSUES_TEXT = N_("No issues were found")
UNMATCHED_TEXT = N_("Commits by authors that matched no GitLab user")
INACTIVE_TEXT = N_("Members with no commits and no issues")
MISASSIGNED_TEXT = N_("Issues where someone other than the assignee did the committing")
OVERDUE_TEXT = N_("overdue")

#Kept under the old names for anything that imported them from here.
__json_block__ = json_block
__xml_element__ = xml_element

class GitLabOutput(Outputable):
	def __init__(self, data):
		self.data = data
		Outputable.__init__(self)

	def __totals_text__(self):
		totals = self.data.totals()
		return _(ISSUES_TOTALS_TEXT).format(totals["issues"], totals["open"], totals["closed"], totals["unassigned"],
		                                    totals["without_milestone"], totals["commits_linked"], totals["commits"],
		                                    percentage(totals["commits_linked"], totals["commits"]),
		                                    totals["referenced_by_commits"])

	def __milestone_state__(self, milestone):
		if milestone.is_overdue():
			return _(OVERDUE_TEXT)
		return milestone.state

	def output_text(self):
		print("\n" + textwrap.fill(_(ISSUES_INFO_TEXT).format(self.data.project_name) + ":", width=terminal.get_size()[0]))
		print(textwrap.fill(self.__totals_text__() + ".", width=terminal.get_size()[0]) + "\n")

		if self.data.active_users():
			terminal.printb(terminal.ljust(_("User"), 21) + terminal.rjust(_("Commits"), 8) + terminal.rjust(_("Linked"), 7) +
			                terminal.rjust(_("Cited"), 6) + terminal.rjust(_("Made"), 5) + terminal.rjust(_("Assigned"), 9) +
			                terminal.rjust(_("Closed"), 7) + terminal.rjust(_("Done self"), 10) +
			                terminal.rjust(_("By other"), 9) + terminal.rjust(_("Untouched"), 10))

			for user in self.data.active_users():
				label = user.username
				print(terminal.ljust(label, 20)[0:20 - terminal.get_excess_column_count(label)], end=" ")
				print("{0}".format(user.commits).rjust(7), "{0}".format(user.commits_linked).rjust(6),
				      "{0}".format(len(user.issues_referenced)).rjust(5), "{0}".format(user.issues_created).rjust(4),
				      "{0}".format(user.issues_assigned).rjust(8), "{0}".format(user.issues_closed).rjust(6),
				      "{0}".format(user.assigned_done_self).rjust(9), "{0}".format(user.assigned_done_other).rjust(8),
				      "{0}".format(user.assigned_untouched).rjust(9))
		else:
			print(_(NO_ISSUES_TEXT) + ".")

		if self.data.inactive_users():
			print("\n" + textwrap.fill(_(INACTIVE_TEXT) + ": " + ", ".join(user.username for user in self.data.inactive_users()),
			                           width=terminal.get_size()[0]))

		if self.data.unmatched:
			print("\n" + _(UNMATCHED_TEXT) + ":")
			for (author, count) in sorted(self.data.unmatched.items()):
				print("  {0} ({1})".format(author, count))

		print("\n" + _(MILESTONES_TEXT) + ":")
		if self.data.milestones:
			terminal.printb(terminal.ljust(_("Milestone"), 31) + terminal.rjust(_("Due"), 11) + terminal.rjust(_("State"), 9) +
			                terminal.rjust(_("Issues"), 7) + terminal.rjust(_("Closed"), 7) + terminal.rjust(_("Done %"), 7) +
			                terminal.rjust(_("Linked commits"), 15))

			for milestone in self.data.milestones:
				print(terminal.ljust(milestone.title, 30)[0:30 - terminal.get_excess_column_count(milestone.title)], end=" ")
				print((milestone.due or "-").rjust(10), self.__milestone_state__(milestone).rjust(8),
				      "{0}".format(len(milestone.issues)).rjust(6), "{0}".format(len(milestone.closed_issues())).rjust(6),
				      "{0:.0f}".format(milestone.completion()).rjust(6), "{0}".format(milestone.linked_commits()).rjust(14))
		else:
			print(_(NO_MILESTONES_TEXT) + ".")

		misassigned = self.data.misassigned()
		if misassigned:
			print("\n" + _(MISASSIGNED_TEXT) + ":")
			for issue in misassigned[:20]:
				print("  #{0} {1} — {2}: {3}".format(issue.iid, issue.title[:50], ", ".join(issue.assignees),
				      ", ".join("{0} ({1})".format(who, count) for (who, count) in sorted(issue.committers.items()))))

	def output_html(self):
		totals = self.data.totals()
		print(html_stats(((_("Issues"), grouped(totals["issues"])),
		                  (_("Open"), grouped(totals["open"])),
		                  (_("Closed"), grouped(totals["closed"])),
		                  (_("Commits linked to an issue"), "{0:.1f}%".format(percentage(totals["commits_linked"], totals["commits"]))),
		                  (_(MILESTONES_TEXT), grouped(totals["milestones"])))))

		rows = ""
		for user in self.data.active_users():
			rows += "<tr data-gi-searchable=\"authors\"><td>" + escape(user.username)
			if user.name:
				rows += " <span class=\"gi-sub\">" + escape(user.name) + "</span>"
			if user.git_authors:
				rows += "<div class=\"gi-sub\">" + escape(", ".join(sorted(user.git_authors))) + "</div>"
			rows += "</td>"
			rows += html_number_cell(_("Commits"), user.commits)
			rows += html_number_cell(_("Linked"), user.commits_linked)
			rows += html_number_cell(_("Issues cited"), len(user.issues_referenced))
			rows += html_number_cell(_("Created"), user.issues_created)
			rows += html_number_cell(_("Assigned"), user.issues_assigned)
			rows += html_number_cell(_("Closed"), user.issues_closed)
			rows += html_number_cell(_("Done self"), user.assigned_done_self)
			rows += html_number_cell(_("By other"), user.assigned_done_other)
			rows += html_number_cell(_("Untouched"), user.assigned_untouched)
			rows += "</tr>"

		headers = ("<thead><tr>" + html_header_cell(_("User")) + html_header_cell(_("Commits"), True) +
		           html_header_cell(_("Linked"), True) + html_header_cell(_("Issues cited"), True) +
		           html_header_cell(_("Created"), True) + html_header_cell(_("Assigned"), True) +
		           html_header_cell(_("Closed"), True) + html_header_cell(_("Done self"), True) +
		           html_header_cell(_("By other"), True) + html_header_cell(_("Untouched"), True) + "</tr></thead>")
		body = html_table("gitlab-users", headers + "<tbody>" + rows + "</tbody>")

		notes = ""
		if self.data.inactive_users():
			notes += ("<div class=\"gi-sub\">" + escape(_(INACTIVE_TEXT)) + ": " +
			          escape(", ".join(user.username for user in self.data.inactive_users())) + "</div>")
		if self.data.unmatched:
			notes += ("<div class=\"gi-sub\">" + escape(_(UNMATCHED_TEXT)) + ": " +
			          escape(", ".join("{0} ({1})".format(author, count) for (author, count) in sorted(self.data.unmatched.items()))) +
			          "</div>")
		if notes:
			body += "<div class=\"gi-card-head\">" + notes + "</div>"

		print(html_card(_(ISSUES_INFO_TEXT).format(self.data.project_name), body, subtitle=self.__totals_text__()))

		rows = ""
		for milestone in self.data.milestones:
			rows += "<tr><td>" + escape(milestone.title) + "</td>"
			rows += "<td data-gi-value=\"" + escape(milestone.due) + "\">" + escape(milestone.due or "-") + "</td>"
			rows += "<td>" + escape(self.__milestone_state__(milestone)) + "</td>"
			rows += html_number_cell(_("Issues"), len(milestone.issues))
			rows += html_number_cell(_("Closed"), len(milestone.closed_issues()))
			rows += html_number_cell(_("Done %"), "{0:.0f}".format(milestone.completion()))
			rows += html_number_cell(_("Linked commits"), milestone.linked_commits())
			rows += "</tr>"

		if rows:
			headers = ("<thead><tr>" + html_header_cell(_("Milestone")) + html_header_cell(_("Due")) +
			           html_header_cell(_("State")) + html_header_cell(_("Issues"), True) +
			           html_header_cell(_("Closed"), True) + html_header_cell(_("Done %"), True) +
			           html_header_cell(_("Linked commits"), True) + "</tr></thead>")
			body = html_table("gitlab-milestones", headers + "<tbody>" + rows + "</tbody>")
		else:
			body = "<div class=\"gi-card-head\"><div class=\"gi-sub\">" + escape(_(NO_MILESTONES_TEXT)) + ".</div></div>"

		misassigned = self.data.misassigned()
		if misassigned:
			items = "".join("<li>#{0} {1} — {2}: {3}</li>".format(issue.iid, escape(issue.title),
			                escape(", ".join(issue.assignees)),
			                escape(", ".join("{0} ({1})".format(who, count) for (who, count) in sorted(issue.committers.items()))))
			                for issue in misassigned[:20])
			body += "<div class=\"gi-card-head\"><div class=\"gi-sub\">" + escape(_(MISASSIGNED_TEXT)) + ":</div><ul>" + items + "</ul></div>"

		print(html_card(_(MILESTONES_TEXT), body))

	def output_json(self):
		data = self.data.as_dict()
		data["message"] = _(ISSUES_INFO_TEXT).format(self.data.project_name)
		print(",\n\t\t\"gitlab\": " + json_block(data, 2).lstrip("\t"), end="")

	def output_xml(self):
		data = self.data.as_dict()
		data["message"] = _(ISSUES_INFO_TEXT).format(self.data.project_name)
		print(xml_element("gitlab", data, 1), end="")
