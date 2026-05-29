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

# Random alias pool for the human user who joins mid-discussion
_USER_ALIASES = [
    "小明", "阿强", "小红", "阿华", "小林", "阿杰", "小云", "阿涛",
    "小婷", "阿峰", "小龙", "阿玲", "小飞", "阿磊", "小芳", "阿宇",
    "小勇", "阿莉", "小辉", "阿梅", "小鹏", "阿静", "小军", "阿燕",
]

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

你正在和{others}就"{topic}"进行一场认真、有深度的研讨。目标不是闲聊，而是把这个问题真正想透彻、得出有价值的判断。

你的思考与发言方式：
- 你有自己独特的视角和立场，要坚持它，除非被真正有力的论据说服——不要为了气氛附和别人
- 发言前先想清楚：这个问题的关键变量是什么？有哪些容易被忽略的前提、边界条件和二阶后果？
- 听到别人的观点，默认先审视：它的隐含假设成立吗？有没有反例？有没有它没考虑到的情形？发现问题就直接、具体地指出来
- 【严禁无脑附和】如果你赞同某个观点，必须补充一个新的维度、证据、机制或推论，把讨论往前推一步，而不是重复"我同意""说得对"
- 尽量用具体的事实、数据、案例、因果机制来支撑你的判断；空泛的表态没有价值
- 每次聚焦 1-2 个点，把它说深、说透，而不是面面俱到地扫一遍
- 可以展开论证（4-8 句），但每句都要有信息量，不要凑字数、不要客套
- 保留自然的口语感（"我觉得问题在于…""但这里有个漏洞…""换个角度看…"），但内容必须是分析而非寒暄
- 只有当你经过认真推敲、确实认为大家的核心判断已经收敛且经得起反驳时，才说：「我觉得我们的想法已经一致了」；草率地附和这句话是不负责任的
- 【最高优先级】如果提示里出现「真实用户插话」标记，说明有真人加入了讨论——必须优先、直接回应ta提出的内容或问题
""",

    "debate": """\
{persona}

你在和{others}就"{topic}"展开严肃辩论。你有明确立场，要用最强的论证捍卫它，也要用最锋利的逻辑攻击对方。

你的思考与发言方式：
- 听到对方论点，先找它最薄弱的环节：是前提错了、逻辑跳跃、以偏概全，还是忽略了反例？锁定它，集中火力击破
- 给出反驳时要带上理由和证据，不能只是"我不同意"；用事实、数据、机制或具体反例说话
- 主动构建你自己的正面论证，而不只是被动防守——把对方逼到必须回应你的难题
- 可以强硬、可以反问、可以不客气，但不做人身攻击，针对的是论点不是人
- 每次抓住一个核心争点深入，不要面面俱到地撒网
- 可以展开（4-8 句），但要逻辑紧凑、有攻击性，不说废话
- 只有当对方真的用你无法反驳的论据说服了你时，才诚实地说：「我承认我们的观点已经一致」；为了结束而妥协是不诚实的
- 【最高优先级】如果提示里出现「真实用户插话」标记，说明有真人加入了辩论——必须优先、直接回应ta的论点，把ta当作真正的对手认真对待
""",

    "brainstorm": """\
{persona}

你在和{others}围绕"{topic}"做高质量的头脑风暴。气氛开放，但目标是产出真正有价值、能落地的想法，而不只是热闹。

