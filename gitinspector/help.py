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
import sys
from .extensions import DEFAULT_EXTENSIONS
from .format import __available_formats__
from .llm import BACKENDS, DEFAULT_LOCAL_URL


__doc__ = _("""Usage: {0} [OPTION]... [REPOSITORY]...
List information about the repository in REPOSITORY. If no repository is
specified, the current directory is used. If multiple repositories are
given, information will be merged into a unified statistical report.

Mandatory arguments to long options are mandatory for short options too.
Boolean arguments can only be given to long options.
  -f, --file-types=EXTENSIONS    a comma separated list of file extensions to
                                   include when computing statistics. The
                                   default extensions used are:
                                   {1}
                                   Specifying * includes files with no
                                   extension, while ** includes all files
  -F, --format=FORMAT            define in which format output should be
                                   generated; the default format is 'text' and
                                   the available formats are:
                                   {2}
      --grading[=BOOL]           show statistics and information in a way that
                                   is formatted for grading of student
                                   projects; this is the same as supplying the
                                   options -HlmrTwCQ
  -C, --focus[=BOOL]             show where each author's changes went: scripts,
                                   shaders, scenes, docs, data, assets or files
                                   the engine generates
  -Q, --code-quality[=BOOL]      read the script lines each author owns and rate
                                   them: typing, naming, documentation, function
                                   length, nesting, debug prints, magic numbers,
                                   duplication; with the share of each author's
                                   code that looks polished enough to have been
                                   generated
  -H, --hard[=BOOL]              track lines and look for duplicates harder;
                                   this can be quite slow with big repositories
  -l, --list-file-types[=BOOL]   list all the file extensions available in the
                                   current branch of the repository
  -L, --localize-output[=BOOL]   localize the generated output to the selected
                                   system language if a translation is
                                   available
  -m, --metrics[=BOOL]           include checks for certain metrics during the
                                   analysis of commits
  -M, --forcemonths[=BOOL]       show statistics in months as well as in weeks
                                   when -w is used
  -r, --responsibilities[=BOOL]  show which files the different authors seem
                                   most responsible for
      --since=DATE|rev:REV       only show statistics for commits more recent
                                   than a specific date, or from a specific
                                   revision on
  -T, --timeline[=BOOL]          show commit timeline, including author names
      --until=DATE|rev:REV       only show statistics for commits made up to
                                   a specific date or revision
  -w, --weeks[=BOOL]             show all statistical information in weeks
                                   instead of in months
  -x, --exclude=PATTERN          an exclusion pattern describing the file
                                   paths, revisions, revisions with certain
                                   commit messages, author names or author
                                   emails that should be excluded from the
                                   statistics; can be specified multiple times
      --gitlab[=BOOL]            fetch the issues and milestones of the GitLab
                                   project behind the origin remote and join
                                   them to the commits (who planned, who was
                                   assigned, who committed against what)
      --gitlab-url=URL           the GitLab project to read instead of the one
                                   inferred from the origin remote
      --gitlab-token=TOKEN       a personal access token with the read_api
                                   scope; $GITLAB_TOKEN and the git config
                                   inspector.gitlab-token are read as well
      --gitlab-dump=FILE         read the issues and milestones from a JSON
                                   dump of the API objects instead of the API
      --gitlab-aliases=FILE      a JSON file mapping commit e-mail addresses
                                   or author names to GitLab usernames, for
                                   students who commit from a personal address
      --llm=BACKEND              have a language model write an assessment of
                                   the statistics; BACKEND is one of {3}
                                   ("local" is any OpenAI-compatible server
                                   such as Ollama or LM Studio, "claude" the
                                   Anthropic API, "claude-code" the Claude
                                   Code command line tool on a subscription)
      --llm-model=NAME           the model the backend should use
      --llm-url=URL              the base URL of the local model server; the
                                   default is {4}
      --llm-prompt=FILE          a file with extra instructions for the model,
                                   such as the rubric of the course
      --llm-max-tokens=N         the longest answer the model may write
      --llm-timeout=SECONDS      how long to wait for the model
  -h, --help                     display this help and exit
      --version                  output version information and exit

gitinspector will filter statistics to only include commits that modify,
add or remove one of the specified extensions, see -f or --file-types for
more information.

gitinspector requires that the git executable is available in your PATH.
Report gitinspector bugs to gitinspector@ejwa.se.""")

def output():
	print(__doc__.format(sys.argv[0], ",".join(DEFAULT_EXTENSIONS), ",".join(__available_formats__),
	                     ",".join(BACKENDS), DEFAULT_LOCAL_URL))
