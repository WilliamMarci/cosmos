# Cosmos

[English](README.md) · [简体中文](README.zh-CN.md)

Cosmos 是面向本机和 SSH 服务器的终端工作空间。你可以重连持续会话、在多个窗格中工作、阅读文档并使用 AI Agent，连接端无需安装配套客户端。

## 功能

- 持续会话、窗口与分屏，支持历史回滚和搜索。
- 内置 Reader，支持图片、PDF、EPUB、Markdown 和 HTML；也可用 `cosmos open FILE` 独立阅读。
- 可选 AI Agent，提供终端观察与交互工具；另有 Bash 命令助手。
- 可选 Rime＋雾凇输入法，以及主题、通知和扩展功能。

项目仍在开发中，当前版本范围见[发布说明](RELEASE.md)。

## 安装

从 [Releases](https://github.com/WilliamMarci/cosmos/releases) 下载 **core 二进制包**，解压后运行：

```bash
./install.sh
```

安装界面可修改软件安装位置，并选择 Agent、PDF、Rime 等组件。默认用户态安装，包内包含 Python 和原生运行依赖，无需编译器或安装系统软件包。

目前提供 **Linux x86_64 / x86-64-v2** 的 **glibc ≥ 2.28** 和 **≥ 2.34** 兼容档。请下载 core 二进制包，勿使用 GitHub 自动生成的源码压缩包。离线安装、自定义路径和兼容要求见[安装文档](docs/installation.md)。

```bash
cosmos                    # 打开或重连主工作空间
cosmos attach work        # 打开指定会话
cosmos open document.pdf  # 在 Cosmos 外直接打开 Reader
cosmos update             # 更新 release 安装
```

## 文档

- [命令与会话](docs/cli.md) · [设置](docs/settings.md) · [Shell 集成](docs/shell.md)
- [Reader](docs/viewer.md) · [Agent](docs/agent.md) · [输入法](docs/input-method.md)
- [主题](docs/themes.md) · [通知](docs/notifications.md) · [扩展](docs/ui-mods.md)
- [开发](docs/development.md) · [架构](docs/architecture.md) · [RPC](docs/framework.md)

## 上游项目与参考

Cosmos 使用 [Tmux](https://github.com/tmux/tmux)、[Textual](https://github.com/Textualize/textual)、[OpenCode](https://github.com/anomalyco/opencode)、[librime](https://github.com/rime/librime)、[雾凇](https://github.com/iDvel/rime-ice) 和 [Poppler](https://poppler.freedesktop.org/)。其他设计参考与固定源码版本见[上游说明](vendor/README.md)和[来源清单](vendor/sources.json)。

Cosmos 采用 [MIT 许可证](LICENSE)。打包的第三方组件保留各自许可证；相关声明及适用的源码包随 release 提供。
