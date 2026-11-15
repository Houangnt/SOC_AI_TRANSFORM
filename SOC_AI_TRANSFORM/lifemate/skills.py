"""Load business instructions and route Vietnamese requests with the configured LLM."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


def allowed_tools(context: dict) -> set[str]:
    apps = context.get("installed_apps")
    if not isinstance(apps, dict):
        raise TypeError("context.installed_apps must be an object")
    names = {"sys.ask_missing_info"}
    for app in apps.values():
        if not isinstance(app, dict) or not isinstance(app.get("tools"), list):
            raise TypeError("Each installed app must declare its tools list")
        for name in app["tools"]:
            if not isinstance(name, str):
                raise TypeError("Installed tool names must be strings")
            names.add(name)
    return names


@dataclass(frozen=True)
class Selection:
    skills: tuple[str, ...]
    rules: tuple[str, ...] = ()


class BusinessSkills:
    def __init__(self, root: Path | None = None):
        configured = os.getenv("SOC_AI_TRANSFORM_BUSINESS_SKILLS_ROOT")
        self.root = (root or (Path(configured) if configured else
                             Path(__file__).parent / "business_skills")).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(
                "Set SOC_AI_TRANSFORM_BUSINESS_SKILLS_ROOT to the provided business_skills folder"
            )
        self.architecture = json.loads(self.read("architecture.json"))
        index = json.loads(self.read("business_index.json"))
        self.index = {item["skill"]: item for item in index}
        self.businesses = {item["skill"]: item for item in self.architecture["businesses"]}
        if len(self.index) != len(index) or self.index.keys() != self.businesses.keys():
            raise ValueError("Business index and architecture do not agree")

    def read(self, relative: str) -> str:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Business reference escapes the skill package")
        if path.relative_to(self.root).parts[0] not in {
            "skills", "rules", "architecture.json", "business_index.json",
        }:
            raise ValueError("Only runtime skill references may be loaded")
        return path.read_text(encoding="utf-8")

    def candidates(self, context: dict | None = None) -> list[dict]:
        allowed = allowed_tools(context) if context is not None else None
        return [{key: item[key] for key in ("skill", "description", "primary_actions")}
                for item in self.index.values()
                if allowed is None or allowed.intersection(item["primary_actions"])]

    def validate(self, selection: Selection, context: dict | None = None) -> Selection:
        candidates = {item["skill"] for item in self.candidates(context)}
        if any(name not in candidates for name in selection.skills):
            raise ValueError("Router selected an unknown or unavailable business")
        permitted = {rule for name in selection.skills
                     for rule in self.businesses[name]["shared_rules"]}
        if any(rule not in permitted for rule in selection.rules):
            raise ValueError("Router selected an inapplicable rule")
        return Selection(tuple(dict.fromkeys(selection.skills)),
                         tuple(dict.fromkeys(selection.rules)))

    def select(self, client, model: str, text: str, context: dict | None = None,
               history: list | None = None) -> Selection:
        candidates = self.candidates(context)
        if not candidates:
            return Selection(())
        prompt = (
            "Bạn chọn nghiệp vụ LifeMate, không thực thi hay lập lời giải. "
            "Đọc yêu cầu cuối cùng cùng context và history; giữ mục tiêu độc lập, "
            "sửa lời, phủ định và điều kiện. History đã thực thi, không chọn để phát lại. "
            "Chọn TẤT CẢ nghiệp vụ cần thiết, kể cả nghiệp vụ đọc để kiểm tra điều kiện; "
            "không giới hạn hai skill. Tra cứu phụ có trong quy trình nghiệp vụ chính "
            "không cần chọn thành nghiệp vụ riêng. Không dùng được app thì không chọn. "
            "Yêu cầu hợp lệ nhưng thiếu thông tin vẫn chọn nghiệp vụ để hỏi thêm. "
            "Chỉ trả JSON {\"skills\": [id], \"rules\": [path]}. "
            "Chỉ trò chuyện, rút lại yêu cầu chưa làm hoặc ngoài phạm vi: skills=[] và rules=[]. "
            "Rules chỉ chọn từ shared_rules của các skill đã chọn khi cần dùng.\n"
            + json.dumps({"businesses": candidates,
                          "shared_rules": {item["skill"]: self.businesses[item["skill"]]["shared_rules"]
                                           for item in candidates}}, ensure_ascii=False)
        )
        response = client.messages.create(
            model=model, max_tokens=2048, system=prompt,
            messages=[{"role": "user", "content": json.dumps(
                {"text": text, "context": context, "history": history or []},
                ensure_ascii=False)}],
        )
        raw = "".join(block.text for block in response.content
                      if getattr(block, "type", None) == "text").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Business router did not return valid JSON") from exc
        if not isinstance(data, dict) or any(
            not isinstance(data.get(key), list)
            or any(not isinstance(value, str) for value in data[key])
            for key in ("skills", "rules")
        ):
            raise ValueError("Business router must return skills and rules as string lists")
        return self.validate(Selection(tuple(data["skills"]), tuple(data["rules"])), context)

    def instructions(self, selection: Selection, context: dict | None = None) -> str:
        selection = self.validate(selection, context)
        paths = [self.architecture["orchestration"]]
        paths.extend(self.index[name]["path"] for name in selection.skills)
        core = ("rules/thuc-thi-tool.md", "rules/doi-tuong.md", "rules/hop-dong-ke-hoach.md")
        paths.extend(rule for rule in core if rule in self.architecture["shared_rules"])
        paths.extend(selection.rules)
        return "\n\n".join(f"### {path}\n{self.read(path)}"
                            for path in dict.fromkeys(paths))
