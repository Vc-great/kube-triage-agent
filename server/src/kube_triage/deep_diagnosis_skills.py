"""Issue #75 S1 STOP：最小 pin-hook PoC 未封闭已消费 pin 的旧 Checkpoint。

仅离线 FakeModel 验证；无 Aegra 注册入口，不得视为可用的 Web/Resume 安全图。
"""

from __future__ import annotations

import hashlib
from importlib.resources import files
from types import MappingProxyType

import yaml
from deepagents.backends.protocol import (
    BackendProtocol,
    DeleteResult,
    EditResult,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import create_file_data, slice_read_response
from deepagents.middleware.skills import SkillsMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Overwrite

from kube_triage import deep_diagnosis_planning as planning

ROOT = "/skills/kubernetes/"
NAMES = ("crashloop-diagnosis", "oom-diagnosis", "imagepull-diagnosis")
PATHS = frozenset(f"{ROOT}{name}/SKILL.md" for name in NAMES)
MODEL_TOOLS = planning.MODEL_TOOLS | {"read_file"}
MAX_DECISIONS = 12
MAX_SKILL_READS = 2
DENIED = "只允许固定内置 Skill 的只读访问。"


class ReadOnlySkillsMiddleware(SkillsMiddleware):
    """仅收窄原生 pin hook；扫描、渲染与工具路由继续继承固定 SDK。"""

    @property
    def name(self):
        return "SkillsMiddleware"

    def before_model(self, state, runtime):
        pins = state.get("pinned_skills", [])
        if not isinstance(pins, list) or pins:
            raise ValueError("本实验禁止 pinned_skills；拒绝正文注入")

    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)


class SkillSnapshot(BackendProtocol):
    """Composite 路由内的固定相对虚拟路径，不访问用户提供的宿主路径。"""

    def __init__(self):
        root = files("kube_triage").joinpath("diagnosis_skills")
        if root.is_symlink() or {p.name for p in root.iterdir()} != set(NAMES):
            raise ValueError("Skill 资源目录不符合固定白名单")
        snapshot = {}
        for name in NAMES:
            directory = root.joinpath(name)
            resource = directory.joinpath("SKILL.md")
            if (directory.is_symlink() or resource.is_symlink()
                    or {p.name for p in directory.iterdir()} != {"SKILL.md"}):
                raise ValueError("拒绝符号链接或额外 Skill 资源")
            data = resource.read_bytes()
            text = data.decode("utf-8")
            if not 0 < len(data) <= 12288 or not 1 <= len(text.splitlines()) <= 100:
                raise ValueError("Skill 大小或行数超限")
            if any(len(line) > 250 for line in text.splitlines()):
                raise ValueError("Skill 单行过长")
            parts = text.split("---", 2)
            meta = yaml.safe_load(parts[1]) if len(parts) == 3 and not parts[0] else None
            if (not isinstance(meta, dict) or set(meta) != {"name", "description"}
                    or meta["name"] != name or not isinstance(meta["description"], str)
                    or not meta["description"].strip()):
                raise ValueError("Skill frontmatter 无效")
            snapshot[f"/{name}/SKILL.md"] = data
        self._snapshot = MappingProxyType(snapshot)
        self.hashes = MappingProxyType({ROOT[:-1] + p: hashlib.sha256(data).hexdigest()
                                      for p, data in snapshot.items()})

    def ls(self, path):
        if path == "/":
            return LsResult(entries=[{"path": f"/{name}", "is_dir": True} for name in NAMES])
        return LsResult(error=DENIED)

    def read(self, file_path, offset=0, limit=100):
        if (file_path not in self._snapshot or type(offset) is not int or not 0 <= offset < 100
                or type(limit) is not int or not 1 <= limit <= 100):
            return ReadResult(error=DENIED)
        return slice_read_response(create_file_data(self._snapshot[file_path].decode()), offset, limit)

    def download_files(self, paths):
        return [FileDownloadResponse(path=p, content=self._snapshot.get(p),
                                    error=None if p in self._snapshot else "permission_denied")
                for p in paths]

    def write(self, file_path, content):
        return WriteResult(error=DENIED)

    def edit(self, file_path, old_string, new_string, replace_all=False):
        return EditResult(error=DENIED)

    def delete(self, file_path):
        return DeleteResult(error=DENIED)

    def upload_files(self, files):
        return [FileUploadResponse(path=p, error="permission_denied") for p, _ in files]

    def glob(self, pattern, path=None):
        return GlobResult(error=DENIED)

    def grep(self, pattern, path=None, glob=None, *, max_count=None):
        return GrepResult(error=DENIED)


