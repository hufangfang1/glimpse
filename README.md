# Glimpse

> 一瞥即见的 HTTP/HTTPS 抓包调试工具

用 Python + PyQt6 实现的 macOS HTTP/HTTPS 抓包调试工具，灵感来自 Proxyman / Charles。

![Glimpse 主界面](assets/screenshot.png)

---

## 功能

### 抓包与解密
- HTTP / HTTPS 流量拦截（基于 mitmproxy MITM 中间人）
- HTTPS 自动解密；一键安装 CA 证书到 macOS 系统钥匙串（osascript 申请管理员权限）
- iOS / Android 移动端抓包（监听 `0.0.0.0`，状态栏显示 LAN IP）
- WebSocket：右侧显示消息流（只读，不可发送）
- **抓取作用域 (Capture Scope)**：白名单 / 黑名单 host 模式，支持 `*.example.com` 通配
  - 接入 mitmproxy 的 `allow_hosts` / `ignore_hosts`，白名单外的 HTTPS 直接透传，不解 TLS
  - 解决飞书、银行等做了 SSL Pinning 的 App "网络不可用"问题
  - 右键流量可一键加入白/黑名单（自动推荐精确域名与 `*.parent.com` 通配）
- 代理意外退出（睡眠 / 网络重置）后自动重启，无需手动恢复

### 拦截编辑 (Breakpoints)
- 命中规则的请求会**暂停**在代理里，等待用户在 Intercept 面板修改后再放行
- 支持在 **请求侧**（发出前）、**响应侧**（送达前）或两端同时断点
- fnmatch URL 模式（同时匹配 host + path）：`*.example.com/api/*`、`*/login`、纯子串
- Release / Release Unchanged / Abort / Release All；超时 120s 自动放行
- 工具栏 **Break: On / Off** 一键开关，`⌘B` 打开规则编辑器；配置存于 `~/.glimpse/breakpoints.json`

### Mock / 改写规则
- 三种规则：
  - **`mock`** — 直接返回构造好的响应（含 JSON / 字符串 body；也可通过 `file:` 字段做本地映射）
  - **`request_rewrite`** — 修改请求 URL / Header / Body（支持文本 find / replace）
  - **`response_rewrite`** — 修改响应状态码 / Header / Body
- 自动为 mock 响应补 CORS 头，浏览器跨域 mock 也能直接返回
- JSON 编辑器，内置「Examples」按钮和格式化；`⌘M` 打开；配置存于 `~/.glimpse/rules.json`

### 主界面工作区
- **Dock 拖拽布局**：Traffic / Inspector / Intercept 三个区域都是独立 QDockWidget，可拖到第二屏、Tab 堆叠、关闭、自由缩放
- **三种 Layout 预设**（View → Layout）：
  - **Monitor** — 仅流量列表，专心抓包
  - **Inspect** — 流量 + 编辑器并排（默认工作台）
  - **Compose** — 隐藏流量列表，专心写一个新请求
- **独立 Flow Inspector 窗口**：双击列表行或右键「在新窗口打开」，把单条流量弹成独立顶层窗口，便于对比 / 第二屏对照
- 当前 Dock 排布持久化到 `~/.glimpse/settings.json`，下次启动恢复

### 流量列表（左侧）
- 列表关键词过滤 + 列排序（按状态码 / 耗时 / 大小 / 时间）
- **结构化过滤查询**（与普通子串混用，按空格 AND）：
  - `status:500` · `status:5xx` · `status:>=400`
  - `host:u.api.*` · `path:/login*` · `method:POST`
  - `slow:>500ms` · `slow:<200ms`
  - `is:flagged` / `is:tagged` / `is:noted`
- **快捷过滤预设**：Filter 框右侧 ▾ 一键 Errors / Slow / POST / Clear
- **按 Host 分组树视图**（View → Group by host 或 `⌘G`），可折叠
- **紧凑行高**（View → Compact rows）便于浏览大量流量
- **列选择器**：右键表头显示 / 隐藏列；拖拽表头重新排序；可一键 Reset
- **行注解**（右键菜单，仅当前会话）：
  - **★ Flag**（标星）/ 🎨 颜色标签（红 / 黄 / 绿 / 蓝行背景）/ 📝 行内备注（鼠标悬停查看）
- **静音 Host**：右键 🔇 隐藏指定域名所有流量，状态栏显示已静音条数，一键解除全部
- 请求重放（`⇧⌘R`）、Copy as cURL（`⌥⌘C`）、Copy URL（`⇧⌘C`）；右键还可复制 Host / Path / Body

