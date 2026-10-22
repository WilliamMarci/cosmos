# 外观氛围参考

`cosmos-atmosphere.py` 和 `window-atmosphere.py` 为用户提供的 `/tmp/cosmos.py`、`/tmp/sw.py` 原样副本，仅用于色彩、密度和视觉层次参考，不作为功能需求或交互规范。

最高优先级：用户确认的 less is more 原则。默认静默，不常驻快捷键大全；统一组合键触发上下文帮助，只展示相关操作，并突出触发键。demo 中的常驻提示、热度条等未确认元素不随参考一并引入。

btop 参考仅涉及主题角色、选择态和局部重绘的思路，没有复制其 C++ 实现：

- https://github.com/aristocratos/btop/blob/main/src/btop_draw.cpp
- https://github.com/aristocratos/btop/blob/main/src/btop_theme.cpp

Cosmos 的终端、查看器与 Mod 交互以本项目设计为准。
