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
import atexit
import getopt
import os
import sys
from collections import OrderedDict
from .blame import Blame
from .changes import Changes
from .codequality import CodeQuality
from .config import GitConfig
from .focus import Focus
from .metrics import MetricsLogic
from . import (basedir, clone, extensions, filtering, format, git, gitlab, help, interval,
               llm, localization, optval, terminal, version, workers)
from .output import outputable
from .output.blameoutput import BlameOutput
from .output.changesoutput import ChangesOutput
from .output.codequalityoutput import CodeQualityOutput
from .output.extensionsoutput import ExtensionsOutput
from .output.filteringoutput import FilteringOutput
from .output.focusoutput import FocusOutput
from .output.gitlaboutput import GitLabOutput
from .output.llmoutput import LLMOutput
from .output.metricsoutput import MetricsOutput
from .output.responsibilitiesoutput import ResponsibilitiesOutput
from .output.timelineoutput import TimelineOutput

localization.init()

class Runner(object):
	def __init__(self):
		self.hard = False
		self.include_metrics = False
		self.list_file_types = False
		self.localize_output = False
		self.responsibilities = False
		self.grading = False
		self.timeline = False
		self.useweeks = False
		self.forcemonths = False
		self.focus = False
		self.code_quality = False
		self.gitlab = False
		self.gitlab_url = None
		self.gitlab_token = None
		self.gitlab_token_config = None
		self.gitlab_dump = None
		self.gitlab_aliases = None
		self.llm = llm.Settings()

	def wants_gitlab(self):
		return bool(self.gitlab or self.gitlab_url or self.gitlab_dump)

	def __gitlab_data__(self, repo):
		"""The issues and milestones of the project behind this repository, joined to its history.
		Runs inside the repository, so the git log and the origin remote are the right ones."""
		if self.gitlab_dump:
			data = gitlab.GitLabData.from_dump(self.gitlab_dump)
		else:
			data = gitlab.GitLabData.from_api(repo.location, self.gitlab_url, self.gitlab_token)

		if self.gitlab_aliases:
			data.aliases = gitlab.load_aliases(self.gitlab_aliases)
		if format.is_interactive_format():
			terminal.clear_line()
		return data.join(repo.location)

	def __assessment__(self, repos, changes, blames, metrics, gitlab_data, focus_data=None, quality_data=None):
		evidence = llm.build_evidence(repos, changes, blames, metrics if self.include_metrics else None,
		                              gitlab_data, self.useweeks, focus_data, quality_data)
		if format.is_interactive_format():
			print(_("Asking {0} for an assessment of the statistics...").format(llm.describe(self.llm)), file=sys.stderr)

		try:
			return LLMOutput(self.llm, llm.assess(self.llm, evidence))
		except llm.LLMError as error:
			return LLMOutput(self.llm, error=error.msg)

	def process(self, repos):
		localization.check_compatibility(version.__version__)

		if not self.localize_output:
			localization.disable()

		terminal.skip_escapes(not sys.stdout.isatty())
		previous_directory = os.getcwd()
		summed_blames = Blame.__new__(Blame)
		summed_changes = Changes.__new__(Changes)
		summed_metrics = MetricsLogic.__new__(MetricsLogic)
		summed_focus = Focus.__new__(Focus)
		summed_quality = CodeQuality.__new__(CodeQuality)
		gitlab_data = None
		#One row per student in the focus and quality sections, however many git identities they used.
		aliases = gitlab.load_aliases(self.gitlab_aliases) if self.gitlab_aliases else {}
		resolver = None

		for repo in repos:
			os.chdir(repo.location)
			interval.check(repo.name)
			#The tracker belongs to one project; with several repositories the first one's is used.
			if self.wants_gitlab() and gitlab_data is None:
				gitlab_data = self.__gitlab_data__(repo)
			if resolver is None and (gitlab_data is not None or aliases):
				resolver = gitlab.make_resolver(gitlab_data.users if gitlab_data is not None else [], aliases)
			repo = repo if len(repos) > 1 else None
			changes = Changes(repo, self.hard)
			summed_blames += Blame(repo, self.hard, self.useweeks, changes)
			summed_changes += changes

			if self.include_metrics:
				summed_metrics += MetricsLogic()

			if self.focus:
				summed_focus += Focus(repo, resolver)

			if self.code_quality:
				summed_quality += CodeQuality(repo, changes, self.hard, resolver)

			__clear_progress__()
		else:
			os.chdir(previous_directory)

		assessment = None
		if self.llm.is_enabled() and summed_changes.get_commits():
			assessment = self.__assessment__(repos, summed_changes, summed_blames, summed_metrics, gitlab_data,
			                                 summed_focus if self.focus else None,
			                                 summed_quality if self.code_quality else None)

		format.output_header(repos)
		outputable.output(ChangesOutput(summed_changes))

		if summed_changes.get_commits():
			outputable.output(BlameOutput(summed_changes, summed_blames, self.forcemonths))

			if self.timeline:
				if self.useweeks and self.forcemonths:
					outputable.output(TimelineOutput(summed_changes, False))
				outputable.output(TimelineOutput(summed_changes, self.useweeks))

			if self.include_metrics:
				outputable.output(MetricsOutput(summed_metrics))

			if self.responsibilities:
				outputable.output(ResponsibilitiesOutput(summed_changes, summed_blames))

			if self.focus:
				outputable.output(FocusOutput(summed_focus))

			if self.code_quality:
				outputable.output(CodeQualityOutput(summed_quality))

			if gitlab_data is not None:
				outputable.output(GitLabOutput(gitlab_data))

			outputable.output(FilteringOutput())

			if self.list_file_types:
				outputable.output(ExtensionsOutput())

			if assessment is not None:
				outputable.output(assessment)

		format.output_footer()
		os.chdir(previous_directory)