### 请求编辑器（右侧 Inspector）
- 类 Postman 的请求构造与发送（主窗口右侧）
- **点击流量行**自动载入；工具栏 **📝 新建请求** 清空为空白草稿
- Method / URL、Params / Headers / Cookies / Body 可编辑表格，一键发送并查看响应
- **Body Form / JSON 双模式**：表格化编辑 form-urlencoded 或写原始 JSON，JSON 模式一键格式化
- **请求/响应分屏可翻转**：编辑器右上角按钮在「上下堆叠」与「左右并排」之间切换
- 响应区 JSON 自动高亮，二进制 / 图片智能识别
- **请求集（Collections）抽屉**：编辑区右缘可展开（默认收起，`Ctrl+B` 切换），分组管理已保存请求
- 数据持久化至 `~/.glimpse/collections.json`（含每条已保存请求的**最后一次发送响应**）

### Cookie 同步（编辑器 Cookies 页）
- **从抓包流量提取**（推荐）：使用代理捕获时浏览器实际发出的 Cookie，与线上行为一致
- **从 Chrome 读取**：读取本机 Chrome / Edge Cookie 库（需钥匙串授权「Chrome Safe Storage」）
- **从 Safari 读取**：解析 `Cookies.binarycookies`
- Chrome 127+ 的会话 Cookie（如 `PHPSESSID`）采用应用绑定加密，离线读取常失败；鉴权接口建议走代理抓包后使用「从抓包流量提取」

### 请求签名
- 编辑器 URL 栏旁 **鉴权下拉**可选 `~/.glimpse/auth.json` 里配置的签名方案
- **每次发送**自动刷新 `nonce` / `signTime` 并写入 Header + Body（与 PHP `buildSign` 一致）
- 内置 `chenla_uc` / `rsa_pkcs1_sha1` 类型；通过 JSON 新增 `id` 即可扩展，无需改代码

---

## 安装

> 环境要求：macOS 11+ 、Python 3.9+

```bash
# 1. 克隆项目
git clone git@github.com:hufangfang1/glimpse.git
cd glimpse

# 2. 创建并激活虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
python -m pip install -r requirements.txt
```

之后无论用应用还是命令行运行，都不必再重复以上步骤。

---

## 运行

### 方式一：macOS 应用（推荐）

**首次**——完成上面的「安装」后，在项目根目录生成 `.app`：

```bash
bash scripts/build_app.sh
```

**日常启动**：双击项目里的 **`Glimpse.app`** 即可。

**固定到「应用程序」或启动台**（不要用 Finder 把 `.app` 拖进去复制）——在项目根目录下执行：

```bash
bash scripts/install_app.sh
```

这会在「应用程序」里创建一个**快捷方式**，指向项目内的 `Glimpse.app`。

> **不要**把 `Glimpse.app` **复制**到「应用程序」——复制后往往打不开。
> 若已经复制过，先删 `/Applications/Glimpse.app`，再运行 `install_app.sh`。
> 首次打开若被 macOS 拦截：「系统设置 → 隐私与安全性 → 仍要打开」。

### 方式二：命令行

在项目根目录下执行：

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

### 配置抓取范围（Capture Scope）

工具栏点 **🎯 Scope** 或按 `⌘L`：

- **Allow**（白名单）：留空 = 抓所有；填了之后**只**对匹配的 host 做 MITM，其他全部透传
- **Block**（黑名单）：匹配的 host 直接透传（用来屏蔽噪音流量）
- 支持通配：`api.example.com`、`*.example.com`、`*.googleapis.com`
- 想同时覆盖根域名和子域名，请加两行：`example.com` 和 `*.example.com`
- 也可在流量列表右键直接「✅ Add to allow」/「🚫 Add to block」（自动推荐精确 + 通配两条）

配置存于 `~/.glimpse/scope.json`，重启自动加载。

### 拦截编辑请求 / 响应（Breakpoints）

1. 工具栏点 **Break: Off** 或按 `⌘B` 打开断点规则编辑器
2. 写一行或多行 URL 模式，例如：
   - `*/api/login` — 拦截所有 login 接口
   - `*.example.com/orders/*` — 拦截目标域下的订单接口
3. 勾选 **Enable**、**Break on request** / **Break on response**，保存
4. 命中规则的请求会自动暂停，**Intercept** 面板（默认浮出在底部）会列出被卡住的流量
5. 选中一条 → 修改 method / URL / headers / body（或响应的 status / headers / body）→ 点击：
   - **Release** — 用当前编辑值放行
   - **Release Unchanged** — 不改动直接放行
   - **Abort** — 直接断开连接
   - **Release All** — 一次性放掉所有暂停中的流量
6. 默认超时 120s 自动放行，不会因为忘了点按钮而把客户端挂死
7. 工具栏的 **Break: On / Off** 用来快速总开关；规则本身保存在 `~/.glimpse/breakpoints.json`

### Mock / 改写规则

