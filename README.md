# Proxyman

用 Python + PyQt6 实现的 macOS HTTP/HTTPS 抓包调试工具，功能类似 Proxyman。

---

## 功能

- HTTP / HTTPS 流量拦截（基于 mitmproxy MITM 中间人）
- HTTPS 自动解密
- 请求 / 响应头和 Body 查看（JSON 语法高亮）
- 关键词过滤流量
- 请求重放（Replay）
- WebSocket 消息查看（实时刷新）
- iOS / Android 移动端抓包（监听 `0.0.0.0`，状态栏显示 LAN IP）
- 一键安装 CA 证书到 macOS 系统钥匙串（osascript 申请管理员权限）

---

## 安装

```bash
# 建议使用虚拟环境
python3 -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
```

---

## 运行

### 方式一：macOS 应用（推荐）

**首次**（安装依赖 + 生成 `.app`）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash scripts/build_app.sh
```

**日常启动**：双击项目里的 **`Proxyman.app`** 即可。

**固定到「应用程序」或启动台**（不要用 Finder 把 `.app` 拖进去复制）：

```bash
bash scripts/install_app.sh
```

这会在「应用程序」里创建一个**快捷方式**，指向项目内的 `Proxyman.app`。

> **不要**把 `Proxyman.app` **复制**到「应用程序」——复制后往往打不开。  
> 若已经复制过，先删 `/Applications/Proxyman.app`，再运行 `install_app.sh`。  
> 首次打开若被 macOS 拦截：「系统设置 → 隐私与安全性 → 仍要打开」。

### 方式二：命令行

```bash
source .venv/bin/activate   # 若尚未激活虚拟环境
python main.py
```

---

## 使用步骤

### 桌面浏览器抓包

1. 点击 **▶ Start** 启动代理（默认端口 9090）
2. 在浏览器或系统网络设置中配置 HTTP 代理：
   - 主机：`127.0.0.1`，端口：`9090`
3. 访问任意网站，流量即出现在列表中
4. 点击 **🔐 Install Cert** 安装 CA 证书（系统会弹出管理员密码对话框），之后 HTTPS 流量也可解密

### iOS / Android 移动设备抓包

1. 确保手机和电脑在**同一 Wi-Fi** 下
2. 启动代理后，查看状态栏中的 **LAN IP**（如 `192.168.1.100:9090`）
   - 在手机 Wi-Fi 详情页设置 HTTP 代理为该地址
3. 在手机浏览器访问 `http://mitm.it`，下载并安装 mitmproxy 证书
   - iOS 还需在「设置 → 通用 → 关于本机 → 证书信任设置」中启用该证书

---

## 项目结构

```
proxyman/
├── main.py                    # 入口
├── Proxyman.app               # 运行 build_app.sh 后生成，双击启动
├── scripts/build_app.sh       # 打包 macOS 应用
├── assets/AppIcon.png         # 应用图标
├── requirements.txt
├── proxy/
│   ├── models.py              # FlowModel 数据模型
│   ├── addon.py               # mitmproxy Addon（捕获流量）
│   └── server.py              # 代理服务器管理
└── gui/
    ├── themes.py              # 暗色主题
    ├── main_window.py         # 主窗口
    └── widgets/
        ├── traffic_table.py   # 流量列表
        └── detail_panel.py    # 请求/响应详情面板
```

---

## 技术栈

| 组件 | 库 |
|------|-----|
| MITM 代理引擎 | [mitmproxy](https://mitmproxy.org/) |
| GUI 框架 | [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) |
| 请求重放 | [httpx](https://www.python-httpx.org/) |

---

## 注意事项

- mitmproxy 首次启动时会在 `~/.mitmproxy/` 目录生成 CA 证书
- 安装证书会通过 `osascript` 申请管理员权限，不会储存密码
- 流量列表最多保留 2000 条，超出后自动丢弃最旧记录
- 仅用于合法的调试和开发，请勿用于未授权的网络监控
