# 安装、更新与自检

官方仓库：[KaiwenVide/teacher-wenkai](https://github.com/KaiwenVide/teacher-wenkai)。采用带版本标签的发布包；源码、技能指引与运行入口应来自同一版本。当前版本 v3.2.0。

## 通过 Codex 安装

对 Codex 说：“从 https://github.com/KaiwenVide/teacher-wenkai 安装 v3.2.0，仓库根目录就是 skill；保留并备份已有安装。”

可用内置 skill-installer 时，首次安装命令为：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" --repo KaiwenVide/teacher-wenkai --ref v3.2.0 --path . --name teacher-wenkai
```

没有该安装器时，从 [v3.2.0 发布页](https://github.com/KaiwenVide/teacher-wenkai/releases/tag/v3.2.0) 下载 teacher-wenkai-3.2.0.zip，核对附件 SHA-256，解压后将 teacher-wenkai 文件夹放到 Codex 的 skills 目录。该目录内应直接包含 SKILL.md。旧版本先移到活动 skills 目录之外，保留备份，避免覆盖自定义文件或加载两个同名技能。

安装后运行包内的 scripts/verify_release.py 检查文件完整性；这不是签名验证。技能将在下一轮对话可用。

## 配置运行环境

Python 3.10+，当前实际验证使用 Python 3.12。技能安装提供指引与脚本；科学计算依赖、可选服务认证和定时任务分别配置。

```bash
python3 -m venv ~/.local/share/teacher-wenkai/venv
~/.local/share/teacher-wenkai/venv/bin/python -m pip install -r ~/.codex/skills/teacher-wenkai/requirements.txt
python3 ~/.codex/skills/teacher-wenkai/scripts/verify_release.py
python3 ~/.codex/skills/teacher-wenkai/scripts/run.py doctor
```

自定义 CODEX_HOME 时调整技能目录；TWK_PYTHON 可指定运行环境。脚本不自动安装依赖。doctor 显示版本与可用模块，不证明账号认证或远程数据库可用。

## 更新与回退

先下载指定新版本到独立临时目录，验证 LICENSE、清单及包内自检。将当前安装完整备份到 skills 目录之外，再换入新版本；不要直接覆盖旧目录或把它作为第二份活动技能保留。把修改过的个人配置单独比较后迁移，不用旧副本覆盖新版本的技能入口或许可证。

更新后再次运行完整性检查和 doctor，核对版本号。需要回退时以同样方式保留当前版本，再恢复已有备份；每份历史发布包保留其当时的许可文件。公开 v3.2.0 及其后标明 MIT 的版本按各自附带的 MIT 许可使用。

## 月度任务

本技能提供月度研读命令及执行规范。周期由使用者明确选择，通过应用自动化运行；仅安装技能不会自动建立定时任务。维护者已选择每月 1 日北京时间 09:00，在原对话回顾上一个自然月的 CNS 主刊生命科学文章。其他使用者按自己的时区、输出目录与运行环境设置。