工具栏 **Rules** 菜单或 `⌘M` 打开规则编辑器（JSON 直编 + Examples 按钮）。最小示例：

```json
[
  {
    "enabled": true,
    "name": "Mock health",
    "kind": "mock",
    "match": "*/api/health",
    "status": 200,
    "headers": {"content-type": "application/json"},
    "body": {"ok": true}
  },
  {
    "enabled": false,
    "name": "Map to local file",
    "kind": "mock",
    "match": "*/api/config",
    "status": 200,
    "headers": {"content-type": "application/json"},
    "file": "~/Desktop/config.json"
  },
  {
    "enabled": false,
    "name": "Inject debug header",
    "kind": "request_rewrite",
    "match": "*/api/*",
    "set_headers": {"x-debug": "glimpse"},
    "remove_headers": ["x-remove-me"]
  },
  {
    "enabled": false,
    "name": "Flip beta flag in response",
    "kind": "response_rewrite",
    "match": "*/api/*",
    "body_find": "\"beta\": false",
    "body_replace": "\"beta\": true"
  }
]
```

字段说明：
- `kind`：`mock` / `request_rewrite` / `response_rewrite`
- `match`：fnmatch URL 模式；不含通配符时按子串匹配
- `mock` 可用 `status` / `headers` / `body`（字符串、对象或数组都行），或 `file` 做本地映射
- `request_rewrite` / `response_rewrite` 可用 `set_headers` / `remove_headers`、`body_find` + `body_replace`，或直接 `body` 整体替换
- `enabled: false` 暂时停用一条规则；保存在 `~/.glimpse/rules.json`

### 请求编辑与 Cookie 同步

1. 在左侧**点击一条流量**，右侧自动载入该请求与抓包响应；或点工具栏 **📝 新建请求** 从空白开始
2. 右侧填写 Method、URL；Body 可在 **Form / JSON** 双模式间切换，JSON 模式可一键格式化
3. 点击 **发送** 查看下方响应区（状态行、Body、Headers）；右上角按钮可在「上下堆叠 / 左右并排」之间切换布局
4. 需要登录态时，在 **Cookies** 页点击 **同步 Cookie**：
   - **从抓包流量提取**：先 **▶ Start** 代理，浏览器走 `127.0.0.1:9090` 并访问目标站，再同步（最可靠）
   - **从 Chrome 读取**：首次会弹出 macOS 钥匙串授权，请选择「允许」或「始终允许」；同一次运行内会缓存密钥
   - 若在地址栏直接打开的 GET 接口，请保持 Method 为 **GET**（勿误用 POST）
5. 点击 **保存** 更新已匹配请求，或按 URL 域名自动分组新建；**另存为…** 可手动选择分组；配置写入 `~/.glimpse/collections.json`
6. 右缘的窄竖条是「请求集抽屉」入口，`Ctrl+B` 一键展开 / 收起

### 请求签名（UC 等 RSA 鉴权）

编辑器 URL 栏旁 **鉴权** 下拉可选 `~/.glimpse/auth.json` 里配置的签名方案；**每次发送**自动刷新 `nonce` / `signTime` 并写入 Header + Body（与 PHP `buildSign` 一致）。

1. 配置签名（任选其一）：
   - 推荐：`cp auth.example.json ~/.glimpse/auth.json` 并填入 `private_key`
   - 开发：直接编辑项目根目录的 `auth.json` 或 `auth.example.json`
2. `private_key` 为 **PEM 字符串**，换行用 `\n`，不要写真实多行
3. 在鉴权下拉选择对应配置后发送（下拉打开时会重新读取配置）
4. 保存到请求集时会记住 `signer_id`；规则变更时改 JSON 或新增 `id`（如 `chenla_uc_v2`）即可，无需改代码

`type` 支持 `chenla_uc` / `rsa_pkcs1_sha1`（同一实现）；`sign_template`、`platform`、`inject` 等均在 JSON 中配置。

---

## 键盘快捷键

| 操作 | 快捷键 |
|------|--------|
| 启动代理 | `⌘R` |
| 停止代理 | `⌘.` |
| 清空流量列表 | `⌘K` |
| 重放选中请求 | `⇧⌘R` |
| Copy URL | `⇧⌘C` |
| Copy as cURL | `⌥⌘C` |
| 抓取作用域 | `⌘L` |
| 断点规则 | `⌘B` |
| Mock / 改写规则 | `⌘M` |
| 按 Host 分组 | `⌘G` |
| 切换请求集抽屉 | `Ctrl+B` |
| 退出 | `⌘Q` |

---

## 项目结构

