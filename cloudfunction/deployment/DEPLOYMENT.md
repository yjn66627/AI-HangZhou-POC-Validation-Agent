# 独立安全测试环境部署说明

以下是供人工审核使用的配置步骤，本候选没有执行部署。`http-gateway.template.json` 是字段说明模板，不能直接交给 CLI 执行。

1. 使用自己有权限的独立 CloudBase 测试环境；确认费用、配额和运行时支持，避免更改现有服务。
2. 审核 `function/fixtures/synthetic_demo_success.json`，确认所有数据为合成。`requirements.txt` 声明标准库运行依赖；不需要安装第三方运行包。
3. 函数类型选择 HTTP，运行时对照 Python3.9，内存 256MB、超时 3 秒。部署包根目录必须直接包含 `index.py`、`__init__.py`、`server.py`、`scf_bootstrap` 和 `fixtures/`，不能额外套一层 function 目录。
4. Linux 上保证 `scf_bootstrap` 可执行且使用 LF 行尾。脚本使用 `/var/lang/python39/bin/python3.9`，监听平台 9000 端口。若供应商改变该路径或运行时，应先在独立环境验证兼容性，不要把未经验证的适配写成已部署事实。
5. 在云端安全配置界面注入你新生成的 `ISOLATED_CLOUD_TEST_CREDENTIAL`。`.env.example` 只有变量名，标准库函数不会自动读取 .env。不要在 JSON 模板、Git、命令历史或文档里写入值。
6. Gateway 设置 GET `/tool/project_experiment_run_read`，upstream 为自己的 HTTP 函数（WEB_SCF），保留原始路径传递。函数内部执行 Bearer 校验；模板不包含现有项目域名或资源 ID。
7. 在独立测试环境验证无凭据/错误凭据为 401、合法测试凭据为 200 且 data 明确为 SYNTHETIC_DEMO_DATA，同时验证非空 query 被拒绝。检查 status 与 JSON Schema，不把 HTTP 200 单独视为业务成功。
8. 仅在另行获得配置授权后，才可让你自己的腾讯元器测试 Tool 指向新路由并在安全界面设置请求头。本说明不包含现有腾讯元器账号或配置。

本地 contract tests 只证明源码与合成数据的契约兼容，不证明云端路由、权限、TLS、冷启动、配额或腾讯元器端到端效果。云资源、域名、凭据注入、路由绑定和流量切换仍需部署者显式配置与验证。
