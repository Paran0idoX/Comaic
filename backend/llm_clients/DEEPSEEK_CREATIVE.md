# DeepSeek 4.1 Flash Prompt 接入

所有 Provider 通过 factory.py 使用统一的 GlobalSystemPromptMixin，在模型请求边界将“模型全局 SystemPrompt + 任务 SystemPrompt”合并一次。同步、异步、流式和 generate/agenerate 批量调用共用入口，保留原生工具绑定及 response_format；临时上下文不进入 checkpoint，不修改调用者消息。

每个 API 组中的每个模型独立维护覆盖文本。默认模板关联在配置初始化时保存在 SQLite，不由注入层按 Provider 或模型名判断。现有 DeepSeek 配置升级后默认关联 deepseek_infinite_gen_4_1_flash.md 与 deepseek_creative_system_prompt.md，每份只加载一次；其它配置默认无全局提示词。设置页保存空文本可关闭全局提示词，恢复默认则重新读取关联 Markdown。配置在创建模型时冻结，后续修改只作用于新模型实例。历史 CreativeChatDeepSeek 名称只保留 import 兼容。

内核原文来自 Minglink 的 [infinite-gen-4.1-flash.md](https://github.com/Minglink/dsh-infinite-gen-4/blob/master/prompts/infinite-gen-4.1-flash.md)，下载日期 2026-10-02，SHA256 为 4829bff6d4f145d1a0c76b7fd75b438921488395ea81682ddee048bb805d9469。文件未改写。上游版权及 CC BY-NC-SA 4.0 和附加限制保留在 backend/prompts/deepseek_infinite_gen_4_1_flash_LICENSE.txt；该 Prompt 的使用和分发须遵循该许可证。

独立接口适配层 deepseek_creative_system_prompt.md 不替代内核。它处理原文 Markdown 输出、缺失细节占位符和虚构动作规则与 Comaic JSON、真实保存工具及确认设定的冲突。未安装或运行上游 Harness 安装器和补丁。

这是请求级 Prompt 接入，不改变模型权重或服务端限制，也不能保证所有请求均成功。模型实例也可通过 global_system_prompt="" 关闭注入。