```
glimpse/
├── main.py                       # 入口
├── auth.example.json             # 鉴权配置示例（复制到 ~/.glimpse/auth.json）
├── Glimpse.app                   # 运行 build_app.sh 后生成，双击启动
├── requirements.txt
├── assets/
│   ├── AppIcon.png               # 应用图标
│   └── screenshot.png            # README 截图
├── scripts/
│   ├── build_app.sh              # 打包 macOS 应用
│   └── install_app.sh            # 在「应用程序」创建快捷方式
├── proxy/
│   ├── models.py                 # FlowModel 数据模型
│   ├── addon.py                  # mitmproxy Addon（抓包 + 断点 + 规则注入）
│   ├── server.py                 # 代理服务器管理（生命周期 / 崩溃自恢复）
│   ├── scope.py                  # 白/黑名单 host 模式
│   ├── breakpoints.py            # 断点规则（拦截规则 + 持久化）
│   ├── rules.py                  # mock / request_rewrite / response_rewrite 引擎
│   ├── http_client.py            # 重放 / 编辑器发送用的 httpx client 工厂
│   ├── collections.py            # 请求集持久化（分组 + 已保存请求 + 最后响应）
│   ├── cookies.py                # Cookie 来源：抓包 / Chrome / Safari
│   └── signing/                  # 可配置请求签名（auth.json 驱动）
│       ├── store.py              # 读取 ~/.glimpse/auth.json 等配置
│       ├── models.py             # SignerConfig / SignResult
│       ├── registry.py           # 按 type 路由签名实现
│       ├── chenla_uc.py          # UC RSA-SHA1（PHP buildSign 等价）
│       └── apply.py              # 发送前注入 Header + Body
└── gui/
    ├── themes.py                 # 暗色主题与控件尺寸常量
    ├── i18n.py                   # 中英文界面文案
    ├── icons.py                  # 程序绘制的小图标
    ├── layout_presets.py         # 工作区 Dock 预设 + 持久化
    ├── main_window.py            # 主窗口（流量 + 编辑器 + 拦截三个 Dock）
    └── widgets/
        ├── traffic_table.py      # 流量列表 / 分组树 / 结构化过滤 / 标记 / 静音
        ├── request_editor.py     # 嵌入式请求编辑器（发送 / 保存 / 抽屉 / 鉴权）
        ├── detail_panel.py       # Body / Headers / WebSocket 展示（编辑器响应区复用）
        ├── flow_inspector_window.py # 独立 Flow Inspector 顶层窗口
        ├── intercept_panel.py    # 拦截队列 + 请求/响应编辑器
        ├── kv_table.py           # Params / Headers / Cookies 键值表
        ├── breakpoint_dialog.py  # 断点规则编辑对话框
        ├── rule_dialog.py        # mock / 改写规则编辑对话框
        └── scope_dialog.py       # 抓取作用域对话框
```

---

## 用户配置文件

所有配置都在 `~/.glimpse/` 下，方便备份与迁移：

| 文件 | 内容 |
|------|------|
| `scope.json` | 抓取作用域 allow / block |
| `breakpoints.json` | 断点规则 |
| `rules.json` | mock / 改写规则 |
| `collections.json` | 请求集 + 每条已保存请求的最后一次响应 |
| `auth.json` | 请求签名配置（私钥、模板等） |
| `settings.json` | 界面语言 + Dock 排布 / 窗口几何 |

---

## 技术栈

| 组件 | 库 |
|------|-----|
| MITM 代理引擎 | [mitmproxy](https://mitmproxy.org/) |
| GUI 框架 | [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) |
| 请求重放 / 编辑器发送 | [httpx](https://www.python-httpx.org/) |
| Chrome Cookie 解密 | [pycryptodome](https://www.pycryptodome.org/) |

---

## 注意事项

- mitmproxy 首次启动时会在 `~/.mitmproxy/` 目录生成 CA 证书
- 安装证书会通过 `osascript` 申请管理员权限，不会储存密码
- 流量列表最多保留 2000 条，超出后自动丢弃最旧记录
- Scope / 断点 / 规则改动只对**新建连接**生效，飞书等长连接 App 修改后需要重连
- 编辑抓包记录**不会修改**左侧列表中的历史数据；仅「保存」会写入 `collections.json`
- 断点暂停的流量默认 120s 后自动放行，避免忘记处理把客户端挂死
- 行内 Flag / 颜色 / 备注属于**当前会话**的临时注解，不会持久化
- Chrome Cookie 同步依赖本机 `security` 命令读取钥匙串；Chrome 127+ 部分 Cookie 无法离线解密，请优先使用「从抓包流量提取」
- 仅用于合法的调试和开发，请勿用于未授权的网络监控

---

## 许可证

本项目采用 [MIT License](LICENSE) 开源。

GUI 依赖 [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)（GPL v3 或商业授权）。若你**打包分发** macOS 应用，请自行确认是否符合 PyQt6 的许可要求。
