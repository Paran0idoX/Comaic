"""工作台人工验收 mock：仅使用内存数据，不读取真实数据库，不调用生图或 LLM。"""

import argparse
import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NOW = "2026-10-01T09:00:00Z"
STAMP = dict(created_at=NOW, updated_at=NOW)
PROJECTS = [dict(id=1, title="雾港故事 · 验收项目 A", **STAMP),
            dict(id=2, title="新故事 · 空项目 B", **STAMP)]
CHARACTER = dict(id=11, outline_version_id=21, character_key="hero", name="林夏",
                 visual_type="stylized_human", role="修理师", background="海港旧城区",
                 appearance="短发，明亮眼睛",
                 negative_constraints="保持人物年龄", default_hairstyle="黑色短发",
                 default_clothing="蓝色工作服", default_accessories="工具包",
                 default_color_palette="蓝色、橙色", **STAMP)
OUTLINE = dict(version_id=21, version_no=1, outline="# 雾港故事\n林夏寻找失踪父亲留下的机械钥匙。",
               status="active", confirmed_at=NOW, characters=[CHARACTER], created_at=NOW)
TASK = dict(id=101, project_id=1, outline_version_id=21, status="succeeded", mode="batch",
            total_pages=2, target_page_no=None, user_requirement=None, section_plan=None,
            error_message=None, **STAMP)
SCENE = dict(id=301, task_id=101, scene_key="harbor", name="雾港维修店", location_type="室内",
             time_of_day="清晨", lighting="暖灯", weather="薄雾", environment_details="旧机器与工具架",
             color_palette="暖橙、灰蓝", negative_constraints="无现代霓虹",
             selected_visual_version_id=501, reference_subject_id=51, **STAMP)
SCRIPT_CHARACTER = dict(id=401, task_id=101, section_id=201, section_no=1,
                        outline_character_id=11, outfit_variant_id=601, character_key="hero",
                        name="林夏", section_role="主角", current_hairstyle="黑色短发",
                        current_clothing="蓝色工作服", current_accessories="工具包", current_state="健康",
                        emotion="好奇", temporary_changes="",
                        negative_constraints="人物年龄不变", outline_character=CHARACTER, **STAMP)
PAGES = [dict(id=1000+n, project_id=1, task_id=101, section_id=201, section_no=1, scene_id=301,
              scene_key="harbor", character_keys=["hero"], page_no=n,
              summary=f"第 {n} 页：林夏发现机器发出奇怪的声音", characters="林夏",
              clothing="蓝色工作服", scene="雾港维修店", composition="三格漫画", character_action="检查齿轮",
              dialogue="这声音是谁留下的？", status="spec_ready", script_review_status="passed",
              script_review_error=None, **STAMP) for n in (1, 2)]
OUTFITS = [dict(id=601, project_id=1, outline_character_id=11, key="work-outfit", version=1,
                name="维修工作服", garment_components=["蓝色外套", "长裤"], layer_order=["内衫", "外套"],
                colors=["蓝色"], materials=["棉布"], patterns=["无图案"], accessories=["工具包"],
                trigger_tokens=["blue workwear"], negative_constraints="不要改为裙装", status="draft",
                approved_at=None, **STAMP)]
STYLES = [dict(id=701, project_id=1, key="ink", version=1, name="温暖水彩漫画",
               positive_tag="watercolor, comic", negative_tag="photorealistic",
               positive_natural_language="柔和水彩与清晰线条", negative_natural_language="避免写实照片质感",
               color_palette=["暖橙", "蓝色"], lighting="温暖漫射光", status="approved",
               approved_at=NOW, **STAMP)]
SCENE_VERSIONS = [dict(id=501, project_id=1, script_scene_id=301, version=1, landmarks=["圆窗", "工作台"],
                      spatial_relations={"圆窗": "在工作台左侧"}, camera_presets=["平视中景"],
                      object_states={"机器": "停机"}, color_palette=["暖橙", "灰蓝"],
                      lighting_state={"主光": "左侧窗光"}, status="draft", approved_at=None, **STAMP)]
