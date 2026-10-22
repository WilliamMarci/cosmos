# Cosmos Shell 入口

新建 Bash 窗格使用 `bash --rcfile shell/cosmos.bash -i`。按顺序加载 HOME 下的 `.bashrc`，然后加载项目 `config/cosmosrc`；环境变量 COSMOS_RC 可指定其他 rc 文件。路径按脚本位置解析，与启动目录无关。

已有会话重连不会重启 Bash，也不会自动重新 source。需要加载改动时，在该窗格回到 Bash 后执行：

```bash
source /home/amadeus/Program/cosmos/config/cosmosrc
```

cosmosrc 导出项目解释器/二进制路径、命令生成 prompt 路径，加载原 terminal_agent Bash 适配器，并定义 Shell 函数 open。不会修改用户的 ~/.bashrc。

## open

`open FILE...` 按参数逐项处理。当前可在 Cosmos 中查看的格式为 PNG/JPG/JPEG/WebP/PDF，大小写扩展名均识别；文件必须存在且运行于 Tmux pane，随后由 `cosmos open` 验证属于 Cosmos 服务。服务器上的其他 Tmux 不作为可绕过该检查的许可。

其他格式、目录和 URL 调用服务器上已有的 `xdg-open`。这是远程主机的应用入口，不会越过 SSH 去打开连接电脑上的程序。外部应用不可用会返回错误，不自动安装。参数通过 argv 传递，空格与前导横线文件名不作为 Shell 代码解释。多个受支持文件会依次在当前 pane 打开，最终显示最后一个，不会自动创建多个窗口。

## 命令生成 prompt

`config/terminal-agent-prompt.md` 是给后端的 Linux Bash command generation 说明，包含输出 JSON、上下文、文件名与不执行命令的约束。COSMOS_AGENT_PROMPT 可指定替代文件。

Cosmos 桥接请求将该文件路径作为 prompt_file 配置传给现有 OpenCode 后端，并在原上下文提示之前附加文件内容。仍保留原模型/权限/历史行为；模型输出只更新 Readline 缓冲区，运行需要用户显式操作。独立 terminal_agent 不会因 Cosmos UI 样式变动改变界面；只有显式配置 prompt_file 时才使用附加文件。
