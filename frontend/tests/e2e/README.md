# 工作台简化 E2E

`simplicity.cjs` 启动无头浏览器、真实前端和 FastAPI，使用独立 SQLite。
测试只替换 ShotPlanner、ComfyUI 和一致性指标运行时，不调用真实收费服务；所有 HTTP 请求、SSE、编译、审批、绑定、评测入库、人工采用和冻结校验仍走业务代码。
测试服务器禁止外部 HTTP 调用，会话记忆、原图、候选、数据库、截图及 trace 都写入新的 `.codex-artifacts/simplicity-e2e-*` 目录。

先构建页面（额外的 `--` 用于现有 npm-run-all 参数转发）：

```powershell
cd frontend
npm run build -- -- --outDir ../.codex-artifacts/simplicity-frontend-build --emptyOutDir
cd ..
node frontend/tests/e2e/simplicity.cjs
```

运行环境需要 Python 后端依赖和 Playwright。仓库不为此新增 npm 依赖；可以通过环境变量指定已有运行时：

- `COMAIC_TEST_PYTHON`：Python 可执行文件，默认 `python`。
- `PLAYWRIGHT_MODULE_PATH`：已有 `playwright` 模块目录，默认使用 Node 模块查找。
- `COMAIC_BROWSER_EXECUTABLE`：可选浏览器可执行文件，例如已安装的 Edge；默认使用 Playwright Chromium。

使用端口 `18124` 和 `15274`，退出时关闭本次启动的服务。请确保这两个端口空闲。

覆盖脚本完成后的生图准备入口、未准备禁止出图、显式准备三类 Prompt、仅生成缺图页、选择页面重画、过期提示词零提交、造型和场景保存并应用、仅存草稿、取消模式选择、冻结原图变动拒绝以及工具变更后的旧冻结批次续跑。
另验证设置统一编辑工具并保留 binding/能力声明，漫画出图和批量参考图只选择已有工具；缺少参考图有提示但可生成，错误配置零上传零提交；低于评测参考值仍可人工采用整套候选，逐页选图不依赖评测。
报告位于测试目录 `report.json`，浏览器 trace 位于 `trace.zip`。图片输出为普通测试色块，评分返回固定的低分，不评估真实生成质量或指标准确性；FastAPI lifespan 心跳与僵尸扫描的启动及付费 Provider 的真实连通性不在这项测试范围内。

另覆盖角色长短卡片的顶部对齐、字段间距、窄屏滚动，以及最终提示词语言仅在生图准备中选择、出图复用已有译文和重新准备其他语言后的冻结续跑。语言转换使用预先编写的模拟响应，不验证真实模型翻译质量。

`workspace-layout.cjs` 使用纯内存 API 检查全部工作区及主要弹窗：项目、脚本编辑、服装与场景、参考图上传与生成、批量参考图三个步骤、提示词规则、候选图、生成记录及生图工具配置。它验证 1440、1280 和 390 像素宽度下的页面溢出、弹窗滚动与底部操作，并检查信息图标的悬停、键盘聚焦和点击，以及英文界面。

完成上述构建后运行：

```powershell
node frontend/tests/e2e/workspace-layout.cjs
```

测试使用相同的运行时环境变量和端口，需与 `simplicity.cjs` 顺序执行。截图、报告与 trace 保存到 `.codex-artifacts/workspace-layout-*`，不读取本机业务数据库。

快速选图的专项离线验收：

```powershell
node frontend/tests/e2e/reference-quick-picker.cjs
```

它复用上述构建、运行时变量和端口，运行前检查端口空闲，并创建 40 个内存场景。覆盖最新与历史候选、上传草稿、场景版本隔离、大图预览、键盘选图、失败重试、确认后自动前进、人物停留、同用途旧图退回候选并可无重复转存地重新确认、末尾不循环、刷新定位及中英文布局。
另检查 1440、1280、390 和 360 像素宽度，包括手机短视口及英文界面，确保图片上的“确认可用”按钮完整显示、图片独立滚动、切换后回到首排及底部操作可见。截图、报告和 trace 保存到 `.codex-artifacts/reference-quick-picker-*`；与其它 E2E 顺序运行，不调用真实 Provider。

漫画快速选图的专项离线验收：

```powershell
cd frontend
npm run build-only -- --outDir ../.codex-artifacts/comic-quick-frontend-build --emptyOutDir
cd ..
node frontend/tests/e2e/comic-quick-picker.cjs
```

沿用上述 Playwright 和浏览器环境变量，也可通过 `COMAIC_TEST_FRONTEND_BUILD` 指定已有构建目录。测试使用随机端口的静态服务，全部 API 由浏览器拦截为内存数据，不需要 Python 后端。覆盖候选预览、键盘高亮、终稿同步、空页跳过、失败重试、自动前进、末页停留、页面搜索和中英文窄屏布局；浏览器 Profile、截图、报告及 trace 均保存到 `.codex-artifacts/comic-quick-picker-*`。