def __clear_progress__():
	if format.is_interactive_format():
		terminal.clear_line()

def __check_python_version__():
	if sys.version_info < (2, 6):
		python_version = str(sys.version_info[0]) + "." + str(sys.version_info[1])
		sys.exit(_("gitinspector requires at least Python 2.6 to run (version {0} was found).").format(python_version))

def __get_validated_git_repos__(repos_relative):
	if not repos_relative:
		repos_relative = "."

	repos = []

	#Try to clone the repos or return the same directory and bail out.
	for repo in repos_relative:
		cloned_repo = clone.create(repo)

		if cloned_repo.name == None:
			cloned_repo.location = basedir.get_basedir_git(cloned_repo.location)
			cloned_repo.name = os.path.basename(cloned_repo.location)

		cloned_repo.branch = git.get_branch(cloned_repo.location)
		repos.append(cloned_repo)

	return repos

def main():
	#The streams are taken over before anything is written, so that --version and --help also survive
	#a console encoding that Python has no codec for.
	terminal.set_stderr_encoding()
	terminal.check_terminal_encoding()
	terminal.set_stdout_encoding()
	terminal.set_stdin_encoding()
	argv = terminal.convert_command_line_to_utf8()
	run = Runner()
	repos = []

	try:
		opts, args = optval.gnu_getopt(argv[1:], "f:F:hHlLmrTwMx:QC", ["exclude=", "file-types=", "format=",
		                                         "hard:true", "help", "list-file-types:true", "localize-output:true",
		                                         "metrics:true", "responsibilities:true", "since=", "grading:true",
		                                         "timeline:true", "until=", "version", "weeks:true", "forcemonths:true",
		                                         "focus:true", "code-quality:true",
		                                         "gitlab:true", "gitlab-url=", "gitlab-token=", "gitlab-dump=", "gitlab-aliases=",
		                                         "llm=", "llm-model=", "llm-url=", "llm-prompt=", "llm-max-tokens=",
		                                         "llm-timeout="])
		#Neither of these describes a repository, and looking for one fails outside a working tree.
		for o, a in opts:
			if o in("-h", "--help"):
				help.output()
				sys.exit(0)
			elif o == "--version":
				version.output()
				sys.exit(0)

		if not git.is_available():
			sys.exit(_("The git executable could not be started. gitinspector needs it in the PATH to run."))

		repos = __get_validated_git_repos__(list(OrderedDict.fromkeys(args)))

		#We need the repos above to be set before we read the git config.
		GitConfig(run, repos[-1].location).read()
		clear_x_on_next_pass = True

		for o, a in opts:
			if o in("-f", "--file-types"):
				extensions.define(a)
			elif o in("-F", "--format"):
				if not format.select(a):
					raise format.InvalidFormatError(_("specified output format not supported."))
			elif o == "-H":
				run.hard = True
			elif o == "--hard":
				run.hard = optval.get_boolean_argument(a)
			elif o == "-l":
				run.list_file_types = True
			elif o == "--list-file-types":
				run.list_file_types = optval.get_boolean_argument(a)
			elif o == "-L":
				run.localize_output = True
			elif o == "--localize-output":
				run.localize_output = optval.get_boolean_argument(a)
			elif o == "-m":
				run.include_metrics = True
			elif o == "--metrics":
				run.include_metrics = optval.get_boolean_argument(a)
			elif o == "-r":
				run.responsibilities = True
			elif o == "--responsibilities":
				run.responsibilities = optval.get_boolean_argument(a)
			elif o == "--since":
				interval.set_since(a)
			elif o == "--grading":
				grading = optval.get_boolean_argument(a)
				run.include_metrics = grading
				run.list_file_types = grading
				run.responsibilities = grading
				run.grading = grading
				run.hard = grading
				run.timeline = grading
				run.useweeks = grading
				run.focus = grading
				run.code_quality = grading
			elif o == "-C":
				run.focus = True
			elif o == "--focus":
				run.focus = optval.get_boolean_argument(a)
			elif o == "-Q":
				run.code_quality = True
			elif o == "--code-quality":
				run.code_quality = optval.get_boolean_argument(a)
			elif o == "-T":
				run.timeline = True
			elif o == "--timeline":
				run.timeline = optval.get_boolean_argument(a)
			elif o == "--until":
				interval.set_until(a)
			elif o == "-w":
				run.useweeks = True
			elif o == "--weeks":
				run.useweeks = optval.get_boolean_argument(a)
			elif o == "-M":
				run.forcemonths = True
			elif o == "--forcemonths":
				run.forcemonths = optval.get_boolean_argument(a)
			elif o in("-x", "--exclude"):
				if clear_x_on_next_pass:
					clear_x_on_next_pass = False
					filtering.clear()
				filtering.add(a)
			elif o == "--gitlab":
				run.gitlab = optval.get_boolean_argument(a)
			elif o == "--gitlab-url":
				run.gitlab_url = a
			elif o == "--gitlab-token":
				run.gitlab_token = a
			elif o == "--gitlab-dump":
				run.gitlab_dump = a
			elif o == "--gitlab-aliases":
				run.gitlab_aliases = a
			elif o == "--llm":
				run.llm.backend = llm.select(a)
			elif o == "--llm-model":
				run.llm.model = a
			elif o == "--llm-url":
				run.llm.url = a
			elif o == "--llm-prompt":
				run.llm.prompt_file = a
			elif o == "--llm-max-tokens":
				run.llm.max_tokens = optval.get_positive_integer_argument(a)
			elif o == "--llm-timeout":
				run.llm.timeout = optval.get_positive_integer_argument(a)

		run.gitlab_token = gitlab.resolve_token(run.gitlab_token, run.gitlab_token_config)
		__check_python_version__()
		run.process(repos)

	except workers.OutOfResourcesError as error:
		__clear_progress__()
		sys.exit(error.msg)
	except (filtering.InvalidRegExpError, format.InvalidFormatError, optval.InvalidOptionArgument, getopt.error,
	        gitlab.GitLabError, llm.LLMError) as exception:
		__clear_progress__()
		print(sys.argv[0], "\b:", exception.msg, file=sys.stderr)
		print(_("Try `{0} --help' for more information.").format(sys.argv[0]), file=sys.stderr)
		sys.exit(2)

@atexit.register
def cleanup():
	clone.delete()

if __name__ == "__main__":
	main()
