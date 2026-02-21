# XGuard — Dify 内容安全检测插件

XGuard 是一个 Dify 工具插件，在调用 LLM 之前对用户输入文本进行内容安全风险检测。支持 27 类风险识别，每个类别可独立开启/关闭并设置不同的风险阈值。

## 架构

```
┌──────────────┐     HTTP      ┌─────────────────┐     推理      ┌───────────────────────────┐
│  Dify 插件    │ ──────────▶  │  XGuard Server  │ ──────────▶  │  XGuard-Reason-0.6B       │
│  (工具节点)    │  /api/check  │  (server/app.py)│              │  (本地安全模型)             │
└──────────────┘              └─────────────────┘              └───────────────────────────┘
```

- **插件端**（`tools/content_check.py`）：运行在 Dify 插件容器中，负责调用后端服务、按类别过滤和阈值判定
- **服务端**（`server/app.py`）：独立的 FastAPI 服务，加载 XGuard 安全模型进行推理，返回各类别风险分数

## 快速开始

### 第一步：启动 XGuard 服务

```bash
cd dify-plugin-xguard/server
pip install -r requirements.txt
python app.py
```

默认监听 `0.0.0.0:8001`。可通过环境变量配置（前缀 `XGUARD_`）：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `XGUARD_MODEL_DIR` | `./YuFeng-XGuard-Reason-0.6B` | 模型目录路径 |
| `XGUARD_DEVICE` | `auto` | 推理设备（auto/cuda/cpu） |
| `XGUARD_LISTEN_HOST` | `0.0.0.0` | 监听地址 |
| `XGUARD_LISTEN_PORT` | `8001` | 监听端口 |
| `XGUARD_DEFAULT_RISK_THRESHOLD` | `0.5` | 默认风险阈值 |

验证服务是否正常：

```bash
curl http://localhost:8001/health
# 返回 {"status": "ok"} 表示正常
```

### 第二步：安装插件到 Dify

1. 在 Dify 后台进入「插件管理」页面
2. 点击「安装插件」，上传 `xguard.difypkg` 文件
3. 等待安装完成

> 注意：需要在 Dify 的 `.env` 中设置 `FORCE_VERIFYING_SIGNATURE=false`，否则自签名插件无法安装。

### 第三步：配置插件凭据

安装完成后，在「工具」页面找到 XGuard，点击「去授权」：

| 配置项 | 必填 | 说明 |
|--------|------|------|
| XGuard 服务地址 | 是 | 后端服务的地址。如果 Dify 是 Docker 部署，填 `http://host.docker.internal:8001`；如果是同一台机器，填 `http://localhost:8001` |
| 默认风险阈值 | 否 | 全局默认阈值（0.0–1.0），不填则为 0.5 |

保存时插件会自动调用 `/health` 接口验证连通性。

### 第四步：在 Workflow 中使用

#### 基本用法：输入拦截

最常见的场景是在 LLM 节点之前做输入安全检测：

```
开始 → 内容安全检测 → IF/ELSE → LLM（安全时） / 直接回复（不安全时）
```

具体步骤：

1. 在 Workflow 编辑器中，添加一个「工具」节点
2. 选择 **XGuard → 内容安全检测**
3. 将用户输入变量绑定到 `text` 参数
4. 在工具节点后添加 **IF/ELSE** 条件节点：
   - 条件：`{{内容安全检测.is_safe}}` 等于 `true`
   - IF 分支（安全）：连接到 LLM 节点，正常处理
   - ELSE 分支（不安全）：连接到「直接回复」节点，返回拦截提示

#### 拦截提示示例

<img width="1397" height="623" alt="image" src="https://github.com/user-attachments/assets/a4f02603-9e18-4508-89c4-e8b6d657eebb" />
<img width="374" height="625" alt="image" src="https://github.com/user-attachments/assets/cd5d5c94-f436-489d-9177-3dc5502cdebc" />

#### 按类别配置

在工具节点的参数面板中，每个风险类别都有两个配置项：

- **开关**（如「危险武器 (dw)」）：`true` 启用拦截，`false` 关闭该类别
- **阈值**（如「危险武器阈值」）：该类别的独立阈值，留空则使用默认阈值

例如，如果你只想拦截暴力和色情内容，可以：
- 将「默认阈值」设为 `0.5`
- 关闭不需要的类别（设为 `false`）
- 对重点类别设置更低的阈值（如 `0.3`），提高敏感度

## 服务端 API

### `GET /health`

健康检查，返回 `{"status": "ok"}`。

### `POST /api/check`

请求：
```json
{
  "text": "待检测的文本内容",
  "threshold": 0.5
}
```

响应：
```json
{
  "safe": true,
  "label": null,
  "score": 0.0,
  "scores": {"sec": 0.99, "dw": 0.001, "pc": 0.002}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `safe` | boolean | 模型判定是否安全 |
| `label` | string/null | 最高风险类别代码，安全时为 null |
| `score` | number | 最高风险分数 |
| `scores` | object | 各类别的概率分数 |

## 插件输出变量

插件会对服务端返回的原始分数进行二次处理（按类别开关和独立阈值过滤），输出以下变量：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `is_safe` | boolean | 是否通过所有已启用类别的检测。`true` = 安全，`false` = 被拦截 |
| `risk_category` | string | 最高风险类别代码（如 `dw`、`ter`），安全时为空 |
| `risk_category_name` | string | 最高风险类别中文名（如「危险武器」），安全时为空 |
| `risk_score` | number | 最高风险分数（0.0–1.0） |
| `risk_details` | object | 模型返回的全部类别分数 |
| `blocked_categories` | array | 所有被拦截的类别列表，每项包含 `code`、`name`、`score`、`threshold` |

### 输出示例

安全文本（如「今天天气怎么样」）：
```json
{
  "is_safe": true,
  "risk_category": "",
  "risk_category_name": "",
  "risk_score": 0.002,
  "risk_details": {"sec": 0.994, "dw": 0.001, "pc": 0.002},
  "blocked_categories": []
}
```

不安全文本：
```json
{
  "is_safe": false,
  "risk_category": "dw",
  "risk_category_name": "危险武器",
  "risk_score": 0.85,
  "risk_details": {"sec": 0.05, "dw": 0.85, "ter": 0.06},
  "blocked_categories": [
    {"code": "dw", "name": "危险武器", "score": 0.85, "threshold": 0.5}
  ]
}
```

## 27 类风险类别

| 代码 | 名称 | 代码 | 名称 |
|------|------|------|------|
| pc | 色情违禁 | dc | 毒品犯罪 |
| dw | 危险武器 | pi | 财产侵犯 |
| ec | 经济犯罪 | ac | 辱骂谩骂 |
| def | 诽谤中伤 | ti | 威胁恐吓 |
| cy | 网络欺凌 | ph | 身体健康 |
| mh | 心理健康 | se | 社会伦理 |
| sci | 科学伦理 | pp | 个人隐私 |
| cs | 商业机密 | acc | 访问控制 |
| mc | 恶意代码 | ha | 黑客攻击 |
| ps | 物理安全 | ter | 暴力恐怖活动 |
| sd | 社会扰乱 | ext | 极端主义思潮 |
| fin | 金融建议 | med | 医疗建议 |
| law | 法律建议 | cm | 未成年人不良引导 |
| ma | 未成年人虐待与剥削 | md | 未成年人犯罪 |

## 隐私说明

所有数据仅发送到您自托管的 XGuard 服务，不涉及任何第三方服务。插件和服务端均不存储任何请求数据。

## 许可证

MIT
