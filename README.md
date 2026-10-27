# AI POC验证与技术决策智能体

《AI杭州·超级智能体赛》参赛作品：将企业技术选型需求整理为 Task、候选方案和实验契约，再用实验结果、证据校验与决策规则支持技术判断。

## 比赛提交版与赛后云端演示

2026 年 9 月 19 日比赛提交版包含前端实验控制台、Backend API、Executor Gateway、Tool Runtime、Schema、Evaluator、Decision Engine 和演示主页。历史演示验证过腾讯元器通过公网 Tool 到本机 Backend 的调用链，使用受控 Fixture 数据；这些历史记录不表示当前可以对任意企业数据执行实时 POC。

赛后 P2 将读取演示迁入 CloudBase：腾讯元器 → CloudBase HTTP Gateway → Python HTTP 云函数 → 冻结 Fixture 响应。这条链路不实时执行 Backend、Evaluator 或任意模型对比。`cloudfunction/` 提供源于该实现的公开复现示例，使用新写且明确标记为 **SYNTHETIC_DEMO_DATA** 的虚构响应，不包含线上冻结响应或云端凭据。

| 范围 | 现有能力 | 边界 |
| --- | --- | --- |
| 前端 | 需求、候选、实验进度、证据与决策展示 | 默认是预置回放，不能把画面当成实时测量 |
| Backend / 实验组件 | 请求校验、执行器抽象、结果规范化、评估、决策与对照编排 | LIVE 模式需显式配置；完整历史测试仍有受限评测 registry 依赖 |
| P2 CloudBase | 经鉴权的零参数读取 Tool 与稳定 JSON envelope | 云端演示使用冻结数据；公开示例是合成数据 |
| 尚未完成 | 任意企业数据接入、任意模型实时对比、通用数据/权限接入及完整商业 SaaS | 不在当前已验证能力范围内 |

## 在线展示

