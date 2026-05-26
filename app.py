import asyncio
import re
import uuid
import random
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="AgentdTalking")

MODE_LABELS = {"discussion": "讨论", "debate": "辩论", "brainstorm": "头脑风暴"}

MODE_OPENINGS = {
    "discussion": "大家好，今天我们来讨论一下：{topic}。请各位分享自己的看法。",
    "debate": "大家好，今天我们来辩论一下：{topic}。请各位表明立场并给出论据。",
    "brainstorm": "大家好，今天我们来进行一场头脑风暴：{topic}。请大家自由发挥，大胆提出想法。",
}

CONSENSUS_KEYWORDS = ["同意", "达成一致", "共识", "赞同", "没有异议", "一致认为", "都同意", "我也这么认为"]


class AgentConfig(BaseModel):
    name: str
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    prompt: str = ""


class DiscussionConfig(BaseModel):
    topic: str
    mode: str = "discussion"
    max_rounds: int = 10
    agents: list[AgentConfig] = []


class LLMAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.name
        self._client = None

    def _get_client(self):
        if self._client:
            return self._client

        kwargs = {"api_key": self.config.api_key, "max_retries": 3, "timeout": 60.0}
        url = self.config.base_url.strip()
        if url:
            kwargs["base_url"] = url

        if self.config.provider == "anthropic":
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(**kwargs)
        else:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _build_system_prompt(self, topic: str, mode: str, other_names: list[str]) -> str:
        mode_label = MODE_LABELS.get(mode, "讨论")
        others = "、".join(other_names)
        return f"""{self.config.prompt}

你正在和{others}进行一场关于"{topic}"的{mode_label}。

要求：
- 你是一个真实的人，和你说话的都是真实的人
- 说话自然、口语化，像面对面聊天
- 可以延展话题，但不要偏离"{topic}"
- 每次发言控制在2-4句话
- 如果你觉得大家已经达成了共识，请明确说"我同意"或"我们达成一致了"
- 有自己的观点和立场，不要轻易附和"""

    def _build_messages(self, history: list[dict], topic: str, mode: str, other_names: list[str]):
        system_prompt = self._build_system_prompt(topic, mode, other_names)

        raw = []
        for msg in history:
            if msg["agent"] == self.name:
                raw.append({"role": "assistant", "content": msg["content"]})
            else:
                raw.append({"role": "user", "content": f'{msg["agent"]}说：{msg["content"]}'})

        merged = []
        for msg in raw:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["content"] += "\n\n" + msg["content"]
            else:
                merged.append(msg.copy())

        if not merged or merged[-1]["role"] == "assistant":
            merged.append({"role": "user", "content": "请继续发表你的看法。"})

        return system_prompt, merged

    async def stream_response(
        self, history: list[dict], topic: str, mode: str, other_names: list[str]
    ) -> AsyncGenerator[str, None]:
        system_prompt, messages = self._build_messages(history, topic, mode, other_names)
        client = self._get_client()

        if self.config.provider == "anthropic":
            async with client.messages.stream(
                model=self.config.model,
                max_tokens=500,
                system=system_prompt,
                messages=messages,
                temperature=0.8,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        else:
            response = await client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                max_tokens=500,
                temperature=0.8,
                stream=True,
            )
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content


