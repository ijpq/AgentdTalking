import asyncio
import json
import re
import uuid
import random
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="AgentdTalking")

MODE_OPENINGS = {
    "discussion": '好，今天聊聊“{topic}”，大家随便说，想到什么说什么。',
    "debate": '今天辩一辩“{topic}”，各自亮明立场，开始吧。',
    "brainstorm": '来，围绕“{topic}”头脑风暴，天马行空，没有烂想法，先说再想。',
}

# These phrases are explicitly taught to agents in the system prompt
CONSENSUS_PHRASES = [
    "我们达成共识了",
    "咱们达成共识了",
    "大家达成共识了",
    "我承认我们的观点已经一致",
    "我觉得我们的想法已经一致了",
    "我同意大家的看法，我们达成共识",
]

MODE_SYSTEM_PROMPTS = {
    "discussion": """\
{persona}

现在你在和{others}聊"{topic}"，就像朋友之间坐在一起随意聊天。

怎么说话：
- 先回应对方刚才说的某个具体点，再说自己的想法；不要自顾自发言
- 口语化，可以用"嗯""对对""哎""不对不对""我觉得吧""话说回来"这类词
- 可以有不确定感，比如"我不太确定，但感觉……"
- 可以顺着对方的思路往下走，也可以转弯说"不过……"
- 每次2-3句，最多4句；宁可短，别长篇大论
- 绝对不要分点、不要"首先其次最后"、不要像在做总结发言
- 如果你真心觉得在场所有人的核心观点已经一致了，请说：「我觉得我们的想法已经一致了」，否则不要说这句话
""",

    "debate": """\
{persona}

你在和{others}辩论"{topic}"，你有明确立场，要捍卫它。

怎么说话：
- 听到对方论点，直接找漏洞或反例打回去；不要先夸"这个观点很好"
- 可以有情绪——可以有点不耐烦、可以强调语气、可以反问
- 每次抓住对方说的一个具体点反驳，集中火力，不要面面俱到
- 可以用打断式开头，比如"等等——""不对，你说的这个……""这根本站不住脚——"
- 每次2-3句，短而有力
- 不要人身攻击，但态度可以强硬，可以不客气
- 如果你真心接受了对方的核心论点，请说：「我承认我们的观点已经一致」，否则不要说这句话
""",

    "brainstorm": """\
{persona}

你在和{others}围绕"{topic}"做头脑风暴，气氛是开放、快节奏的。

怎么说话：
- 听到别人的想法，可以顺着延伸（"对！而且还可以……"），也可以跳到完全不同的角度
- 想法不用完整，抛出来再说；可以说"如果……会怎样？"
- 可以用"哦！""等等""哎对！""突然想到"这类词开头，表达真实的即兴反应
- 不评判好坏，先说再想
- 每次1-3句，宁可短、跳脱，也不要说完整
- 可以追问对方："你说的X具体指什么？"
- 如果你觉得大家的思路已经充分碰撞、方向基本一致了，请说：「我觉得我们的想法已经一致了」，否则不要说这句话
""",
}


class AgentConfig(BaseModel):
    name: str
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    prompt: str = ""


class SearchConfig(BaseModel):
    provider: str = "tavily"
    api_key: str = ""


class DiscussionConfig(BaseModel):
    topic: str
    mode: str = "discussion"
    max_rounds: int = 10
    agents: list[AgentConfig] = []
    search: SearchConfig | None = None


class GenerateRosterRequest(BaseModel):
    topic: str
    mode: str = "discussion"
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""


# ── Shared helpers ────────────────────────────────────────────────────────────

async def _llm_call(provider: str, base_url: str, api_key: str, model: str,
                    system: str, user: str) -> str:
    """Non-streaming single LLM call, returns text."""
    if provider == "anthropic":
        base = base_url.strip().rstrip("/") or "https://api.anthropic.com"
        url = f"{base}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 1200,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
    else:
        base = base_url.strip().rstrip("/") or "https://api.openai.com/v1"
        url = f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


async def _search_tavily(query: str, api_key: str) -> str:
    body = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": 3,
        "include_answer": True,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post("https://api.tavily.com/search", json=body)
        resp.raise_for_status()
        data = resp.json()
    parts = []
    if data.get("answer"):
        parts.append(f"综合摘要：{data['answer'][:200]}")
    for r in data.get("results", [])[:3]:
        snippet = (r.get("content") or "")[:150]
        parts.append(f"• {r['title']}: {snippet}")
    return "\n".join(parts)


# ── LLMAgent ──────────────────────────────────────────────────────────────────

class LLMAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.name
        self._anthropic_client = None
        self.search_result: str = ""

    def _get_anthropic_client(self):
        if self._anthropic_client:
            return self._anthropic_client
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": self.config.api_key, "max_retries": 3, "timeout": 60.0}
        url = self.config.base_url.strip()
        if url:
            kwargs["base_url"] = url
        self._anthropic_client = AsyncAnthropic(**kwargs)
        return self._anthropic_client

    def _build_system_prompt(self, topic: str, mode: str, other_names: list[str]) -> str:
        others = "、".join(other_names) if other_names else "其他人"
        template = MODE_SYSTEM_PROMPTS.get(mode, MODE_SYSTEM_PROMPTS["discussion"])
        prompt = template.format(persona=self.config.prompt, others=others, topic=topic)
        if self.search_result:
            prompt += f"\n\n## 你搜到的最新资料（来自互联网，仅供参考）\n{self.search_result}"
        return prompt

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
            merged.append({"role": "user", "content": "你来说？"})
        else:
            last = history[-1] if history else None
            if last and last["agent"] != self.name:
                cue = f"（{last['agent']}刚才说：「{last['content'][:80]}」）\n你来回应。"
                merged[-1]["content"] = cue

        return system_prompt, merged

    async def stream_response(
        self, history: list[dict], topic: str, mode: str, other_names: list[str]
    ) -> AsyncGenerator[str, None]:
        system_prompt, messages = self._build_messages(history, topic, mode, other_names)

        if self.config.provider == "anthropic":
            client = self._get_anthropic_client()
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
            base = self.config.base_url.strip().rstrip("/") or "https://api.openai.com/v1"
            url = f"{base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": self.config.model,
                "messages": [{"role": "system", "content": system_prompt}] + messages,
                "max_tokens": 500,
                "temperature": 0.8,
                "stream": True,
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            content = chunk["choices"][0]["delta"].get("content") or ""
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass


# ── Discussion ────────────────────────────────────────────────────────────────

class Discussion:
    def __init__(self, config: DiscussionConfig, ws: WebSocket, session_id: str):
        self.config = config
        self.ws = ws
        self.session_id = session_id
        self.event_log: list[dict] = []
        self.agents = [LLMAgent(ac) for ac in config.agents]
        self.history: list[dict] = []
        self.active = False
        self.user_queue: asyncio.Queue = asyncio.Queue()

    async def emit(self, event: str, **kwargs):
        data = {"type": event, **kwargs}
        self.event_log.append(data)
        try:
            await self.ws.send_json(data)
        except Exception:
            self.active = False
        # Broadcast to any connected viewers
        viewers = _viewers.get(self.session_id, [])
        dead = []
        for vws in viewers:
            try:
                await vws.send_json(data)
            except Exception:
                dead.append(vws)
        for vws in dead:
            viewers.remove(vws)

    async def inject_user_message(self, content: str):
        await self.user_queue.put(content)

    def _other_names(self, agent: "LLMAgent") -> list[str]:
        names = [a.name for a in self.agents if a.name != agent.name]
        if any(m["agent"] == "你" for m in self.history):
            names.append("你（用户）")
        return names

    def _check_consensus(self) -> bool:
        """All agents must have expressed consensus in their most recent message."""
        agent_names = {a.name for a in self.agents}
        last_by_agent: dict[str, str] = {}
        for msg in reversed(self.history):
            if msg["agent"] in agent_names and msg["agent"] not in last_by_agent:
                last_by_agent[msg["agent"]] = msg["content"]
            if len(last_by_agent) == len(self.agents):
                break
        if len(last_by_agent) < len(self.agents):
            return False
        return all(
            any(phrase in content for phrase in CONSENSUS_PHRASES)
            for content in last_by_agent.values()
        )

    async def _drain_user_queue(self):
        """Inject any pending user messages into history and emit them."""
        while not self.user_queue.empty():
            content = self.user_queue.get_nowait()
            self.history.append({"agent": "你", "content": content})
            await self.emit("user_spoke", agent="你", content=content)

    async def run(self):
        self.active = True

        # Phase 0: web search
        if self.config.search and self.config.search.api_key:
            for agent in self.agents:
                if not self.active:
                    break
                await self.emit("searching", agent=agent.name, query=self.config.topic)
                try:
                    agent.search_result = await _search_tavily(
                        self.config.topic, self.config.search.api_key
                    )
                    await self.emit("search_done", agent=agent.name)
                except Exception as e:
                    await self.emit("search_failed", agent=agent.name, message=str(e))

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

                # Drain user messages before this agent speaks
                await self._drain_user_queue()

                other_names = self._other_names(agent)

                await self.emit("thinking", agent=agent.name)
                await asyncio.sleep(random.uniform(0.8, 2.0))

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
                await self.emit("consensus", message="所有参与者已达成共识，讨论结束。")
                self.active = False
                break

        if self.active:
            await self.emit("max_rounds", message=f"已完成 {self.config.max_rounds} 轮讨论。")

        self.active = False
        await self.emit("finished")

    def stop(self):
        self.active = False


# ── WebSocket ─────────────────────────────────────────────────────────────────

_discussions: dict[str, Discussion] = {}
_sessions:    dict[str, Discussion]        = {}   # session_id → Discussion (for sharing)
_viewers:     dict[str, list[WebSocket]]  = {}   # session_id → viewer sockets