ASSETS = []
SUBJECTS = [dict(id=51, project_id=1, entity_type="scene", key="harbor", name="雾港维修店",
                 description="圆窗、旧机器与木制工作台", negative_constraints="不要现代霓虹", **STAMP),
            dict(id=52, project_id=1, entity_type="prop", key="mechanical-key", name="机械钥匙",
                 description="黄铜齿轮形钥匙", negative_constraints="保持齿轮数量", **STAMP)]
VISUAL_PROFILES = {}


def visual_profiles(project_id, data):
    category = data["entity_type"]
    identities = [("character", data["entity_id"])] if category == "character" else [("scene_subject" if category == "scene" else "prop_subject", data["reference_subject_id"])]
    if data.get("outfit_variant_id"): identities.append(("outfit", data["outfit_variant_id"]))
    if category == "scene" and data.get("entity_id"): identities.append(("scene_version", data["entity_id"]))
    profiles = []
    for kind, owner_id in identities:
        key = (project_id, kind, owner_id)
        if key not in VISUAL_PROFILES or data.get("refresh_visual_profiles"):
            previous = VISUAL_PROFILES.get(key)
            roles = ["identity_face", "identity_full_body", "identity_side", "identity_back"] if kind in ("character", "outfit") else ["prop_reference" if kind == "prop_subject" else "scene_master"]
            texts = dict(character="Black hair.", outfit="Blue workwear.", scene_subject="Brick walls and a round window.", scene_version="Warm lamps at night.", prop_subject="A closed bronze watch case.")
            alternatives = [dict(natural=texts[kind], tags=[texts[kind].strip(".").lower()])]
            if kind == "character": alternatives.append(dict(natural="Cool brown hair.", tags=["cool brown hair"]))
            facts = [dict(kind="head" if kind == "character" else "clothing" if kind == "outfit" else "environment" if kind.startswith("scene") else "shape",
                attribute="hair_color" if kind == "character" else kind, polarity="required", must_keep=True,
                source_field="default_hairstyle" if kind == "character" else "description", source_excerpt="黑或冷褐发" if kind == "character" else texts[kind],
                views=roles if kind != "outfit" else roles[1:], options=alternatives, selected=0, default_index=0,
                default_is_explicit=False, selection_reason="No explicit default; use the first candidate.")]
            VISUAL_PROFILES[key] = dict(id=previous["id"] if previous else 7000+len(VISUAL_PROFILES), project_id=project_id,
                kind=kind, owner_id=owner_id, revision=previous["revision"]+1 if previous else 1, source_hash="a"*64,
                format_version=1, data=dict(human=kind == "character", facts=facts))
        profiles.append(VISUAL_PROFILES[key])
    return profiles


REFERENCE_TASKS = []
REFERENCE_ROLES = {"character": ["identity_face", "identity_full_body", "identity_side", "identity_back"],
                   "scene": ["scene_master"], "prop": ["prop_reference"]}
REF_TASK = dict(id=801, project_id=1, outline_character_id=11, character_name="林夏", tool_id=1,
                tool_name="模拟生图工具", style_profile_id=701, status="succeeded", candidate_count=1,
                prompt_type="natural_language", prompts={}, progress={"completed": 3, "failed": 0, "total": 3},
                approved_candidate_index=None, error_code=None, error_message=None, heartbeat_at=NOW,
                finished_at=NOW, candidates=[], **STAMP)
REFERENCE_TASKS.append(dict(REF_TASK, entity_type="character", entity_id=11, entity_key="hero", reference_subject_id=None,
                           outfit_variant_id=None, selected_roles=REFERENCE_ROLES["character"][:3], source_asset_ids=[], subject_name="林夏"))
TOOL = dict(id=1, name="模拟生图工具", provider="openai_images_compatible", prompt_type="natural_language",
            description="验收用，不会向外部发送请求", is_default=True, capabilities={"features": ["txt2img", "seed"]},
            bindings={}, api_base_url="http://mock.invalid", endpoint_path="/images/generations",
            api_key=None, model="mock", size="1024x1024", response_format="b64_json",
            comfy_base_url=None, workflow_json=None, positive_node_id=None, positive_input_name=None,
            negative_node_id=None, negative_input_name=None, seed_node_id=None, seed_input_name=None,
            seed_field_name=None, negative_prompt_field_name=None, extra_body_json=None, **STAMP)
