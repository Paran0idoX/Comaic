"""验证临时注入保留 JSON、工具消息与多轮上下文，不发真实请求。"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.messages import AIMessageChunk
import asyncio

from backend.llm_clients.deepseek_creative import CreativeChatDeepSeek
from backend.llm_clients.factory import LLMConfigInput, create_chat_model
from backend.models.enums import LLMProvider


def test_creative_injection_keeps_schema_tools_and_input_memory():
    model = CreativeChatDeepSeek(model="deepseek-v4.1-flash", api_key="test-only", global_system_prompt="GLOBAL SYSTEM PROMPT")
    messages = [SystemMessage(content="Return the required page schema with locked keys."),
        HumanMessage(content="Write a fictional mystery."),
        AIMessage(content="", tool_calls=[{"name": "save_outline", "args": {"outline": "story"}, "id": "call1", "type": "tool_call"}]),
        ToolMessage(content="saved", tool_call_id="call1")]
    schema = {"type": "json_object"}
    tools = [{"type": "function", "function": {"name": "save_outline", "parameters": {"type": "object"}}}]
    payload = model._get_request_payload(messages, response_format=schema, tools=tools)
    assert payload["messages"][0]["content"] == "GLOBAL SYSTEM PROMPT\n\n" + messages[0].content
    assert payload["response_format"] == schema and payload["tools"] == tools
    assert payload["messages"][2]["tool_calls"][0]["id"] == "call1"
    assert payload["messages"][3]["tool_call_id"] == "call1"
    assert messages[0].content == "Return the required page schema with locked keys."
    assert model._get_request_payload(messages, response_format=schema, tools=tools) == payload


def test_creative_injection_can_be_disabled_and_handles_no_system():
    model = CreativeChatDeepSeek(model="deepseek-v4.1-flash", api_key="test-only", global_system_prompt="GLOBAL SYSTEM PROMPT")
    messages = [HumanMessage(content="Write a story.")]
    assert model._get_request_payload(messages)["messages"][0]["role"] == "system"
    model.global_system_prompt = ""
    assert model._get_request_payload(messages)["messages"] == [{"role": "user", "content": "Write a story."}]


def test_factory_uses_same_global_prompt_injection_for_all_providers():
    deepseek = create_chat_model(LLMConfigInput(provider=LLMProvider.DEEPSEEK,
        base_url=None, model="deepseek-flash", api_key="test-only", thinking_enabled=False, global_system_prompt="GLOBAL SYSTEM PROMPT"))
    assert isinstance(deepseek, CreativeChatDeepSeek)
    assert deepseek.global_system_prompt == "GLOBAL SYSTEM PROMPT"
    assert deepseek._get_request_payload([HumanMessage(content="story")])["extra_body"]["thinking"] == {"type": "disabled"}
    compatible = create_chat_model(LLMConfigInput(provider=LLMProvider.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:12345/v1", model="deepseek-flash", api_key="test-only", global_system_prompt="GLOBAL SYSTEM PROMPT"))
    assert not isinstance(compatible, CreativeChatDeepSeek)
    assert compatible.global_system_prompt == "GLOBAL SYSTEM PROMPT"


def test_trace_messages_match_request_without_changing_memory(monkeypatch):
    """用本地回调验证实际追踪输入，覆盖同步、异步、流式及直接批量调用。"""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    recorded = []

    class Recorder(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            recorded.append(messages[0])

    def generate(self, messages, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def agenerate(self, messages, **kwargs):
        return generate(self, messages, **kwargs)

    def stream(self, messages, **kwargs):
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))

    async def astream(self, messages, **kwargs):
        for chunk in stream(self, messages, **kwargs):
            yield chunk

    monkeypatch.setattr(CreativeChatDeepSeek, "_generate", generate)
    monkeypatch.setattr(CreativeChatDeepSeek, "_agenerate", agenerate)
    monkeypatch.setattr(CreativeChatDeepSeek, "_stream", stream)
    monkeypatch.setattr(CreativeChatDeepSeek, "_astream", astream)
    model = CreativeChatDeepSeek(model="deepseek-v4.1-flash", api_key="test-only", global_system_prompt="GLOBAL SYSTEM PROMPT")
    messages = [SystemMessage(content="Business prompt"), HumanMessage(content="story")]
    config = {"callbacks": [Recorder()]}
    model.invoke(messages, config=config)
    list(model.stream(messages, config=config))
    model.generate([messages], callbacks=config["callbacks"])

    async def run_async():
        await model.ainvoke(messages, config=config)
        _ = [chunk async for chunk in model.astream(messages, config=config)]
        await model.agenerate([messages], callbacks=config["callbacks"])

    asyncio.run(run_async())
    expected = model._get_request_payload(messages)["messages"][0]["content"]
    assert len(recorded) == 6
    assert all(batch[0].content == expected for batch in recorded)
    assert messages[0].content == "Business prompt"
    assert model._get_request_payload(recorded[0])["messages"][0]["content"] == expected
