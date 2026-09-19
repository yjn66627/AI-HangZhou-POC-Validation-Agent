# AI POC验证与技术决策智能体

面向企业技术选型的 POC 验证与技术决策智能体：把自然语言需求整理成可验证实验，再用实验结果和证据支持技术决策。

## 项目流程

企业需求 → 候选方案 → POC实验 → 效果评估 → 技术决策

## 在线展示

- 演示主页：[https://just-wxtx.upma.site/](https://just-wxtx.upma.site/)
- 腾讯元器体验：[打开体验](https://yuanqi.tencent.com/webim/#/chat/rPLdMX?appid=2097996104859300096&experience=true&space_id=spm0Lq34zNykEjAFYKI2s3c9MAyrJHkC)

## 当前验证事实

- 腾讯元器真实 Tool 请求 PASS
- 公网调用 HTTP 200
- Recovery Bridge SUCCESS
- Backend HTTP 200
- Experiment Run COMPLETED
- Result 非空

固定技术口径：

> 真实腾讯元器公网 Tool 调用 + 真实系统链路 + 受控实验 Fixture 数据

## 本地运行

### 后端

需要 Python 3.12 或更高版本：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Windows PowerShell 激活虚拟环境时使用：

```powershell
.\.venv\Scripts\Activate.ps1
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

浏览器打开 `http://127.0.0.1:5173/`。

### 演示主页

```bash
python -m http.server 8080 --directory demo-site
```

浏览器打开 `http://127.0.0.1:8080/`。

## 目录说明

| 目录 | 内容 |
| --- | --- |
| `backend/` | Backend API 与收案服务 |
| 执行层组件 | Executor 运行组件 |
| `experiment/` | 实验执行、评估与决策引擎 |
| `contracts/` | 请求、结果与决策契约 |
| `frontend/` | 团队最新前端控制台 |
| `demo_cases/` | 可公开演示案例 |
| `datasets/` | 公开测试输入 |
| `demo-site/` | 比赛演示主页 |
| `adapters/` | 外部系统映射模板 |

## 安全说明

仓库只包含源码、公开文档、示例数据和演示资源。真实密钥、访问令牌、Cookie、私有评测数据和本机配置不应提交到仓库。