BATCH = dict(id=901, project_id=1, page_id=None, script_task_id=101, tool_preset_id=1, parent_task_id=None,
             task_kind="batch", generation_mode="preview", seed_strategy="shared_candidate", candidate_count=1,
             comfy_prompt_id=None, status="succeeded", batch_size=1, error_message=None, **STAMP)
COMPILATION = dict(id=1001, task_id=101, continuity_compilation_id=1101, source_hash="mock", status="succeeded",
                   generation_mode="preview", total_pages=2, completed_pages=2, total_specs=6, completed_specs=6,
                   failed_pages=[], error_code=None, error_message=None, **STAMP)
PRESETS = [dict(id=i, name=name, kind=kind, content="模拟规划规则", tag_content="bad anatomy",
                natural_language_content="避免人物数量错误", description="验收配置", is_default=True, **STAMP)
           for i, name, kind in [(1, "画面规划规则", "shot_planner_system_prompt"), (2, "避免内容", "negative_prompt")]]
# 内存图片是普通测试图；上传仅核对 multipart 的人物归属和用途，不保存到生产 outputs。
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Z1kAAAAASUVORK5CYII=")


def planned_references():
    """仅展示本页人物和明确绑定的场景，避免模拟页面把无关新条目当作实际选图。"""
    approved = [asset for asset in ASSETS if asset["project_id"] == 1 and asset["status"] == "approved"]
    selected = []
    faces = [asset for asset in approved if asset["entity_type"] == "character" and asset.get("entity_id") == 11 and asset["role"] == "identity_face"]
    if faces:
        selected.append((faces[0], CHARACTER, "identity", "reference.selection.view_match"))
    subject = next((item for item in SUBJECTS if item["id"] == SCENE["reference_subject_id"]), None)
    scene_assets = [asset for asset in approved if asset["entity_type"] == "scene" and asset.get("reference_subject_id") == SCENE["reference_subject_id"] and asset.get("entity_id") in (None, SCENE["selected_visual_version_id"])]
    if scene_assets and subject:
        asset = next((item for item in scene_assets if item.get("entity_id") == SCENE["selected_visual_version_id"]), scene_assets[0])
        selected.append((asset, subject, "scene", "reference.selection.scene_version" if asset.get("entity_id") else "reference.selection.scene_subject"))
    return {"schema_version": 1, "items": [dict(asset, asset_id=asset["id"], order=index,
        owner={"category": asset["entity_type"], "id": owner["id"], "key": owner.get("character_key") or owner["key"], "name": owner["name"]},
        purpose=purpose, reason="Use the confirmed reference for this page", reason_code=reason_code, is_primary=True)
        for index, (asset, owner, purpose, reason_code) in enumerate(selected, 1)], "omitted": [], "fallbacks": []}


def mock_comic_image(page_id):
    return dict(id=page_id+9000, page_id=page_id, generation_run_id=1901, artifact_index=1,
        image_url="/api/visual-bible/assets/1200/file", local_path="mock.png", seed=1,
        workflow_name=TOOL["name"], prompt="模拟结果", negative_prompt="", score=None, sha256="mock",
        width=1, height=1, is_selected=False, created_at=NOW)


def set_reference_asset_status(asset, status):
    """离线模拟同用途同范围互斥确认；原图与转存关联保留以支持重新确认。"""
    def same_slot(peer):
        if any(peer.get(key) != asset.get(key) for key in ("project_id", "entity_type", "role", "entity_id")):
            return False
        if asset["entity_type"] == "character":
            return asset["role"] == "identity_face" or peer.get("outfit_variant_id") == asset.get("outfit_variant_id")
        return peer.get("reference_subject_id") == asset.get("reference_subject_id")
    if status == "approved":
        for peer in ASSETS:
            if peer["id"] != asset["id"] and peer["status"] == "approved" and same_slot(peer):
                peer.update(status="draft", approved_at=None)
    asset.update(status=status, approved_at=NOW if status == "approved" else None)
    by_id = {item["id"]: item for item in ASSETS}
    for task in REFERENCE_TASKS:
        for candidate in task["candidates"]:
            for run in candidate["roles"].values():
                for image in run["images"]:
                    target = by_id.get(image.get("promoted_asset_id"))
                    image["promoted_asset_status"] = target["status"] if target else None
                run["review_status"] = "approved" if any(image["promoted_asset_status"] == "approved" for image in run["images"]) else "draft"


