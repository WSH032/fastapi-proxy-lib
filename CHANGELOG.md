<!-- The content will be also use in `docs/CHANGELOG/CHANGELOG.md` by `pymdownx.snippets` -->
<!-- Do not use any **relative link** and  **GitHub-specific syntax** ！-->
<!-- Do not rename or move the file -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)(**After we publish 1.0.0**).

- `Added` for new features.
- `Changed` for changes in existing functionality.
- `Deprecated` for soon-to-be removed features.
- `Removed` for now removed features.
- `Fixed` for any bug fixes.
- `Security` in case of vulnerabilities.
- `[YANKED]` for deprecated releases.

<!-- Refer to: https://github.com/olivierlacan/keep-a-changelog/blob/main/CHANGELOG.md -->
<!-- Refer to: https://github.com/gradio-app/gradio/blob/main/CHANGELOG.md -->

## [Unreleased]

### Security

- [#10](https://github.com/WSH032/fastapi-proxy-lib/pull/10) - fix security vulnerabilities of cookies leakage between different users. Thanks [@WSH032](https://github.com/WSH032)!

### Removed

- [#10](https://github.com/WSH032/fastapi-proxy-lib/pull/10) - Remove support for setting cookies at the `AsyncClient` level. Thanks [@WSH032](https://github.com/WSH032)!

## [0.0.1b0] - 2023-11-27 [YANKED]

!!! danger
    **This version has security vulnerabilities, please stop using it.**

[unreleased]: https://github.com/WSH032/fastapi-proxy-lib/tree/HEAD
[0.0.1b0]: https://github.com/WSH032/fastapi-proxy-lib/releases/tag/v0.0.1b0