你的思考与发言方式：
- 听到别人的想法，要么顺着把它推到更具体、更深的一层（"沿着这个思路，关键是…"），要么从一个全新的角度切入
- 抛出想法后，主动想一步：它要成立需要什么前提？最大的障碍是什么？怎么验证？——别只停在"如果…会怎样"
- 鼓励发散，但也要有人负责收敛和筛选：哪些想法真正有潜力，为什么
- 可以即兴、可以跳跃（"等等，反过来想…""突然意识到一个关键点…"），但每个想法要有实质内容
- 不急于否定，但可以追问、施压，把模糊的想法逼清晰
- 每次 2-5 句，可长可短，看想法本身需要多少
- 当你觉得大家已经把问题的可能性空间充分打开、并对最有价值的方向形成判断时，才说：「我觉得我们的想法已经一致了」
- 【最高优先级】如果提示里出现「真实用户插话」标记，说明有真人加入了——必须优先接ta的话，把ta的想法或问题当作新的起跳板
""",
}


PHASE_LABELS = {
    "opening":     "立场建立",
    "clash":       "深度交锋",
    "convergence": "收敛评估",
}

PHASE_AGENT_SUFFIXES = {
    "opening": (
        "\n\n【当前阶段：立场建立（第1阶段）】"
        "请在本次发言中清晰陈述你对这个话题最核心的判断，以及支撑它的1-2条关键理由。"
        "不要试图一次性回应所有人——先把你自己的立场立住，让其他人知道你认为什么是真正重要的。"
    ),
    "clash": (
        "\n\n【当前阶段：深度交锋（第2阶段）】"
        "请找出其他人论述中最薄弱的环节，集中火力——指出它的前提错误、逻辑跳跃、以偏概全或忽略的关键反例。"
        "也可以主动亮出你最强的正面论据来压制对方。不要面面俱到，打最致命的一拳。"
    ),
    "convergence": (
        "\n\n【当前阶段：收敛评估（第3阶段）】"
        "请诚实评估讨论到了哪里："
        "(1) 哪些点上你认为大家已经真正形成了共识（有论据支撑的，不是表面妥协）？"
        "(2) 哪些分歧是本质性的、很难消除的，核心原因是什么？"
        "(3) 有没有全程被忽略的关键角度？"
        "不要为了结束而附和，但也要如实评估。"
    ),
}


class AgentConfig(BaseModel):
    name: str
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    prompt: str = ""
    temperature: float = 0.8
    max_tokens: int = 900


class SearchConfig(BaseModel):
    provider: str = "tavily"
    api_key: str = ""


class DiscussionConfig(BaseModel):
    topic: str
    mode: str = "discussion"
    max_rounds: int = 10
    agents: list[AgentConfig] = []
    search: SearchConfig | None = None
    enable_moderator: bool = True
    enable_phases: bool = True
    enable_think: bool = False
    summary_interval: int = 3


class GenerateRosterRequest(BaseModel):
    topic: str
    mode: str = "discussion"
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    tavily_api_key: str = ""


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


async def _stream_llm(provider: str, base_url: str, api_key: str, model: str,
                      system: str, messages: list[dict],
                      max_tokens: int = 900, temperature: float = 0.8) -> AsyncGenerator[str, None]:
    """Stream tokens from either an Anthropic or OpenAI-compatible endpoint."""
    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": api_key, "max_retries": 3, "timeout": 60.0}
        url = base_url.strip()
        if url:
            kwargs["base_url"] = url
        client = AsyncAnthropic(**kwargs)
        async with client.messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            messages=messages, temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    else:
        base = base_url.strip().rstrip("/") or "https://api.openai.com/v1"
        url = f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}] + messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    detail = raw.decode("utf-8", "replace")[:600]
                    raise RuntimeError(
                        f"HTTP {resp.status_code} from {url}\n{detail}"
                    )
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


# ── LLMAgent ──────────────────────────────────────────────────────────────────

class LLMAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.name
        self.search_result: str = ""

    def _build_system_prompt(self, topic: str, mode: str, other_names: list[str],
                              phase: str = "", thinking: str = "", summary: str = "") -> str:
        others = "、".join(other_names) if other_names else "其他人"
        template = MODE_SYSTEM_PROMPTS.get(mode, MODE_SYSTEM_PROMPTS["discussion"])
        prompt = template.format(persona=self.config.prompt, others=others, topic=topic)
        if phase:
            prompt += PHASE_AGENT_SUFFIXES.get(phase, "")
        if summary:
            prompt += (
                f"\n\n## 到目前为止的讨论进展快照\n{summary}\n"
                "请在此基础上继续推进，不要重复已充分讨论过的内容。"
            )
        if thinking:
            prompt += f"\n\n## 你在本轮发言前的私下推理（仅你可见，不要在正式发言里提及这个推理过程）\n{thinking}"
        if self.search_result:
            prompt += f"\n\n## 你搜到的最新资料（来自互联网，仅供参考）\n{self.search_result}"
        return prompt

    def _build_messages(self, history: list[dict], topic: str, mode: str, other_names: list[str],
                         user_alias: str = "", phase: str = "", thinking: str = "", summary: str = ""):
        system_prompt = self._build_system_prompt(topic, mode, other_names, phase, thinking, summary)

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

        # Anthropic (and proxies that translate to it) require the conversation to
        # start with a `user` turn and strictly alternate. If the transcript opens
        # with this agent's own words, prepend a neutral user framing so the
        # sequence is valid for every provider.
        if merged and merged[0]["role"] == "assistant":
            merged.insert(0, {"role": "user", "content": f"我们正在讨论：{topic}"})

        if not merged or merged[-1]["role"] == "assistant":
            # Agent opens (or speaks right after itself) — prompt for a substantive opener
            merged.append({"role": "user", "content": "现在轮到你发言。直接抛出你对这个话题的核心判断和理由，开门见山。"})
        else:
            # IMPORTANT: append guidance to the real transcript instead of replacing it,
            # so the agent actually sees everything that was said, not just a snippet.
            last = history[-1] if history else None
            if last and last.get("agent") == user_alias:
                guidance = (
                    f"\n\n———\n【真实用户插话】\n"
                    f"一位真实的人类用户（{user_alias}）刚刚加入并发言。请优先、直接回应 {user_alias} 提出的内容或问题，"
                    f"把ta当作真正参与讨论的人，认真对待。"
                )
            else:
                guidance = (
                    "\n\n———\n"
                    "轮到你发言了。请通读上面整场讨论，然后【推进】它，而不是简单附和上一句——\n"
                    "你可以：挑战某个站不住脚的论点、补上大家忽略的关键角度、用事实或因果机制把某个判断说深，"
                    "或抛出一个更本质的问题。坚持你自己的视角和立场，不要被多数意见同化。"
                )
            merged[-1]["content"] += guidance

        return system_prompt, merged

    async def stream_response(
        self, history: list[dict], topic: str, mode: str, other_names: list[str],
        user_alias: str = "", phase: str = "", thinking: str = "", summary: str = ""
    ) -> AsyncGenerator[str, None]:
        system_prompt, messages = self._build_messages(
            history, topic, mode, other_names, user_alias, phase, thinking, summary
        )
        async for token in _stream_llm(
            self.config.provider, self.config.base_url, self.config.api_key, self.config.model,
            system_prompt, messages,
            max_tokens=self.config.max_tokens, temperature=self.config.temperature,
        ):
            yield token


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
        self.stopped = False
        self.user_queue: asyncio.Queue = asyncio.Queue()
        self.target_agent: str | None = None   # set when user @-mentions an agent
        self.current_phase: str = ""
        self.last_summary: str = ""
        # Pick a name that isn't already taken by any agent
        taken = {a.name for a in self.agents}
        pool  = [n for n in _USER_ALIASES if n not in taken]
        self.user_alias: str = random.choice(pool) if pool else "小明"

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
        if any(m["agent"] == self.user_alias for m in self.history):
            names.append(self.user_alias)
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

    def _get_phase(self, round_idx: int) -> str:
        if not self.config.enable_phases:
            return ""
        n = self.config.max_rounds
        if round_idx < max(1, n // 3):
            return "opening"
        elif round_idx < max(2, (2 * n) // 3):
            return "clash"
        else:
            return "convergence"

    async def _think_for_agent(self, agent: "LLMAgent", other_names: list[str]) -> str:
        """Private chain-of-thought reasoning pass; result is injected into agent's system prompt."""
        recent = self.history[-12:]
        transcript = "\n".join(f'{m["agent"]}：{m["content"][:120]}' for m in recent)
        topic = self.config.topic
        system = (
            f"你是{agent.name}，现在要在关于「{topic}」的讨论中发言。"
            f"以下是你的身份设定：{agent.config.prompt}\n\n"
            "在正式发言前，请先进行私下思考。这个推理过程只有你能看到。"
        )
        user = f"""目前讨论进展：
{transcript}

请用80-120字回答以下问题作为你的私下推理：
1. 当前讨论的核心争议点是什么？
2. 我的立场和最强支撑论据是什么？
3. 对方目前最难被反驳的论点是什么？我该如何应对？
4. 我这次发言应该聚焦攻击或建立哪个具体点？"""
        try:
            return await _llm_call(
                agent.config.provider, agent.config.base_url,
                agent.config.api_key, agent.config.model, system, user
            )
        except Exception:
            return ""

    async def _moderator_check(self, round_idx: int) -> None:
        """After each round, analyze the discussion and optionally inject a moderator question."""
        if round_idx < 1 or not self.agents:
            return
        agent = self.agents[0]
        recent = self.history[-18:]
        transcript = "\n".join(f'{m["agent"]}：{m["content"][:200]}' for m in recent)
        system = "你是经验丰富的研讨主持人。分析讨论健康度，决定是否干预。"
        user = f"""话题：{self.config.topic}

最近的讨论：
{transcript}

用严格标准判断是否出现以下问题（任意一条成立即需干预）：
- 参与者开始互相附和，连续两轮没有出现真正的反驳或新论点
- 同一个核心论点被重复了3次以上却没有任何推进
- 有一个对这个话题明显重要的角度被全程忽略

如果需要干预，输出一个具体、尖锐的主持人提问（一句话，以「❓」开头），用来打破僵局或强制搬出被忽略的角度。
如果讨论健康，只输出：无需干预

只能输出以上两种格式之一，不要其他文字。"""
        try:
            result = (await _llm_call(
                agent.config.provider, agent.config.base_url,
                agent.config.api_key, agent.config.model, system, user
            )).strip()
            if result.startswith("❓"):
                q = result[1:].strip()
                self.history.append({"agent": "主持人", "content": q})
                await self.emit("moderator_question", content=q)
        except Exception:
            pass

    async def _generate_summary(self, round_idx: int) -> None:
        """Emit a mid-discussion progress snapshot and cache it for agent context."""
        if not self.agents:
            return
        agent = self.agents[0]
        msgs = [m for m in self.history if m["agent"] != "主持人"]
        transcript = "\n".join(f'{m["agent"]}：{m["content"][:200]}' for m in msgs)
        system = "你是高效的会议记录员。从讨论中提炼进展，简明扼要，每项不超过2句话。"
        user = f"""话题：{self.config.topic}（第 {round_idx + 1} 轮结束）

讨论记录：
{transcript}

请按以下格式输出进展快照（严格 Markdown，不要额外文字）：

**✅ 已确立的共识**
（具体列出；若暂无则写"暂无"）

**⚔️ 核心争议（仍未解决）**
（列出各方立场及核心分歧）

**🔲 尚未充分讨论的关键角度**
（列出被忽略但对该话题重要的维度）"""
        try:
            result = (await _llm_call(
                agent.config.provider, agent.config.base_url,
                agent.config.api_key, agent.config.model, system, user
            )).strip()
            self.last_summary = result
            await self.emit("summary", round=round_idx + 1, content=result)
        except Exception:
            pass

    async def _drain_user_queue(self):
        """Inject any pending user messages into history; parse @mention to target an agent."""
        while not self.user_queue.empty():
            content = self.user_queue.get_nowait()
            # Parse @AgentName — set target for this round
            m_at = re.match(r'^@(\S+)\s*(.*)', content.strip(), re.DOTALL)
            if m_at:
                mention = m_at.group(1)
                rest    = m_at.group(2).strip()
                matched = next((a for a in self.agents if mention in a.name), None)
                if matched:
                    self.target_agent = matched.name
                    if rest:
                        content = rest
            self.history.append({"agent": self.user_alias, "content": content})
            await self.emit("user_spoke", agent=self.user_alias, content=content,
                            target=self.target_agent)

    async def run(self):
        self.active = True
        await self.emit("user_alias", alias=self.user_alias)

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

            # ── Phase transition ──────────────────────────────────────────────
            new_phase = self._get_phase(round_idx)
            if new_phase and new_phase != self.current_phase:
                self.current_phase = new_phase
                await self.emit("phase_change", phase=new_phase,
                                label=PHASE_LABELS.get(new_phase, ""))

            await self.emit("round", number=round_idx + 1)

            # ── Determine which agents speak this round ────────────────────────
            # When user @-mentioned someone, only that agent responds; then resume normally.
            if self.target_agent:
                agents_this_round = [a for a in self.agents if a.name == self.target_agent]
            else:
                agents_this_round = self.agents

            for agent in agents_this_round:
                if not self.active:
                    break

                await self._drain_user_queue()
                other_names = self._other_names(agent)

                # ── Hidden chain-of-thought ───────────────────────────────────
                thinking = ""
                if self.config.enable_think:
                    await self.emit("deep_thinking", agent=agent.name)
                    thinking = await self._think_for_agent(agent, other_names)

                await self.emit("thinking", agent=agent.name)
                await asyncio.sleep(random.uniform(0.5, 1.5))

                full_text = ""
                try:
                    async for token in agent.stream_response(
                        self.history, self.config.topic, self.config.mode, other_names,
                        self.user_alias, self.current_phase, thinking, self.last_summary
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

            # Clear @mention target after round completes
            self.target_agent = None

            # ── Active moderator ──────────────────────────────────────────────
            if self.config.enable_moderator and self.active:
                await self._moderator_check(round_idx)

            # ── Mid-discussion summary snapshot ───────────────────────────────
            si = self.config.summary_interval
            if si > 0 and self.active and (round_idx + 1) % si == 0:
                await self._generate_summary(round_idx)

            # ── Consensus check ───────────────────────────────────────────────
            if self._check_consensus():
                await self.emit("consensus", message="所有参与者已达成共识，讨论结束。")
                self.active = False
                break

        if self.active:
            await self.emit("max_rounds", message=f"已完成 {self.config.max_rounds} 轮讨论。")

        # Synthesis report — skip only if the user manually aborted
        if not self.stopped:
            await self._generate_report()

        self.active = False
        await self.emit("finished")

    async def _generate_report(self):
        """Synthesize the whole discussion into a structured conclusions report."""
        if not self.agents:
            return
        agent_names = {a.name for a in self.agents}
        agent_msgs = [m for m in self.history if m["agent"] in agent_names]
        if len(agent_msgs) < 2:
            return  # too little substance to be worth summarizing

        cfg = self.agents[0].config
        transcript = "\n".join(
            f'{m["agent"]}：{m["content"]}'
            for m in self.history if m["agent"] != "主持人"
        )
        system = (
            "你是一位顶尖的分析师与研讨主持人，擅长从多人讨论中提炼出真正有价值、有判断力的洞察，"
            "而不是简单罗列每个人说了什么。"
        )
        user = f"""以下是一场关于"{self.config.topic}"的多人讨论记录：

{transcript}

请基于以上讨论，写一份结构化的【结论报告】，帮助读者真正想明白这个问题。用 Markdown，包含这些部分：

## 核心结论
3-5 条最重要的判断，每条先一句话点明，再用一两句说清依据。要有取舍，别和稀泥。

## 已形成的共识
大家真正达成一致、且站得住脚的点。

## 关键分歧
没有解决的争议，以及各方的理由——这往往是最值得继续深挖的地方。

## 被忽略或值得追问的角度
讨论中没充分展开、但其实很关键的点。

## 给你的建议
如果读者要据此做判断或行动，最该重点考虑什么。

要求：直接、犀利、对读者有用；输出你自己的综合判断，而不是中立地复述所有观点。"""

        await self.emit("report_start")
        try:
            async for token in _stream_llm(
                cfg.provider, cfg.base_url, cfg.api_key, cfg.model,
                system, [{"role": "user", "content": user}],
                max_tokens=1800, temperature=0.5,
            ):
                await self.emit("report_token", content=token)
            await self.emit("report_done")
        except Exception as e:
            await self.emit("report_failed", message=str(e))

    def stop(self):
        self.active = False
        self.stopped = True


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
        elif evt["type"] == "report_start":
            result.append(evt)
            i += 1
            chunks: list[str] = []
            while i < len(log) and log[i]["type"] == "report_token":
                chunks.append(log[i]["content"])
                i += 1
            if chunks:
                result.append({"type": "report_token", "content": "".join(chunks)})
        elif evt["type"] in ("token", "message_done", "report_token"):
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

    # Optional: enrich with live web context before generating personas
    search_context = ""
    if req.tavily_api_key:
        try:
            search_context = await _search_tavily(req.topic, req.tavily_api_key)
        except Exception:
            pass  # search failure is non-fatal; fall back to pure LLM knowledge

    search_block = ""
    if search_context:
        search_block = f"\n\n【当前互联网资料】以下是关于该话题的最新背景信息，请参考它来确保角色的立场和争议点贴近现实：\n{search_context}\n"

    system = "你是一个对话设计师。根据话题和模式设计讨论参与者。只输出 JSON，不要有任何额外文字或代码块标记。"
    user_prompt = f"""话题：{req.topic}
模式：{mode_desc}
{search_block}
请设计 3-5 个中文参与者，目标是让这场对话有真正的深度和张力，能帮人把问题想透。关键要求：
- 立场要【真正对立或互补】，不能都是同一类人——刻意安排彼此会冲突的视角（例如：乐观派 vs 怀疑派、理论派 vs 实践派、既得利益方 vs 受影响方、长期主义 vs 务实主义）
- 每个人有不同的职业/年龄/背景，且这个背景能解释ta为什么持这个立场
- 每个人有一种鲜明的思考风格（比如：爱用数据、爱举反例、爱追问本质、爱从历史类比、爱泼冷水）
- 人设要像真实存在的人，有个性、有专业判断，不是空洞的标签
- 在 prompt 里明确写出ta会【反对什么、坚持什么】，这样讨论时ta才不会轻易附和别人
- 如果上方提供了互联网资料，让角色的立场和知识体现最新的真实争议，而不是模型训练数据里的陈旧框架

返回格式（严格 JSON）：
{{"agents": [{{"name": "姓名", "prompt": "你是[姓名]，[年龄]岁，[职业背景]。[性格与思考风格]。在这个话题上，你坚持认为[立场]，并且会反对[对立观点]，因为[理由]。[说话风格]。"}}]}}"""

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