def create_reference_mock_task(project_id, data):
    """单张和批量验收共用内存候选，不访问真实 Provider。"""
    subject = next((item for item in SUBJECTS if item["id"] == data.get("reference_subject_id")), None)
    name = subject["name"] if subject else CHARACTER["name"]
    sources = data.get("source_asset_ids", []) if data.get("source_mode") == "manual" else []
    task_id = 1800+len(REFERENCE_TASKS)
    candidates = []
    for index in range(1, data["candidate_count"]+1):
        roles = {}
        for offset, role in enumerate(data["roles"]):
            image_id = task_id*100+index*10+offset
            image = dict(id=image_id, artifact_index=0, image_url=f"/api/reference-images/images/{image_id}/file",
                         sha256="mock", width=1, height=1, promoted_asset_id=None)
            roles[role] = dict(id=image_id, candidate_index=index, role=role, seed=index, provider="openai_images_compatible",
                               prompt_type="natural_language", positive_prompt=data["prompts"][role]["positive"], negative_prompt=data["prompts"][role]["negative"],
                               status="succeeded", review_status="draft", seed_applied=False, external_request_id="mock", degradations=[], error_code=None,
                               images=[image], primary_image=image, finished_at=NOW, **STAMP)
        candidates.append(dict(candidate_index=index, seed=index, status="succeeded", roles=roles))
    total = len(data["roles"])*data["candidate_count"]
    task = dict(id=task_id, project_id=project_id, entity_type=data["entity_type"], entity_id=data.get("entity_id"),
                entity_key=subject["key"] if subject else "hero", reference_subject_id=data.get("reference_subject_id"),
                outfit_variant_id=data.get("outfit_variant_id"), outline_character_id=data.get("entity_id") if data["entity_type"] == "character" else None,
                subject_name=name, tool_preset_id=1, tool_name=TOOL["name"], status="succeeded", candidate_count=data["candidate_count"],
                selected_roles=data["roles"], source_asset_ids=sources, prompt_type="natural_language", prompts=data["prompts"],
                progress=dict(completed=total, failed=0, total=total), error_code=None, candidates=candidates, **STAMP)
    REFERENCE_TASKS.insert(0, task)
    return task


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, data, status=200):
        content = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def prepare_reference_preview(self, project_id, data):
        """模拟后端线程中的摘要准备，保持真实批量 SSE 协议。"""
        time.sleep(getattr(self.server, "prompt_delay", 0))
        if data["entity_type"] == "prop" and getattr(self.server, "fail_prop_once", False):
            self.server.fail_prop_once = False
            raise ValueError("mock extraction failure")
        profiles = visual_profiles(project_id, data)
        prompts = {role: dict(positive="One " + role.replace("_", " ") + " reference. " + " ".join(
            fact["options"][fact["selected"]]["natural"] for profile in profiles for fact in profile["data"]["facts"] if role in fact["views"]),
            negative="Additional subjects, collage, captions") for role in data["roles"]}
        sources = data.get("source_asset_ids", []) if data.get("source_mode") == "manual" else []
        return dict(prompt_type="natural_language", prompts=prompts, source_asset_ids=sources, visual_profiles=profiles)

    def stream_reference_previews(self, project_id, items):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()
        events = Queue()
        def emit(event, payload):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        def prepare(index, item):
            events.put(dict(project_id=project_id, index=index, status="running"))
            try:
                events.put(dict(project_id=project_id, index=index, status="succeeded", preview=self.prepare_reference_preview(project_id, item)))
            except ValueError:
                events.put(dict(project_id=project_id, index=index, status="failed",
                    error={"code": "reference.profile_extraction_failed", "message": "模拟提炼失败，请重试。"}))
        with ThreadPoolExecutor(max_workers=5) as executor:
            try:
                emit("accepted", dict(project_id=project_id, total=len(items), concurrency=5))
                futures = [executor.submit(prepare, index, item) for index, item in enumerate(items)]
                completed = failed = 0
                while completed + failed < len(items):
                    event = events.get()
                    completed += event["status"] == "succeeded"
                    failed += event["status"] == "failed"
                    emit("item", event)
                emit("done", dict(project_id=project_id, total=len(items), completed=completed, failed=failed))
            except (BrokenPipeError, ConnectionResetError):
                for future in futures: future.cancel()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/reference-images/catalog":
            return self.send({"categories": [dict(entity_type=kind, roles=[dict(role=role, label_key=f"visualBible.roleLabels.{role}") for role in roles])
                                             for kind, roles in REFERENCE_ROLES.items()]})
        if match := re.fullmatch(r"/api/reference-images/projects/(\d+)/subjects", path):
            return self.send({"items": [item for item in SUBJECTS if item["project_id"] == int(match[1])]})
        if match := re.fullmatch(r"/api/reference-images/projects/(\d+)/tasks", path):
            return self.send({"items": [item for item in REFERENCE_TASKS if item["project_id"] == int(match[1])]})
        if match := re.fullmatch(r"/api/reference-images/tasks/(\d+)", path):
            task = next((item for item in REFERENCE_TASKS if item["id"] == int(match[1])), None)
            if task: return self.send(task)
            if match[1] == "801":
                return self.send(dict(REF_TASK, entity_type="character", entity_id=11, entity_key="hero", reference_subject_id=None,
                                      outfit_variant_id=None, selected_roles=REFERENCE_ROLES["character"][:3], source_asset_ids=[], subject_name="林夏"))
        if path == "/api/projects": return self.send({"items": PROJECTS})
        if path == "/api/image-generation/tools": return self.send({"items": [TOOL]})
        if path == "/api/image-specs/presets": return self.send(PRESETS)
        if path == "/api/settings/app": return self.send({"script_section_max_concurrency": 2})
        if path == "/api/settings/llm": return self.send({"items": [], "active_config_id": None})
        if path == "/api/settings/llm/providers":
            return self.send([dict(value="openai_compatible", label="OpenAI Compatible", requires_base_url=True, model_prefixes=[]),
                              dict(value="deepseek", label="DeepSeek", requires_base_url=False, model_prefixes=[])])
        if path == "/api/settings/consistency-evaluation":
            return self.send(dict(cids_cross_min=.5, cids_self_min=.5, csd_cross_min=.5, csd_self_min=.5, occm_min=.5, copy_paste_max=.5,
                metric_version="mock", runtime=dict(ready=False, python_executable="mock-python", source_root="mock-source", pretrain_root="mock-weights",
                    missing_modules=[], missing_source_files=[], missing_weights=[], invalid_source_files=[], invalid_weights=[],
                    onnx_cuda_available=False, arcface_provider="cpu", torch_version=None, cuda_available=False, cuda_device=None, detail=None, metric_version="mock")))
        if (path.startswith("/api/visual-bible/assets/") or path.startswith("/api/reference-images/images/")) and path.endswith("/file"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            return self.wfile.write(PNG)
        if match := re.fullmatch(r"/api/projects/(\d+)/script-tasks", path):
            return self.send([TASK] if match[1] == "1" else [])
        if match := re.fullmatch(r"/api/projects/(\d+)/pages", path):
            return self.send({"items": PAGES if match[1] == "1" else []})
        if path == "/api/scripts/tasks/101": return self.send(TASK)
        if match := re.fullmatch(r"/api/scripts/tasks/(\d+)/(pages|sections|characters|scenes)", path):
            sections = [dict(id=201, task_id=101, section_no=1, page_start=1, page_end=2, title="机器的秘密",
                             description="林夏发现线索", status="completed", error_message=None, pages=PAGES, **STAMP)]
            data = {"pages": PAGES, "sections": sections, "characters": [SCRIPT_CHARACTER], "scenes": [SCENE]}
            return self.send({"items": data[match[2]] if match[1] == "101" else []})
        if match := re.fullmatch(r"/api/visual-bible/projects/(\d+)/(outfits|styles|scene-versions|assets)", path):
            data = {"outfits": OUTFITS, "styles": STYLES, "scene-versions": SCENE_VERSIONS, "assets": ASSETS}
            if match[2] == "assets": return self.send([asset for asset in ASSETS if asset["project_id"] == int(match[1])])
            return self.send(data[match[2]] if match[1] == "1" else [])
        if match := re.fullmatch(r"/api/character-references/projects/(\d+)/outline-characters", path):
            return self.send({"items": [CHARACTER] if match[1] == "1" else []})
        if path == "/api/character-references/outline-versions/21/characters": return self.send({"items": [CHARACTER]})
        if path == "/api/character-references/outline-characters/11/tasks": return self.send({"items": [REF_TASK]})
        if path == "/api/character-references/tasks/801": return self.send(REF_TASK)
        if match := re.fullmatch(r"/api/image-specs/script-tasks/(\d+)(/(continuity|compilations))?", path):
            if match[3] == "compilations": return self.send([COMPILATION])
            if match[3] == "continuity":
                snapshots = [dict(id=page["id"], page_id=page["id"], page_no=page["page_no"],
                                  state={"characters": [{"character_key": "lin_xia", "name": "林夏"}], "scene": {"scene_key": "workshop"}},
                                  state_hash="mock-page", warnings=[], created_at=NOW) for page in PAGES]
                return self.send([
                    dict(id=1101, task_id=101, source_hash="mock", status="succeeded", events=[], snapshots=snapshots, created_at=NOW),
                    dict(id=1100, task_id=101, source_hash="legacy", status="succeeded",
                         events=[dict(id=1, page_id=PAGES[0]["id"], page_no=1, sequence_no=1, event_type="set_outfit",
                                      target_type="character", target_key="lin_xia", timing="before_page", payload={"description": "旧版服装"}, source="manual")],
                         snapshots=snapshots[:1], created_at=NOW),
                ])
            return self.send([dict(id=2000+idx*3+i, page_id=page["id"], page_no=page["page_no"], snapshot_id=1,
                                   shot_plan_id=1, prompt_type=prompt_type, generation_mode="preview", spec={"reference_plan": planned_references()},
                                   positive_prompt="林夏在维修店检查机器，水彩漫画", negative_prompt="避免错误人物数量",
                                   required_capabilities=["txt2img"], warnings=[], source_hash="mock", spec_hash="mock",
                                   compiler_key="mock", compiler_version="mock", created_at=NOW)
                              for idx, page in enumerate(PAGES) for i, prompt_type in enumerate(["tag", "natural_language", "hybrid"])])
        if match := re.fullmatch(r"/api/image-generation/script-tasks/(\d+)/(batches|pages)", path):
            if match[2] == "batches": return self.send({"items": [BATCH]})
            return self.send({"items": [dict(page_id=p["id"], page_no=p["page_no"], prompt_type="natural_language",
                                            positive_prompt="林夏检查机器", status="spec_ready", selected_image_id=None,
                                            latest_spec_id=2000, spec_warnings=[], completed_candidates=1 if planned_references()["items"] else 0,
                                            images=[mock_comic_image(p["id"])] if planned_references()["items"] else []) for p in PAGES]})
        if path == "/api/image-generation/runs/1901":
            # 模拟工具是纯文字接口，计划图不会谎称已发送；运行明确展示省略原因。
            inputs = {"schema_version": 1, "order_known": True, "capacity": 0, "items": [],
                      "omitted": [dict(item, reason_code="reference.capacity_exceeded") for item in planned_references()["items"]]}
            return self.send(dict(id=1901, generation_task_id=901, batch_task_id=901, page_id=1001,
                image_spec_id=2000, tool_preset_id=1, provider=TOOL["provider"], prompt_type=TOOL["prompt_type"],
                candidate_index=1, seed=1, seed_applied=False, seed_strategy="per_page", generation_mode="preview",
                status="succeeded", external_request_id="mock-only", workflow=None, workflow_hash=None, bindings={},
                resolved_assets=[], degradations=[], applied_spec={"reference_inputs": inputs,
                "prompt": {"positive": "模拟文字提示词；该工具未发送参考图片", "negative": ""}},
                error_code=None, error_message=None, finished_at=NOW, **STAMP))
        if path.endswith("/gate"): return self.send({"passed": False, "script_task_id": 101, "reason_codes": []})
        if path.endswith("/readiness"):
            return self.send({"ready": False, "batch_task_id": 901, "metric_version": "mock",
                              "errors": [], "warnings": [], "runtime": None, "track_count": 0,
                              "incomplete_tracks": [], "source_hash": "mock", "reference_baseline": None})
        if path.startswith("/api/consistency-evaluations/") and path.endswith("/tasks"): return self.send({"items": []})
        return self.send({"code": "common.not_found", "message": "Mock endpoint not configured"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if path.endswith("/assets/upload"):
            mime = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
            fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                      for part in mime.iter_parts()}
            project_id = int(path.split("/")[4])
            asset = dict(id=1200+len(ASSETS), project_id=project_id, entity_type=fields["entity_type"].decode(),
                         entity_id=int(fields["entity_id"]) if fields.get("entity_id") else None, entity_key=None,
                         reference_subject_id=int(fields["reference_subject_id"]) if fields.get("reference_subject_id") else None,
                         outfit_variant_id=int(fields["outfit_variant_id"]) if fields.get("outfit_variant_id") else None, role=fields["role"].decode(),
                         storage_kind="local_file", local_path="mock.png", renderer_locator=None, mime_type="image/png",
                         sha256="mock", width=1, height=1, version=1, status="draft", source="upload",
                         source_image_id=None, crop_metadata={}, mask_asset_id=None, approved_at=None, **STAMP)
            ASSETS.insert(0, asset)
            return self.send(asset)
        data = json.loads(raw or "{}")
        if match := re.fullmatch(r"/api/reference-images/projects/(\d+)/subjects", path):
            subject = dict(data, id=100+len(SUBJECTS), project_id=int(match[1]), key=data.get("key") or f"subject-{len(SUBJECTS)}", **STAMP)
            SUBJECTS.append(subject)
            return self.send(subject)
        if match := re.fullmatch(r"/api/reference-images/projects/(\d+)/tasks/batch", path):
            return self.send({"items": [create_reference_mock_task(int(match[1]), item) for item in data["items"]]})
        if match := re.fullmatch(r"/api/reference-images/projects/(\d+)/prompt-preview/batch", path):
            return self.stream_reference_previews(int(match[1]), data["items"])
        if match := re.fullmatch(r"/api/reference-images/projects/(\d+)/(prompt-preview|tasks)", path):
            project_id = int(match[1])
            if match[2] == "prompt-preview":
                try:
                    return self.send(self.prepare_reference_preview(project_id, data))
                except ValueError:
                    return self.send({"detail": {"code": "reference.profile_extraction_failed", "message": "模拟提炼失败，请重试。"}}, 422)
            return self.send(create_reference_mock_task(project_id, data))
        if match := re.fullmatch(r"/api/reference-images/images/(\d+)/approve", path):
            image_id = int(match[1])
            for task in REFERENCE_TASKS:
                for candidate in task["candidates"]:
                    for role, run in candidate["roles"].items():
                        image = next((item for item in run["images"] if item["id"] == image_id), None)
                        if image:
                            if image["promoted_asset_id"]:
                                asset = next(item for item in ASSETS if item["id"] == image["promoted_asset_id"])
                                set_reference_asset_status(asset, "approved")
                                return self.send(asset)
                            asset = dict(id=1200+len(ASSETS), project_id=task["project_id"], entity_type=task["entity_type"],
                                         entity_id=task["entity_id"], entity_key=task["entity_key"], reference_subject_id=task["reference_subject_id"],
                                         outfit_variant_id=task["outfit_variant_id"], role=role, storage_kind="local_file", local_path="mock.png",
                                         renderer_locator=None, mime_type="image/png", sha256="mock", width=1, height=1, version=1,
                                         status="approved", source="generated", source_image_id=None, crop_metadata={}, mask_asset_id=None, approved_at=NOW, **STAMP)
                            image["promoted_asset_id"] = asset["id"]; ASSETS.insert(0, asset)
                            set_reference_asset_status(asset, "approved")
                            return self.send(asset)
        if path == "/api/outline/sessions/resolve":
            pid = data["project_id"]
            return self.send(dict(session_id=pid, project_id=pid, thread_id=f"mock-{pid}", purpose="outline",
                                  outline_versions=[OUTLINE] if pid == 1 else [], messages=[]))
        if match := re.fullmatch(r"/api/visual-bible/assets/(\d+)/status", path):
            asset = next(item for item in ASSETS if item["id"] == int(match[1]))
            set_reference_asset_status(asset, data["status"])
            return self.send(asset)
        if match := re.fullmatch(r"/api/visual-bible/configurations/(outfit|style|scene)/(\d+)/status", path):
            items = {"outfit": OUTFITS, "style": STYLES, "scene": SCENE_VERSIONS}[match[1]]
            item = next(item for item in items if item["id"] == int(match[2]))
            item.update(status=data["status"], approved_at=NOW)
            return self.send({"id": item["id"], "status": item["status"]})
        if match := re.fullmatch(r"/api/visual-bible/projects/(\d+)/(outfits|styles|scene-versions)", path):
            items = {"outfits": OUTFITS, "styles": STYLES, "scene-versions": SCENE_VERSIONS}[match[2]]
            item = dict(data, id=3000+len(items), project_id=int(match[1]), version=2,
                        status="draft", approved_at=None, **STAMP)
            items.insert(0, item)
            return self.send(item)
        # 参考图任务只返回内存模拟候选；其它未配置接口不会访问外部 Provider。
        return self.send({"code": "common.not_found", "message": "Generation is disabled in this mock"}, 404)

    def do_PUT(self):
        path = urlparse(self.path).path
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        if match := re.fullmatch(r"/api/reference-images/visual-profiles/(\d+)", path):
            item = next((profile for profile in VISUAL_PROFILES.values() if profile["id"] == int(match[1])), None)
            if item is None or item["revision"] != data["expected_revision"]:
                return self.send({"detail": {"code": "reference.profile_conflict", "message": "摘要已更新，请重新准备。"}}, 409)
            item.update(data=data["data"], revision=item["revision"]+1)
            return self.send(item)
        if match := re.fullmatch(r"/api/reference-images/subjects/(\d+)", path):
            item = next(item for item in SUBJECTS if item["id"] == int(match[1])); item.update(data)
            return self.send(item)
        if match := re.fullmatch(r"/api/reference-images/script-scenes/(\d+)/subject", path):
            SCENE["reference_subject_id"] = data["reference_subject_id"]
            return self.send(dict(id=int(match[1]), **data))
        if path.endswith("/outfit"):
            SCRIPT_CHARACTER["outfit_variant_id"] = data["outfit_variant_id"]
            return self.send({"id": 401, **data})
        if path.endswith("/visual-version"):
            SCENE["selected_visual_version_id"] = data["scene_visual_version_id"]
            return self.send({"id": 301, "selected_visual_version_id": data["scene_visual_version_id"]})
        return self.send({"code": "common.not_found", "message": "Mock endpoint not configured"}, 404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--prompt-delay", type=float, default=0, help="模拟 Prompt 请求耗时（秒）")
    parser.add_argument("--fail-first-prop-preview", action="store_true", help="模拟首个物品 Prompt 请求失败")
    args = parser.parse_args()
    print(f"Mock workspace API: http://127.0.0.1:{args.port} (in-memory only)", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.prompt_delay = max(0, args.prompt_delay)
    server.fail_prop_once = args.fail_first_prop_preview
    server.serve_forever()