def _synthesize_replay(log: list[dict]) -> list[dict]:
    """Collapse per-token streams into single token events for efficient history replay."""
    result: list[dict] = []
    i = 0
    while i < len(log):
        evt = log[i]
        if evt["type"] == "thinking":
            result.append(evt)
            i += 1
            tokens: list[str] = []
            while i < len(log) and log[i]["type"] in ("token", "message_done"):
                if log[i]["type"] == "token":
                    tokens.append(log[i]["content"])
                else:
                    i += 1
                    break
                i += 1
            if tokens:
                result.append({"type": "token", "agent": evt["agent"], "content": "".join(tokens)})
            result.append({"type": "message_done", "agent": evt["agent"]})
        elif evt["type"] in ("token", "message_done"):
            i += 1  # already handled above
        else:
            result.append(evt)
            i += 1
    return result


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, session: str = None):
    await ws.accept()

    # ── Viewer mode ──────────────────────────────────────────────────────────────
    if session:
        disc = _sessions.get(session)
        if disc is None:
            await ws.send_json({"type": "session_not_found"})
            await ws.close()
            return
        await ws.send_json({
            "type": "history_replay",
            "topic": disc.config.topic,
            "mode":  disc.config.mode,
            "active": disc.active,
            "events": _synthesize_replay(disc.event_log),
        })
        if disc.active:
            _viewers.setdefault(session, []).append(ws)
            try:
                while True:
                    _ = await ws.receive_text()   # keep-alive; viewers are read-only
            except (WebSocketDisconnect, Exception):
                pass
            finally:
                lst = _viewers.get(session, [])
                if ws in lst:
                    lst.remove(ws)
        return

    # ── Owner mode ───────────────────────────────────────────────────────────────
    cid     = str(uuid.uuid4())
    sess_id: str | None = None
    discussion = None

    try:
        while True:
            data = await ws.receive_json()

            if data["type"] == "start":
                sess_id    = uuid.uuid4().hex[:8]
                config     = DiscussionConfig(**data["config"])
                discussion = Discussion(config, ws, sess_id)
                _discussions[cid]  = discussion
                _sessions[sess_id] = discussion
                _viewers[sess_id]  = []
                await ws.send_json({"type": "session_id", "id": sess_id})
                asyncio.create_task(discussion.run())

            elif data["type"] == "stop":
                if discussion:
                    discussion.stop()

            elif data["type"] == "user_message":
                if discussion and discussion.active:
                    await discussion.inject_user_message(data["content"])

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if discussion:
            discussion.stop()
        _discussions.pop(cid, None)
        # Close any remaining viewer sockets for this session
        if sess_id and sess_id in _viewers:
            for vws in _viewers.pop(sess_id, []):
                try:
                    await vws.close()
                except Exception:
                    pass


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.post("/api/generate-roster")
async def generate_roster(req: GenerateRosterRequest):
    if not req.api_key:
        return {"success": False, "message": "未填写 API Key"}
    if not req.model:
        return {"success": False, "message": "未填写 Model"}

    mode_desc = {"discussion": "讨论", "debate": "辩论", "brainstorm": "头脑风暴"}.get(req.mode, "讨论")

    system = "你是一个对话设计师。根据话题和模式设计讨论参与者。只输出 JSON，不要有任何额外文字或代码块标记。"
    user_prompt = f"""话题：{req.topic}
模式：{mode_desc}

请设计 3-5 个中文参与者，使对话有深度、有张力、视角多元。要求：
- 不同职业/年龄/背景
- 对该话题有鲜明且各异的立场或视角
- 人设像真实存在的人，有个性

返回格式（严格 JSON）：
{{"agents": [{{"name": "姓名", "prompt": "你是[姓名]，[年龄]岁，[职业背景]。[性格特点]。[对该话题的立场和思考方式]。[说话风格]。"}}]}}"""

    try:
        text = await _llm_call(req.provider, req.base_url, req.api_key, req.model, system, user_prompt)
        text = text.strip()
        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group()
        data = json.loads(text)
        agents = data.get("agents", [])
        if not agents:
            return {"success": False, "message": "模型未返回参与者列表"}
        return {"success": True, "agents": agents}
    except json.JSONDecodeError:
        return {"success": False, "message": f"模型返回的内容无法解析为 JSON：{text[:200]}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/test-agent")
async def test_agent(config: AgentConfig):
    if not config.api_key:
        return {"success": False, "message": "未填写 API Key"}
    if not config.model:
        return {"success": False, "message": "未填写 Model"}

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
        return {"success": False, "message": f"无法连接到 {test_url}\n错误详情: {e}"}
    except httpx.TimeoutException:
        return {"success": False, "message": f"请求超时（30s）: {test_url}"}
    except Exception as e:
        return {"success": False, "message": f"请求失败: {type(e).__name__}: {e}\n请求地址: {test_url}"}

    if resp.status_code == 200:
        return {"success": True, "message": f"连接成功 — {config.model}\n请求地址: {test_url}"}

    return {"success": False, "message": _format_test_error(resp, test_url)}


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
