# Hi 感谢对本项目感兴趣

## 代码贡献

> **Note**
>
> 我们最低支持的版本是`python3.8`，你可以随意使用`python3.8`以上的版本。
>
> 但是请注意，您的代码要能通过`py >= 3.8`的所有版本的代码风格检查与测试。

我们推荐使用[虚拟环境](https://docs.python.org/3/library/venv.html#creating-virtual-environments)来进行开发

在激活虚拟环境后，运行[./scripts/init.sh](./scripts/init-dev.sh)来为你初始化:

- [requirements](./requirements-dev.txt)
- [hatch](https://github.com/pypa/hatch)
- [pre-commit](https://pre-commit.com/)
- [mkdocs-material](https://squidfunk.github.io/mkdocs-material/)

## 代码风格

由于本项目主要是python语言，所以我们只强制要求python代码风格。

但是涉及到其他语言（例如 `bash`, `toml` 等）的部分，也请尽力保证样式正确。

> **Note**
> 我们启用了大量而严格的`lint`规则，如果你使用`vscode`，我们推荐你安装[./.vscode/extensions.json](./.vscode/extensions.json)中的插件来帮助你实时检查错误
>
> 如果你打不过检查器，可以使用`# noqa`和`# type: ignore`来跳过检查
>
> 当然，这些规则可能过于严格，你可以发起一个`issue`或者`pull request`来讨论是否需要修改规则

### python代码风格(请查看[./pyproject.toml](./pyproject.toml)了解我们的风格)

- [Ruff](https://github.com/astral-sh/ruff): 代码质量检查
- [Blcak](https://github.com/psf/black): 代码格式规范
- [Pyright](https://github.com/Microsoft/pyright/): 静态类型检查

您需要通过以上检查，`pre-commit` 会确保这点。

你也可以[手动检查](./scripts/lint.sh)和[自动修复](./scripts/format.sh)。

> **Note**
> `Pyright`检查将发生两次
>
> - 在`pre-commit`中，`Pyright`不会检查第三方依赖，并且`python`版本为支持的最低版本
> - 而在`Github Actions`或[手动检查](./scripts/lint.sh)中，`Pyright`将在激活的虚拟环境中检查所有依赖

## 代码测试

测试文件位于[./tests/](./tests/)

我们使用`pytest`来完成测试，测试将在`Github Actions`中进行。

你也可以[手动测试](./scripts/pytest.sh)。