class Discussion:
    def __init__(self, config: DiscussionConfig, ws: WebSocket):
        self.config = config
        self.ws = ws
        self.agents = [LLMAgent(ac) for ac in config.agents]
        self.history: list[dict] = []
        self.active = False

    async def emit(self, event: str, **kwargs):
        try:
            await self.ws.send_json({"type": event, **kwargs})
        except Exception:
            self.active = False

    def _check_consensus(self) -> bool:
        n = len(self.agents)
        if len(self.history) < n:
            return False
        recent = self.history[-n:]
        count = sum(
            1
            for msg in recent
            if any(kw in msg["content"] for kw in CONSENSUS_KEYWORDS)
        )
        return count >= max(n - 1, 2)

    async def run(self):
        self.active = True

        opening = MODE_OPENINGS.get(self.config.mode, MODE_OPENINGS["discussion"]).format(
            topic=self.config.topic
        )
        self.history.append({"agent": "主持人", "content": opening})
        await self.emit("moderator", content=opening)
        await asyncio.sleep(1)

        for round_idx in range(self.config.max_rounds):
            if not self.active:
                break

            await self.emit("round", number=round_idx + 1)

            for agent in self.agents:
                if not self.active:
                    break

                other_names = [a.name for a in self.agents if a.name != agent.name]

                await self.emit("thinking", agent=agent.name)
                await asyncio.sleep(random.uniform(1.0, 2.5))

                full_text = ""
                try:
                    async for token in agent.stream_response(
                        self.history, self.config.topic, self.config.mode, other_names
                    ):
                        if not self.active:
                            break
                        full_text += token
                        await self.emit("token", agent=agent.name, content=token)

                    if full_text:
                        self.history.append({"agent": agent.name, "content": full_text})
                        await self.emit("message_done", agent=agent.name)
                except Exception as e:
                    await self.emit("error", agent=agent.name, message=str(e))

            if self._check_consensus():
                await self.emit("consensus", message="参与者已达成共识，讨论结束。")
                self.active = False
                break

        if self.active:
            await self.emit("max_rounds", message=f"已完成 {self.config.max_rounds} 轮讨论。")

        self.active = False
        await self.emit("finished")

    def stop(self):
        self.active = False


_discussions: dict[str, Discussion] = {}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    cid = str(uuid.uuid4())
    discussion = None

    try:
        while True:
            data = await ws.receive_json()

            if data["type"] == "start":
                config = DiscussionConfig(**data["config"])
                discussion = Discussion(config, ws)
                _discussions[cid] = discussion
                asyncio.create_task(discussion.run())

            elif data["type"] == "stop":
                if discussion:
                    discussion.stop()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if discussion:
            discussion.stop()
        _discussions.pop(cid, None)


@app.post("/api/test-agent")
async def test_agent(config: AgentConfig):
    if not config.api_key:
        return {"success": False, "message": "未填写 API Key"}
    if not config.model:
        return {"success": False, "message": "未填写 Model"}

    import httpx

    base = config.base_url.strip().rstrip("/")

    if config.provider == "anthropic":
        base = base or "https://api.anthropic.com"
        test_url = f"{base}/v1/messages"
        headers = {
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": config.model,
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "Hi"}],
        }
    else:
        base = base or "https://api.openai.com/v1"
        test_url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": config.model,
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "Hi"}],
        }

    try:
        async with httpx.AsyncClient(
            timeout=30,
            transport=httpx.AsyncHTTPTransport(retries=2),
        ) as client:
            resp = await client.post(test_url, json=body, headers=headers)
    except httpx.ConnectError as e:
        return {"success": False, "message": f"无法连接到 {test_url}\n错误详情: {e}\n请检查网络或 Base URL 是否可达"}
    except httpx.TimeoutException:
        return {"success": False, "message": f"请求超时（30s）: {test_url}\n提示：可能是网络到目标服务器延迟过高"}
    except Exception as e:
        return {"success": False, "message": f"请求失败: {type(e).__name__}: {e}\n请求地址: {test_url}"}

    if resp.status_code == 200:
        return {"success": True, "message": f"连接成功 — {config.model}\n请求地址: {test_url}"}

    msg = _format_test_error(resp, test_url)
    return {"success": False, "message": msg}


def _format_test_error(resp, test_url: str) -> str:
    code = resp.status_code
    ct = resp.headers.get("content-type", "")
    body = resp.text[:500]

    if "json" in ct:
        try:
            data = resp.json()
            detail = (
                data.get("error", {}).get("message", "")
                or data.get("message", "")
                or str(data)
            )
            if len(detail) > 300:
                detail = detail[:300] + "..."
            return f"HTTP {code}: {detail}\n请求地址: {test_url}"
        except Exception:
            pass

    if "<html" in body.lower() or "<!doctype" in body.lower():
        title = ""
        m = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()
        detail = title or "HTML 错误页面"
        return (
            f"HTTP {code} — {detail}\n"
            f"请求地址: {test_url}\n"
            f"服务器返回了网页而非 JSON，常见原因：\n"
            f"  • Base URL 路径不对（应填到 /v1）\n"
            f"  • API Key / 鉴权信息不匹配\n"
            f"  • Cloudflare WAF 拦截了请求"
        )

    snippet = body[:200] + "..." if len(body) > 200 else body
    return f"HTTP {code}\n请求地址: {test_url}\n响应: {snippet}"


@app.get("/")
async def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
