[![Latest release](https://img.shields.io/github/release/ejwa/gitinspector.svg?style=flat-square)](https://github.com/ejwa/gitinspector/releases/latest)
[![Tests](https://img.shields.io/github/actions/workflow/status/ejwa/gitinspector/tests.yml?branch=master&label=tests&style=flat-square)](https://github.com/ejwa/gitinspector/actions/workflows/tests.yml)
[![License](https://img.shields.io/github/license/ejwa/gitinspector.svg?style=flat-square)](https://github.com/ejwa/gitinspector/blob/master/LICENSE.txt)

## About Gitinspector
<img align="left" height="100px"
     src="https://raw.githubusercontent.com/ejwa/gitinspector/master/gitinspector/html/gitinspector_piclet.png"/>


<a href="https://ejwa.github.io/gitinspector/examples/gitinspector_output.html"><img align="right" width="30%" src="https://ejwa.github.io/gitinspector/images/html_example.png" /></a> 
Gitinspector is a statistical analysis tool for git repositories. The default analysis shows general statistics per author, which can be complemented with a timeline analysis that shows the workload and activity of each author. Under normal operation, it filters the results to only show statistics about a number of given extensions and by default only includes source files in the statistical analysis.

This tool was originally written to help fetch repository statistics from student projects in the course Object-oriented Programming Project (TDA367/DIT211) at Chalmers University of Technology and Gothenburg University.

Today, gitinspector is used as a grading aid by universities worldwide.

A full [Documentation](https://github.com/ejwa/gitinspector/wiki/Documentation) of the usage and available options of gitinspector is available on the wiki. For help on the most common questions, please refer to the [FAQ](https://github.com/ejwa/gitinspector/wiki/FAQ) document.

### Some of the features
  * Shows cumulative work by each author in the history.
  * Filters results by extension (default: java,c,cc,cpp,h,hh,hpp,php,py,glsl,rb,js,sql,go,swift,ts,tsx,rs,groovy,gd,gdshader,gdshaderinc,cs,hlsl,shader,usf,ush).
  * Knows the game engines: GDScript and gdshader (Godot), C# (Godot, Unity) and the Unity and Unreal shader languages get comment recognition and complexity metrics.
  * Shows where each author's changes went (`--focus`): scripts, shaders, editor-written scenes, docs, data, assets, generated files.
  * Rates the script lines each author owns (`--code-quality`): typing, naming, documentation, function length, nesting, debug prints, magic numbers, duplication, with a level band and the share of code that looks polished enough to have been generated.
  * Can display a statistical timeline analysis.
  * Scans for all filetypes (by extension) found in the repository.
  * Multi-threaded; uses multiple instances of git to speed up analysis when possible.
  * Supports HTML, JSON, XML and plain text output (console).
  * Generates responsive HTML reports with a light and a dark mode, sortable tables and a search box, that work on phones as well.
  * Can report violations of different code metrics.
  * Joins the issues and milestones of a GitLab project to the commits (who planned, who was assigned, who committed).
  * Can have a language model, local or Claude, write an assessment from the statistics.
  * Runs on Python 2.7 and on Python 3.5 and later; see [docs/REQUIREMENTS.txt](docs/REQUIREMENTS.txt) for the supported versions.

### Contribution focus and code level
`--focus` (`-C`) puts every changed file of every commit in a category by extension and path, so the report says where an author's lines went: scripts, shaders, scenes the editor wrote, docs, data, config, and separately how many asset and generated files they touched. Shares are of authored lines only, so the member who committed the asset pack no longer looks like the lead programmer.

`--code-quality` (`-Q`) reads the script lines git blame gives each author (GDScript, C#, Python, JavaScript and TypeScript, the shader languages, C and C++) and rates them: typed parameters and returns, naming against the language's convention, documented functions, median function length, nesting, branches per function, debug prints, magic numbers, commented-out code, long lines, duplicated lines, safety checks. Four sub-scores (clarity, structure, robustness, hygiene) make one score and a level band (beginning, developing, competent, strong). The same measures are taken per chunk, one author's lines in one file from one commit, which gives the share of each author's code that is good, fair or poor, and flags chunks that are well above that author's usual polish and carry the marks of generated code: full typing, a doc comment on every function, sentence-case explanatory comments, long descriptive names, nothing left over, one large commit. The flag is a heuristic and a prompt for a question, not a verdict. Both are part of `--grading`.

### GitLab issues, milestones and a written assessment
Two additions aimed at grading. `--gitlab` reads the issues and the milestones of the GitLab project behind the origin remote (or `--gitlab-url`, or an offline `--gitlab-dump` of the API objects) and joins them to the commits: who raised the issues, who was assigned, who committed against which issue, which milestones held and which are overdue. A personal access token with the `read_api` scope goes in `--gitlab-token`, `$GITLAB_TOKEN` or the git config `inspector.gitlab-token`. Students who commit from a personal address are matched to their GitLab account by address, name and name tokens; `--gitlab-aliases=FILE` (a JSON object of address or name to username) settles the ones that are not, and the same matching merges the rows of the focus and code quality sections, so a student who committed under four names gets one row.

`--llm=BACKEND` then has a language model write an assessment from the statistics in the report, never from the source. Three backends: `local` for any OpenAI-compatible server on the machine (Ollama, LM Studio, llama.cpp; `--llm-url`, default `http://localhost:11434/v1`), `claude` for the Anthropic API (`pip install anthropic`; `ANTHROPIC_API_KEY` or an `ant auth login` profile), and `claude-code` for the `claude` command line tool on a Claude subscription. `--llm-model` picks the model and `--llm-prompt=FILE` adds the rubric of the course. The assessment lands at the end of every output format, marked as written by a model, so it can be checked against the tables above it.

```
gitinspector --grading --gitlab --llm=local --llm-model=llama3.1 -F html > report.html
gitinspector --grading --gitlab-dump=team1.json --llm=claude-code --llm-prompt=rubric.txt
```

Every option can also be set once in the git config as `inspector.gitlab`, `inspector.gitlab-url`, `inspector.gitlab-token`, `inspector.gitlab-dump`, `inspector.gitlab-aliases`, `inspector.llm`, `inspector.llm-model`, `inspector.llm-url` and `inspector.llm-prompt`.

### Example outputs
Below are some example outputs for a number of famous open source projects, as well as for gitinspector itself. All the statistics were generated using the *"-HTlrm"* flags.

| Project name | | | | |
|---|---|---|---|---|
| Django | [HTML](https://ejwa.github.io/gitinspector/examples/django_output.html) | [HTML Embedded](https://ejwa.github.io/gitinspector/examples/django_output.emb.html) | [Plain Text](https://ejwa.github.io/gitinspector/examples/django_output.txt) | [XML](https://ejwa.github.io/gitinspector/examples/django_output.xml) |
| Gitinspector | [HTML](https://ejwa.github.io/gitinspector/examples/gitinspector_output.html) | [HTML Embedded](https://ejwa.github.io/gitinspector/examples/gitinspector_output.emb.html) | [Plain Text](https://ejwa.github.io/gitinspector/examples/gitinspector_output.txt) | [XML](https://ejwa.github.io/gitinspector/examples/gitinspector_output.xml) |
| JQuery | [HTML](https://ejwa.github.io/gitinspector/examples/jquery_output.html) | [HTML Embedded](https://ejwa.github.io/gitinspector/examples/jquery_output.emb.html) | [Plain Text](https://ejwa.github.io/gitinspector/examples/jquery_output.txt) | [XML](https://ejwa.github.io/gitinspector/examples/jquery_output.xml) |
| Pango | [HTML](https://ejwa.github.io/gitinspector/examples/pango_output.html) | [HTML Embedded](https://ejwa.github.io/gitinspector/examples/pango_output.emb.html) | [Plain Text](https://ejwa.github.io/gitinspector/examples/pango_output.txt) | [XML](https://ejwa.github.io/gitinspector/examples/pango_output.xml) |

### The Team
  * Adam Waldenberg, Lead maintainer and Swedish translation
  * Agustín Cañas, Spanish translation
  * Alexander Chernoskutov, Russian translation
  * Bart van Andel, npm package maintainer
  * Bill Wang, Chinese translation
  * Christian Kastner, Debian package maintainer
  * Georgios Andreadis, Dutch translation
  * Gilmar Pupo, Portuguese translation
  * Kamila Chyla, Polish translation
  * Luca Motta, Italian translation
  * Moses Kim, Korean translation
  * Philipp Nowak, German translation
  * Sergei Lomakov, Russian translation
  * Yannick Moy, French translation

*We need translations for gitinspector!* If you are a gitinspector user, feel willing to help and have good language skills in any unsupported language we urge you to contact us. We also happily accept code patches. Please refer to [Contributing](https://github.com/ejwa/gitinspector/wiki/Contributing) for more information on how to contribute to the project.

### Packages
The Debian packages offered with releases of gitinspector are unofficial and very simple packages generated with [stdeb](https://github.com/astraw/stdeb). Christian Kastner is maintaining the official Debian packages. You can check the current status on the [Debian Package Tracker](https://tracker.debian.org/pkg/gitinspector).  Consequently, there are official packages for many Debian based distributions installable via *apt-get*.

An [npm](https://npmjs.com) package is provided for convenience as well. To install it globally, execute `npm i -g gitinspector`.

### Docker
A *Dockerfile* is included for those who would rather not install gitinspector at all. Build the image from the root of the sources and mount the repository to analyze on */repo*:

```
docker build -t gitinspector .
docker run --rm -v "$PWD:/repo" gitinspector -f py -T
```

### Forks
[GitInspectorGUI](https://gitlab.com/edu-boost/gitinspectorgui) started out as an extension of gitinspector and has since been rewritten from scratch. It offers a graphical interface next to the command line, HTML and Excel output with blame information per file, and stand-alone apps for Windows and macOS. Its documentation lives at [edu-boost.gitlab.io/gitinspectorgui](https://edu-boost.gitlab.io/gitinspectorgui).

### License
gitinspector is licensed under the *GNU GPL v3*. The gitinspector logo is partly based on the git logo; based on the work of Jason Long. The logo is licensed under the *Creative Commons Attribution 3.0 Unported License*.
