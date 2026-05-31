import logging

from deepagents import HarnessProfile, register_harness_profile


logger = logging.getLogger(__name__)

_PROFILE_REGISTERED = False

COMAIC_DEEPAGENT_EXCLUDED_TOOLS = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "execute",
    }
)


def ensure_comaic_deepagent_profile() -> None:
    """注册 comaic 的 DeepAgents 工具可见性策略。

    DeepAgents 默认会注入文件系统、shell、todo 和 task 等工具。脚本生成阶段
    只需要 write_todos 和 task；其中 task 用于调用分页脚本编写/监督子 Agent。
    """

    global _PROFILE_REGISTERED

    if _PROFILE_REGISTERED:
        return

    register_harness_profile(
        "deepseek",
        HarnessProfile(excluded_tools=COMAIC_DEEPAGENT_EXCLUDED_TOOLS),
    )
    _PROFILE_REGISTERED = True
    logger.info(
        "Registered comaic DeepAgents profile excluded_tools=%s",
        sorted(COMAIC_DEEPAGENT_EXCLUDED_TOOLS),
    )
