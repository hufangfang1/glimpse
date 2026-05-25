# Glimpse

> 一瞥即见的 HTTP/HTTPS 抓包调试工具

用 Python + PyQt6 实现的 macOS HTTP/HTTPS 抓包调试工具，灵感来自 Proxyman / Charles。

---

## 功能

- HTTP / HTTPS 流量拦截（基于 mitmproxy MITM 中间人）
- HTTPS 自动解密
- 请求 / 响应头和 Body 查看，JSON 语法高亮 + 折叠树
- Body 内 ⌘F 全文搜索（支持上下导航 + 匹配计数）
- 列表关键词过滤 + 列排序（按状态码/耗时/大小/时间）
- 请求重放（⇧⌘R）、Copy as cURL（⌥⌘C）、Copy URL（⇧⌘C）
- **抓取作用域 (Capture Scope)**：白名单 / 黑名单 host 模式，支持 `*.example.com` 通配
  - 接入 mitmproxy 的 `allow_hosts` / `ignore_hosts`，白名单外的 HTTPS 直接透传，不解 TLS
  - 解决飞书、银行等做了 SSL Pinning 的 App "网络不可用"问题
  - 右键流量可一键加入白/黑名单
- WebSocket 消息查看（实时刷新）
- iOS / Android 移动端抓包（监听 `0.0.0.0`，状态栏显示 LAN IP）
- 一键安装 CA 证书到 macOS 系统钥匙串（osascript 申请管理员权限）

---

## 安装

先进入项目根目录（包含 `main.py`、`requirements.txt` 的 `glimpse/` 文件夹）：

```bash
cd glimpse   # 若 clone 时用了其他目录名，请改成实际路径
```

然后执行：

```bash
# 建议使用虚拟环境
python3 -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
```

---

## 运行

### 方式一：macOS 应用（推荐）

**首次**（安装依赖 + 生成 `.app`）——在项目根目录下执行：

```bash
cd glimpse   # 若已在项目根目录可省略
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash scripts/build_app.sh
```

**日常启动**：双击项目里的 **`Glimpse.app`** 即可。

**固定到「应用程序」或启动台**（不要用 Finder 把 `.app` 拖进去复制）——在项目根目录下执行：

```bash
cd glimpse   # 若已在项目根目录可省略
bash scripts/install_app.sh
```

这会在「应用程序」里创建一个**快捷方式**，指向项目内的 `Glimpse.app`。

> **不要**把 `Glimpse.app` **复制**到「应用程序」——复制后往往打不开。  
> 若已经复制过，先删 `/Applications/Glimpse.app`，再运行 `install_app.sh`。  
> 首次打开若被 macOS 拦截：「系统设置 → 隐私与安全性 → 仍要打开」。

### 方式二：命令行

在项目根目录下执行：

```bash
cd glimpse   # 若已在项目根目录可省略
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

### 配置抓取范围（Capture Scope）

工具栏点 **🎯 Scope** 或按 `⌘L`：

- **Allow**（白名单）：留空 = 抓所有；填了之后**只**对匹配的 host 做 MITM，其他全部透传
- **Block**（黑名单）：匹配的 host 直接透传（用来屏蔽噪音流量）
- 支持通配：`api.example.com`、`*.example.com`、`*.googleapis.com`
- 想同时覆盖根域名和子域名，请加两行：`example.com` 和 `*.example.com`

配置存于 `~/.glimpse/scope.json`，重启自动加载。

---

## 项目结构

```
glimpse/
├── main.py                       # 入口
├── Glimpse.app                   # 运行 build_app.sh 后生成，双击启动
├── scripts/build_app.sh          # 打包 macOS 应用
├── assets/AppIcon.png            # 应用图标
├── requirements.txt
├── proxy/
│   ├── models.py                 # FlowModel 数据模型
│   ├── addon.py                  # mitmproxy Addon（捕获流量）
│   ├── scope.py                  # 白/黑名单 host 模式
│   └── server.py                 # 代理服务器管理
└── gui/
    ├── themes.py                 # 暗色主题
    ├── main_window.py            # 主窗口
    └── widgets/
        ├── traffic_table.py      # 流量列表
        ├── detail_panel.py       # 请求/响应详情面板
        └── scope_dialog.py       # 抓取作用域对话框
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
- Scope 改动只对**新建连接**生效，飞书等长连接 App 修改后需要重连
- 仅用于合法的调试和开发，请勿用于未授权的网络监控