- 演示主页：[https://just-wxtx.upma.site/](https://just-wxtx.upma.site/)
- 腾讯元器体验：[打开体验](https://yuanqi.tencent.com/webim/#/chat/rPLdMX?appid=2097996104859300096&experience=true&space_id=spm0Lq34zNykEjAFYKI2s3c9MAyrJHkC)

以上是项目展示入口；源码测试不会访问这些服务，也不能据此证明一次新的端到端实验成功。

## Contributors / 团队贡献

| 成员 | 角色 | 主要贡献 |
| --- | --- | --- |
| 小杨 | Project Lead / Integration | 后端核心链路、真实系统联调、技术验证、演示主页与本次提交整合 |
| 小刘 | Frontend Development | 前端开发、业务系统界面与前端展示优化 |
| 小林 | Product Materials / Documentation / Coordination | 产品材料、文档与项目对接 |

本栏目用于说明贡献来源，不替代 Git 提交记录，也不改变各文件的公开协作属性。


## 本地运行和测试

Backend 的本地验证基线为 Python 3.12.14。先在独立虚拟环境安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

公开安全 smoke tests 和云函数契约测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_case_registry_public_config.py tests/test_tool_policy_regression.py cloudfunction/tests -q
```

公开测试与完整测试必须分别报告。公开命令显式排除 22 项标记为 requires_restricted_registry 的历史测试，排除数量须报告为 deselected，不是已通过或自动 skip。默认完整运行仍包含这些测试，并在没有获授权评测 registry 时失败；不要恢复私有答案或删除断言来制造通过。详见 [测试边界](docs/TESTING.md)。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -m "not requires_restricted_registry" -q
.\.venv\Scripts\python.exe -m pytest tests cloudfunction/tests --collect-only -q
.\.venv\Scripts\python.exe -m pytest tests cloudfunction/tests -q
```

### Backend

源码读取进程环境变量，不会自动加载根目录 `.env`。只在自己的本地环境设置演示假值：

```powershell
$env:API_KEY = 'local-demo-only'
$env:EXECUTOR_MODE = 'FIXTURE'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

`GET /health` 用于健康检查。运行记录位于进程内，必须保持单 worker（single worker）；重启会丢失记录。完整实验提交还要求匹配的输入与评估契约。`CASE_REGISTRY_PATH` 可指定调用者自己有权使用的数据集路径，默认不挂载额外评测 registry。

本候选还注册了 `POST /api/v1/agent/intake`，复用已有收案服务和同一 `_submit_run` 后台执行链。接口同样需要 Backend 鉴权；闲聊返回文本而不提交，`submit=false` 只预览，正式提交返回 run_id/result_url。默认无模型配置时采用确定性编译及 FIXTURE 执行；本地测试通过不代表该路由已部署到线上，也不代表真实企业实验已执行。

### 前端

前端是 React / Vite 项目，Node.js 18+：

```bash
cd frontend
npm ci --ignore-scripts
npm run build
npm run dev
```

默认访问 `http://127.0.0.1:5173/`，默认数据来自预置演示包。真实密钥不得写进 `VITE_*` 变量，因为它们会进入浏览器构建产物。

### 演示主页

```bash
python -m http.server 8080 --directory demo-site
```

访问 `http://127.0.0.1:8080/`。视频是演示素材，不是测试执行记录。

### CloudBase 独立合成示例

见 [云函数说明](cloudfunction/README.md)、[部署模板与步骤](cloudfunction/deployment/DEPLOYMENT.md) 和 [恢复说明](cloudfunction/deployment/ROLLBACK.md)。部署者需要自己的独立测试环境和新生成的测试凭据；本仓库不包含现有云环境、域名、凭据或路由状态。仅运行本地测试不会部署云资源。

## 目录说明

| 目录 | 内容 |
| --- | --- |
| `backend/` | Backend API、Executor 接口和收案逻辑模块 |
| `executor_gateway/` | Executor Gateway、Tool Runtime 和适配器 |
| `experiment/` | Case Registry、实验执行、评估和决策 |
| `contracts/` | Task、实验、结果与决策 Schema |
| `frontend/` | 团队前端控制台 |
| `cloudfunction/` | 赛后 P2 读取 Tool 的公开合成示例 |
| `examples/`、`tests/`、`tools/` | 公开 sandbox 示例、回归测试和离线测试工具 |
| `demo_cases/`、`datasets/` | 既有公开演示输入 |
| `demo-site/` | 演示主页与视频 |

## 公开范围与已知限制

仓库不应包含真实凭据、真实环境变量文件、私有评测数据或内部交接材料。当前目录清理不能清除 Git 历史中的既有内容。项目以公开展示方式提供，尚未授予覆盖全部项目的通用开源许可证；既有视频保持原文件，本次更新不新增素材使用许可，也不代表已获得其他贡献者统一开源授权。第三方内容仍适用各自的条款。

详见 [发布准备状态](docs/PUBLICATION_READINESS.md) 与 [环境变量说明](docs/ENV.md)。

## 验证结果与权利边界

公开验证基线（Python 3.12.14）：公开 Backend/Runtime 测试 544 PASS / 1 SKIP / 22 deselected；CloudFunction 合成契约测试 12 PASS；Agent intake 回归 29 PASS（属于公开测试子集）；前端 build 通过。完整测试的已知结果为 **556 PASS / 22 FAIL / 1 SKIP**，失败来自未提供的受限评测 registry，不能写作全量通过。

本次发布不部署线上服务，不扩大任意企业数据或模型的实时实验能力。比赛版、赛后云端冻结演示和仓库内合成示例的范围分别如上所述。

参见 [权利与许可范围](docs/RIGHTS_AND_LICENSING.md)、[第三方依赖声明](docs/THIRD_PARTY_NOTICES.md) 和 [既有演示素材说明](demo-site/assets/ASSET_RIGHTS.md)。历史文档中的早期分工不替代本页的现行团队贡献说明，也不构成版权归属或许可证明。