class SkillsBoundary(planning.PlanningBoundary):
    """在 SDK 原生加载前清理缓存，在原生 pin/模型注入前验证来源。"""

    def __init__(self, metadata):
        self._metadata = metadata

    async def abefore_agent(self, state, runtime):
        update = await super().abefore_agent(state, runtime)
        return {**update, "skills_metadata": None, "pinned_skills": Overwrite([]),
                "skills_load_errors": [], "_skill_tools_disclosed": {}}

    async def abefore_model(self, state, runtime):
        if (state.get("skills_metadata") != self._metadata or state.get("pinned_skills")
                or state.get("skills_load_errors") or state.get("_skill_tools_disclosed")):
            raise ValueError("Skill 来源或缓存校验失败；拒绝模型调用")

    async def awrap_model_call(self, request, handler):
        # Known S1 STOP: a legacy checkpoint past the pin hook can already
        # contain pinned HumanMessages with an empty pin field. The minimal
        # replacement does not authenticate this history. Do not expose it.
        await self.abefore_model(request.state, request.runtime)
        turn = planning._turn(request.state.get("messages", []))
        if sum(isinstance(m, AIMessage) for m in turn) >= MAX_DECISIONS:
            return AIMessage(content="本轮模型决策预算已用尽；当前状态与根因未核验。")
        tools = [t for t in request.tools if t.name in MODEL_TOOLS]
        if len(tools) != 6 or {t.name for t in tools} != MODEL_TOOLS:
            raise RuntimeError("Skills Graph 模型工具清单必须恰为六项；检查独立 Profile")
        return await handler(request.override(tools=tools))

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        if call.get("name") != "read_file":
            return await super().awrap_tool_call(request, handler)
        ident = call.get("id") or ""

        def deny():
            return ToolMessage(content="Skill 路径、参数、ID 或两次读取预算无效；拒绝执行。",
                               name="read_file", tool_call_id=ident, status="error")

        turn = planning._turn(request.state.get("messages", []))
        latest = next((m for m in reversed(turn) if isinstance(m, AIMessage)), None)
        message, matched = planning._unique_call(turn, ident)
        if latest is None or message is not latest or matched != call:
            return deny()
        calls = [c for m in turn if isinstance(m, AIMessage) for c in m.tool_calls
                 if c.get("name") == "read_file"]
        if next((i for i, c in enumerate(calls) if c is matched), MAX_SKILL_READS) >= MAX_SKILL_READS:
            return deny()
        args = call.get("args")
        if (not isinstance(args, dict) or set(args) - {"file_path", "offset", "limit"}
                or args.get("file_path") not in PATHS
                or type(args.get("offset", 0)) is not int or not 0 <= args.get("offset", 0) < 100
                or type(args.get("limit", 100)) is not int or not 1 <= args.get("limit", 100) <= 100):
            return deny()
        # Native read_file defaults to 2000; use our documented bounded default.
        changed = {**call, "args": {"offset": 0, "limit": 100, **args}}
        result = await handler(request.override(tool_call=changed))
        if not isinstance(result, ToolMessage) or result.tool_call_id != ident:
            return deny()
        return result


def build_graph(model, *, checkpointer=None):
    """S1 STOP：来源边界未实现，公开入口始终在 SDK 装配前失败关闭。

    测试装配在 server/tests/skills_probe_helpers.py；不通过拒绝所有恢复
    宣称 Gate PASS。此入口不返回可被 copy/with_config 注入 Checkpointer 的图。
    """
    raise NotImplementedError("S1 STOP：Checkpoint 来源未封闭；Skills Graph 暂不可构建")
