# pyright: basic

"""Maintain lint tools version consistency between `.pre-commit-config.yaml` and `pyproject.toml`."""


# https://packaging.pypa.io/en/stable/requirements.html
# https://yaml.readthedocs.io/en/latest/example/
# https://tomlkit.readthedocs.io/en/latest/quickstart/
# https://hatch.pypa.io/latest/config/environment/overview/#dependencies


import sys
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Union,
)

import tomlkit  # type: ignore
import tomlkit.items  # type: ignore
from packaging.requirements import Requirement  # type: ignore
from packaging.specifiers import SpecifierSet  # type: ignore
from packaging.version import Version  # type: ignore
from ruamel.yaml import YAML  # type: ignore

yaml = YAML(typ="safe")

pre_commit_config_yaml_path = Path(".pre-commit-config.yaml")
pyproject_toml_path = Path("pyproject.toml")

RepoType = Dict[str, Any]
HookType = Dict[str, Any]

if __name__ == "__main__":
    # NOTE: 这三个键名应该对应
    # pyproject_toml["tool"]["hatch"]["envs"]["default"]["dependencies"] 里的值
    vers_in_pre_commit: Dict[str, Union[None, str]] = {
        "ruff": None,
        "black": None,
        "codespell": None,
    }

    # 找出pre-commit-config.yaml中的版本
    pre_commit_yaml = yaml.load(pre_commit_config_yaml_path)
    repos_lst: List[RepoType] = pre_commit_yaml["repos"]

    for repo in repos_lst:
        hooks_lst: List[HookType] = repo["hooks"]
        hook = hooks_lst[0]  # 特殊标记的只有一个hook
        hook_alias = hook.get("alias")  # 只有特殊标记的才有alias
        if hook_alias is None:
            continue
        if hook_alias in vers_in_pre_commit:
            vers_in_pre_commit[hook_alias] = repo["rev"]

    # 检查是否正确
    new_vers: Dict[str, Version] = {}
    for name, ver in vers_in_pre_commit.items():
        if not isinstance(ver, str):
            sys.exit(f"Error: version of `{name}` not found in pre-commit-config.yaml")
        try:
            new_vers[name] = Version(ver)
        except Exception as e:
            sys.exit(f"{e}: version of `{name}` in pre-commit-config.yaml is invalid")

    # 修改pyproject.toml中的版本
    with open(pyproject_toml_path, "rb") as f:  # NOTE: 用二进制模式打开
        pyproject_toml = tomlkit.load(f)
        requir_lst = pyproject_toml["tool"]["hatch"]["envs"]["default"]["dependencies"]  # type: ignore
        assert isinstance(requir_lst, tomlkit.items.Array)

        for idx, require in enumerate(requir_lst):
            assert isinstance(require, tomlkit.items.String)
            parsed_requir = Requirement(require)
            if parsed_requir.name in new_vers:
                # 更新版本
                parsed_requir.specifier = SpecifierSet(
                    f"=={new_vers.pop(parsed_requir.name)}"
                )
                requir_lst[idx] = str(parsed_requir)

        # 在上一步的pop操作应该把所有的依赖都更新了，如果这里字典不为空，说明发生了错误
        if new_vers:
            sys.exit(
                f"Error: version of `{new_vers.popitem()}` not found in pyproject.toml"
            )

        # 如果没错误，就准备更新
        pyproject_toml["tool"]["hatch"]["envs"]["default"]["dependencies"] = requir_lst  # type: ignore

    with open(pyproject_toml_path, "wb") as f:
        toml_str = tomlkit.dumps(pyproject_toml)
        f.write(toml_str.encode("utf-8"))  # NOTE: 用utf-8二进制写入，否则文本样式会乱
