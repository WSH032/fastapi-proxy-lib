<!-- The content will be also use in `docs/CONTRIBUTING/CONTRIBUTING.md` by `pymdownx.snippets` -->
<!-- Do not use any **relative link** and  **GitHub-specific syntax** ！-->
<!-- Do not rename or move the file -->

# Contributing

> The guide is modified from [mkdocstrings](https://mkdocstrings.github.io/contributing/#contributing)

Contributions are welcome, and they are greatly appreciated! Every little bit helps, and credit will always be given.

## Environment setup

First, `fork` and `clone` the repository, then `cd` to the directory.

We use [`hatch`](https://github.com/pypa/hatch) and [`pre-commit`](https://pre-commit.com/) to manage our project.

You can install them with:

```shell
# https://pypa.github.io/pipx/
python3 -m pip install --user pipx

pipx install hatch
pipx install pre-commit
```

Then, initialize the env with:

```shell
# Init pre-commit
# https://pre-commit.com/#3-install-the-git-hook-scripts
pre-commit install
pre-commit run --all-files

# https://hatch.pypa.io/latest/environment/
hatch shell
```

That's all! Now, you can start to develop.

## Code style

The source code is in `src/`

We use [Ruff](https://github.com/astral-sh/ruff), [Blcak](https://github.com/psf/black), [Pyright](https://github.com/Microsoft/pyright/)
 and [Codespell](https://github.com/codespell-project/codespell) to check our code style and lint.

Please check `pyproject.toml` to know our style.

If you want to format or lint-fix your code, you can use the following command:

```shell
hatch run lint
```

or, with `pre-commit`:

```shell
pre-commit run -a
```

or, dry run:

```shell
hatch run lint-check
```

!!! tip
    If you use `VSCode`, we strongly recommend you to install the extensions in `.vscode/extensions.json`.<br>
    Because our code style rules are quite strict.<br>
    These extensions can help you know where need to be fixed when coding.

## Testing

We use [pytest](https://docs.pytest.org/en/stable/) to test our code.

The test source code is in `tests/`

You can run the testing with:

```shell
hatch run test
```

## Documentation

We use [mkdocs](https://www.mkdocs.org), [mkdocs-material](https://squidfunk.github.io/mkdocs-material), [mkdocstrings](https://mkdocstrings.github.io) to build our documentation.

The documentation source code is in `docs/`, `mkdocs.yml`,
 may be there is also some source code in `scripts/` or somewhere (check `mkdocs.yml` to find that).

Live-reloading docs:

```shell
hatch run docs:mkdocs serve
```

Build docs:

```shell
hatch run docs:docs-build
```

## PR

- PRs should target the `main` branch.
- Keep branches up to date by `rebase` before merging.
- Do not add multiple unrelated things in same PR.
- Do not submit PRs where you just take existing lines and reformat them without changing what they do.
- Do not change other parts of the code that are not yours for formatting reasons.
- Do not use your clone's main branch to make a PR - create a branch and PR that.

### Edit `CHANGELOG.md`

If you have made the corresponding changes, please record them in `CHANGELOG.md`.

### Commit message convention

Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/),
or, `pre-commit` may be reject your commit.

!!! info
    If you don't know how to finish these, it's okay, feel free to initiate a PR, I will help you continue.

## More

There may still be some useful commands in `pyproject.toml`, you can refer to [hatch/environment/scripts](https://hatch.pypa.io/latest/config/environment/overview/#scripts) to use them.

!!! info
    If you find that the commands given in the above examples are incorrect, please open an issue, we greatly appreciate it.

---

## 😢

!!! warning
    The following 👇 content is for the maintainers of this project, may be you don't need to read it.

---

## deploy-docs

please refer to `.github/workflows/docs.yml`

## CI: lint-test

please refer to `.github/workflows/lint-test.yml`

## CI: pre-commit-ci auto-update

Every Monday, `pre-commit-ci` will send a PR for automatic hook version updates, which will trigger a local `ver_sync` hook.

The `ver_sync` hook will maintain lint tools version consistency between `.pre-commit-config.yaml` and `pyproject.toml`.

Please check whether the `ver_sync` works properly, then you can accept the PR.

## Publish and Release 🚀

**^^First, edit `CHANGELOG.md` to record the changes.^^**

Then, please refer to:

- `.github/workflows/publish.yml`
- <https://github.com/frankie567/hatch-regex-commit>
- <https://hatch.pypa.io/latest/version/#updating>

Update version with:

```shell
hatch version {new_version}
```

It will create a commit and tag automatically, then, push the **tag** to GitHub.

After that, the `publish.yml` workflow will build and publish the package to PyPI.

> Don't forget to make a `approve` in environment `pypi` for the workflow.

Finally, edit the `draft release` created by `publish.yml` workflow, and publish the release.

!!! warning
    The creating of tag needs signature verification,<br>
    please refer to <https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification>
