## 核心判断

按我本次读取到的 Comaic 仓库，你现在的**语义一致性建模其实已经比较合理**：

* `outline_character` 保存角色长期不变的身份、外观、视觉锚点和禁止变化项；
* `script_character`、`script_section` 保存某一剧情段中的发型、服装、配饰、状态和临时变化；
* `script_scene` 集中保存地点、光照、天气、环境、色板和场景锚点；
* 页面只保存当前镜头的局部变化，再关联对应角色和场景。([GitHub][1])

问题发生在这些结构化信息进入图像生成器的时候：目前 `ImagePromptAgent` 会把它们压缩成一条英文正向 Prompt，各页面基本独立生成；`ComfyWorkflowPreset` 主要只能注入正向 Prompt、负向 Prompt 和 seed。也就是说，原本清晰的角色、服装、场景结构，最后发生了一次严重的**有损编译**。([GitHub][2])

当前批量任务把同一组候选 seed 用在各页面上，这对复现和 A/B 测试有价值，但 seed 只决定初始噪声，不能真正锁定角色身份、服装或空间结构。与此同时，`ComicImage` 目前保存的生成溯源信息也偏少，不足以诊断到底是模型、LoRA、参考图、ControlNet 还是采样参数造成了漂移。([GitHub][3])

因此最关键的改造不是继续增加 Prompt 长度，而是把 Comaic 从：

> 剧本 → 自由文本 Prompt → 单次文生图

升级成：

> 剧本状态 → 视觉状态快照 → 结构化生成规格 → 多种视觉条件 → 生成 → 自动质检 → 局部修复

有一条可以贯穿整个系统的原则：

> **越要求某个元素严格不变，就越不应该让扩散模型在每张图里从头重新猜测和绘制它。**

---

# 一、把“一致性”拆成不同控制通道

角色、服装、场景并不是同一种一致性问题，最好分别建立真值来源。

| 一致性对象 | 真值来源                     | 主要生成条件              | 自动验收           |
| ----- | ------------------------ | ------------------- | -------------- |
| 角色身份  | 多视角角色参考集、身份 LoRA         | 参考图适配器、身份 LoRA、面部条件 | 人脸或角色裁剪相似度     |
| 发型、体型 | 全身与半身参考图                 | 整体角色参考、区域条件         | 全身裁剪相似度、属性检查   |
| 服装    | `OutfitVariant`、服装参考图、色板 | 服装 LoRA、区域参考、蒙版编辑   | 颜色、材质、图案、配件检查  |
| 场景几何  | 场景母版、平面图、3D 草模           | 深度、边缘、分割、透视控制       | 地标位置、空间关系、深度结构 |
| 场景状态  | 物体状态图和连续性事件              | 场景参考图、局部重绘          | 门窗、道具、破损等状态检查  |
| 动作和构图 | Shot Plan                | 姿态、框选区域、深度图         | 关键点和主体位置       |
| 风格和光照 | `StyleProfile`、光照状态      | 风格 LoRA、参考图、固定后处理   | 风格嵌入、色彩和曝光检查   |

IP-Adapter 的研究证明了文本条件和图像条件可以通过解耦交叉注意力共同工作；ControlNet 则适合承载姿态、边缘、深度等结构控制。多区域生成可以借鉴 MultiDiffusion 和区域注意力方法，将不同人物和条件绑定到不同空间区域。需要注意，这些具体权重和实现通常与模型架构绑定，不能假定 SDXL 的适配器可以直接用于 Anima 或 Z-Image。([arXiv][4])

---

# 二、先增加“视觉状态快照”，不要直接从剧本生成 Prompt

你已有的 `outline_character → script_character → page` 层级可以保留，但建议在页面和生成任务之间增加一个确定性的 `VisualStateSnapshot`。

```text
角色基准状态
+ 当前服装版本
+ 当前场景状态
+ 连续性事件
+ 当前镜头局部变化
────────────────
= VisualStateSnapshot
```

例如：

```json
{
  "page_id": 37,
  "continuity_block_id": 8,
  "characters": [
    {
      "character_id": 3,
      "identity_version": 2,
      "hairstyle_id": "short_black_v1",
      "outfit_variant_id": 12,
      "outfit_state": {
        "jacket": "open",
        "shirt": "dry",
        "left_sleeve": "torn"
      },
      "held_props": ["red_umbrella_v1"],
      "injuries": []
    }
  ],
  "scene": {
    "scene_id": 5,
    "visual_version": 3,
    "time": "night",
    "weather": "heavy_rain",
    "object_states": {
      "front_door": "open",
      "desk_lamp": "on",
      "window_2": "broken"
    }
  }
}
```

## 建议引入连续性事件

不要仅依靠描述文本表达变化，可以建立 `continuity_event`：

* `CHANGE_OUTFIT`
* `REMOVE_JACKET`
* `PICK_UP_PROP`
* `TRANSFER_PROP`
* `CLOTHES_GET_WET`
* `GARMENT_TORN`
* `LIGHT_SWITCHED_ON`
* `DOOR_OPENED`
* `OBJECT_BROKEN`
* `TIME_ADVANCED`

LLM 可以负责从剧本中提取这些事件，但真正的状态更新由确定性的 reducer 完成。这样“上一页拿着伞，下一页是否仍然拿着伞”不再取决于 Prompt Agent 是否记得重写，而是状态机的结果。

还应当区分：

* **不可变字段**：身份、眼睛颜色、基础身高、疤痕位置；
* **受控可变字段**：发型、服装、配饰；
* **临时状态**：湿、脏、破损、受伤；
* **镜头字段**：表情、动作、朝向、主体位置。

页面描述不能直接覆盖不可变字段。若模型或 LLM 给出了与角色基准冲突的内容，应在提交 ComfyUI 前由校验器拦截。

---

# 三、建立真正的 Visual Bible，而不只是文字 Bible

现在数据库里的视觉锚点主要仍是文字。建议增加版本化视觉资产库，例如：

```text
VisualAsset
- id
- project_id
- entity_type: character / outfit / scene / style / prop / control
- entity_id
- role
- model_family
- file_path
- version
- approved
- source
- crop_metadata
- mask_path
- embedding
- derived_from_asset_id
```

## 角色资产

每个主要角色至少维护：

* 正面头像；
* 3/4 头像；
* 侧面头像；
* 半身；
* 全身；
* 常用表情；
* 对真人角色，最好再覆盖不同光照和头部角度。

作为工程起点，二次元角色可以先用 2–4 张高质量多视角参考，真人角色通常需要 4–8 张覆盖正面、3/4、侧面、半身和全身。这不是硬性数量；清晰、互相一致且经过人工确认的少量参考，通常比大量带有身份漂移的图片更可靠。

生成出的候选图不能自动加入角色基准集。只有人工确认后，才能升级为新的 canonical reference。否则错误会被不断反馈回系统。

## 服装资产

建议新增独立的 `OutfitVariant`：

```text
OutfitVariant
- character_id
- key
- garment_components
- layer_order
- colors
- materials
- patterns
- accessories
- front_reference
- back_reference
- detail_references
- lora_id
- trigger_tokens
- negative_constraints
```

服装需要显式记录：

* 上下装的层级关系；
* 是否敞开、扣上、卷袖；
* 材质；
* 主色、辅色；
* 图案和图案位置；
* 鞋、袜子、腰带、首饰；
* 临时状态，如湿、脏、破损。

**身份 LoRA、服装 LoRA 和风格 LoRA 应尽量分开。**

训练身份 LoRA 时，应让训练数据包含多种服装、背景和姿态，减少“这个人永远穿同一件衣服”的绑定。训练服装 LoRA 时，则应尽量使用不同姿态甚至不同人物，让服装概念不只绑定到一个人的脸。一次性出现的服装一般没有必要训练 LoRA，用服装参考图加区域重绘更划算。

## 场景资产

一个重复使用的场景至少应保存：

* 建立镜头或场景母版；
* 持久地标列表；
* 物体空间关系；
* 简单平面图；
* 常用摄像机位置；
* 深度图、边缘图或分割图；
* 白天、夜间等光照版本；
* 可变化物体的状态。

对于高频室内场景，最稳定的方案通常是用 Blender 等工具建立非常粗的 3D 草模，只负责墙体、家具和摄像机位置，再渲染深度、法线、边缘或分割控制图。最终画面仍可由 Anima、Z-Image 等模型完成。

同一机位重复出现时，甚至可以直接复用背景母版，只在人物区域进行生成或重绘。这样场景一致性不再依赖模型“记住这间房”。

---

# 四、把 `ImagePromptAgent` 改成 `ShotPlannerAgent + ImageSpecCompiler`

当前 Agent 最终返回一条自由文本，这会造成同义词漂移、遗漏、描述顺序改变，以及不同底模的提示词习惯混用。

建议拆成两步：

1. `ShotPlannerAgent` 只负责镜头中真正需要创造的内容：

   * 摄像机；
   * 景别；
   * 构图；
   * 动作；
   * 表情；
   * 角色区域；
   * 需要使用的控制图。

2. `ImageSpecCompiler` 确定性地合并：

   * `VisualStateSnapshot`；
   * 视觉资产；
   * 模型能力；
   * Shot Plan；
   * 渲染参数。

一个页面的输入不再只是一条 Prompt，而是类似：

```json
{
  "model_profile": "anima_base_v1",
  "continuity_block_id": 14,
  "style_asset_id": 17,

  "scene": {
    "scene_state_id": 8,
    "master_asset_id": 61,
    "camera": {
      "shot": "medium shot",
      "azimuth": 35
    },
    "depth_asset_id": 82
  },

  "subjects": [
    {
      "character_id": 3,
      "identity_asset_ids": [21, 22, 23],
      "identity_lora_id": 5,
      "outfit_variant_id": 12,
      "outfit_asset_ids": [34, 35],
      "region": [0.08, 0.10, 0.46, 0.94],
      "pose_asset_id": 81
    }
  ],

  "continuity_anchor_image_id": 105,

  "render": {
    "candidate_count": 4,
    "seed_strategy": "per_page",
    "repair_pass": true
  }
}
```

这里的完整 Prompt 应当只是**编译产物和调试信息**，而不是生成任务的唯一真值。

然后为每个模型实现独立编译器：

```text
AnimaPromptCompiler
ZImagePromptCompiler
SDXLPromptCompiler
QwenImageEditCompiler
```

例如 Anima 官方说明其提示词支持 Danbooru 标签和自然语言混用，并规定了较明确的标签顺序；多角色画面还需要对每个角色显式描述外观。不能把同一套长自然语言 Prompt 原样用于所有底模。([Hugging Face][5])

---

# 五、扩展 ComfyUI preset：从三个输入变成能力声明

当前 preset 只映射 positive、negative、seed。建议改为：

```json
{
  "capabilities": [
    "txt2img",
    "img2img",
    "reference_image",
    "lora",
    "pose",
    "depth",
    "canny",
    "regional_condition",
    "inpaint"
  ],
  "bindings": {
    "prompt.positive": "6.text",
    "prompt.negative": "7.text",
    "render.seed": "25.noise_seed",

    "subjects.0.identity_reference": "31.image",
    "subjects.0.identity_lora": "45.lora_name",
    "subjects.0.identity_lora_weight": "45.strength_model",

    "scene.depth": "70.image",
    "repair.mask": "82.mask"
  }
}
```

`WorkflowCompiler` 在提交前检查：

* 当前 workflow 是否支持所需参考图；
* 是否支持多个角色；
* 是否支持区域绑定；
* LoRA 是否属于当前模型家族；
* ControlNet 是否与当前 checkpoint 兼容；
* 缺失能力时是降级、换 workflow，还是拒绝生成。

建议再抽象一层：

```text
RendererBackend
├── ComfyUIBackend
├── LocalDiffusersBackend
└── EditModelBackend
```

这样未来加入 Qwen-Image-Edit 或某个 sequence-generation 后端，不必把所有逻辑塞进 ComfyUI service。

---

# 六、使用“连续性块”和关键帧，而不是线性追着上一张图生成

建议按以下条件把页面划分成 `ContinuityBlock`：

```text
scene_id
+ 当前服装版本
+ 时间和主要光照
+ 天气
+ 关键场景状态
```

每个连续性块采用三级锚点：

```text
角色和场景 canonical assets
              ↓
       连续性块关键帧
              ↓
          当前页面
```

生成顺序：

1. 先生成建立镜头或关键帧；
2. 人工选定关键帧；
3. 后续页面始终携带 canonical references；
4. 同时可以将关键帧作为场景和造型的局部参考；
5. 上一页图片只作为弱的附加参考，不能成为唯一参考。

不要采用：

```text
第 1 页 → 第 2 页 → 第 3 页 → 第 4 页
```

这种纯链式 img2img 会积累误差。第三页继承第二页的小错误，第四页又继承第三页的错误，最终角色和服装会逐渐变形。

StoryDiffusion 通过 Consistent Self-Attention 在一组图之间共享一致性信息；StoryMaker 同时使用面部身份和完整人物裁剪，以更好保留头发、衣服和身体特征；AnyStory 则面向单主体和多主体故事个性化。这些方案证明了“整组图联合建模”相较独立页面生成的潜力，但其代码与权重仍具有明显模型架构依赖。([arXiv][6])

因此可以增加一个未来接口：

```text
SequenceRenderer.render(
    continuity_block,
    image_specs[]
)
```

它可以一次生成整个连续性块，或者维护跨请求的 attention/reference bank。这个方向适合作为 P2，而不是第一步就重构进去。

---

# 七、多人物和复杂服装必须做区域绑定

多人物场景最常见的问题是：

* A 的发色跑到 B 身上；
* 两个人交换服装；
* 配饰随机转移；
* 身体融合；
* Prompt 中靠前的角色占据所有特征。

每个主体都应有：

```text
character_id
identity reference
outfit reference
bounding box / mask
pose
depth order
regional prompt
regional negative prompt
```

如果底模和 workflow 支持区域注意力，就分别注入。

如果不支持，采用模型无关的分阶段方法：

1. 生成背景；
2. 在 A 的蒙版区域生成人物 A；
3. 在 B 的蒙版区域生成人物 B；
4. 对边缘、光照、阴影进行一次低 denoise 的融合；
5. 最后修复脸、手、衣服细节。

MultiDiffusion 和区域注意力研究表明，可以将不同文本或视觉条件绑定到指定蒙版和区域，而不是让所有条件在整张图上互相竞争。([arXiv][7])

实际生产中，**背景一次生成、人物分层生成、最后融合**，通常比要求一个文生图节点同时准确处理房间、两三个人物、服装、动作和道具更稳定。

---

# 八、使用多阶段生成，而不是期待一次采样完成所有事情

推荐的最终生产链路：

### 1. Layout pass

产生或确认：

* 主体框；
* 人物姿态；
* 摄像机；
* 前后遮挡；
* 深度顺序；
* 视线方向。

### 2. Scene pass

使用场景母版和深度、边缘、分割等条件生成背景。

### 3. Subject pass

按人物区域分别应用：

* 身份参考；
* 人物 LoRA；
* 服装参考或服装 LoRA；
* 姿态；
* 区域 Prompt。

### 4. Repair pass

只重绘失败区域：

* 脸；
* 手；
* 衣领、袖口；
* 图案；
* 配饰；
* 角色与地面的接触阴影。

### 5. Deterministic composition

以下内容最好不要交给扩散模型：

* 对话文字；
* 气泡；
* 分镜框线；
* 商标和必须准确的文字；
* 必须完全相同的徽章、纹身、饰品图案。

这些内容应通过 SVG、Canvas、HTML 或图像合成确定性添加。

你当前 MVP 采用单页单图而非复杂多格漫画，这反而有利于一致性。将来增加多格页面时，建议每个 panel 独立作为 shot 生成，最后由页面布局器组合，不要让模型一次生成完整漫画页面。([GitHub][1])

---

# 九、建立自动一致性质检，而不仅是人工挑图

人工选择应该保留，但可以在人工之前自动筛选。

建议每张图保存一个分项分数，而不是单一 `score`：

```json
{
  "identity": 0.92,
  "hairstyle": 0.88,
  "outfit": 0.74,
  "scene": 0.91,
  "pose": 0.95,
  "style": 0.87,
  "prompt_alignment": 0.90,
  "artifacts": 0.96,
  "copy_paste_penalty": 0.12
}
```

## 真人角色

* 人脸识别 embedding 与 canonical face references 对比；
* 全身裁剪与完整人物参考对比；
* 单独比较发型、轮廓、体型和服装区域。

## 二次元角色

传统人脸识别对二次元未必可靠，可以组合：

* 自监督视觉 embedding；
* 角色裁剪相似度；
* VLM 属性检查；
* 发色、瞳色、发型、配饰的结构化判断。

## 服装

* 先分割服装区域；
* 检查主色和辅色；
* 检查图案、材质和配件；
* 检查服装状态，例如是否敞开、湿、破损。

## 场景

* 检查持久地标是否存在；
* 检查物体之间的相对位置；
* 对比深度或边缘结构；
* 检查连续性事件后的状态。

ViStoryBench 已将视觉故事一致性拆成角色、风格、Prompt 对齐、美学、瑕疵和复制粘贴等多个维度，并提供自动指标思路。Comaic 可以借鉴它建立自己的回归基准，而不是只看一张图“感觉像不像”。([arXiv][8])

更重要的是，质检结果应决定**修复哪一部分**：

* 身份不合格：只重新生成角色区域；
* 服装不合格：蒙版重绘衣服；
* 场景几何不合格：加强深度或边缘控制；
* 姿态不合格：重新使用姿态条件；
* 风格不合格：调整风格参考或 LoRA；
* 不要默认整张图全部重来。

---

# 十、二次元和真人应采用不同策略

|          | 二次元                              | 真人                                               |
| -------- | -------------------------------- | ------------------------------------------------ |
| 身份主要来源   | 稳定标签、角色 LoRA、角色参考图               | 面部身份条件、完整人物参考、身份 LoRA                            |
| 最重要结构条件  | 线稿、姿态、边缘                         | 姿态、深度、边缘、相机和光照                                   |
| 服装       | 标签和轮廓通常较有效                       | 材质、褶皱、层次和图案容易漂移                                  |
| 场景       | 线稿和色板可强力约束                       | 几何、透视、焦段和光照都必须稳定                                 |
| 一次文生图可用性 | 较高                               | 较低                                               |
| 最终推荐     | T2I + LoRA + lineart/pose + 区域修复 | 参考图 + 身份控制 + 全身/服装条件 + depth/pose + edit/inpaint |

## 真人一致性的关键点

真人不能只锁脸。完整身份至少包括：

* 面部几何；
* 发际线和发型；
* 头身比例；
* 肩宽和体型；
* 肤色与皮肤纹理；
* 服装轮廓；
* 相机透视；
* 光照方向。

InstantID 和 PuLID 等方法擅长人脸身份保持，但主要存在于特定 SD/SDXL 生态中；StoryMaker 同时使用面部身份与完整人物裁剪，正是因为单独锁脸不能保证头发、身体和服装一致。Comaic 应设计统一的 identity-provider 接口，但不能假定这些现有权重能直接迁移到 Anima 或 Z-Image。([arXiv][9])

真人模式还建议把以下字段加入 `SceneState` 或 `StyleProfile`：

* 镜头焦段；
* 相机高度；
* 光圈和景深；
* 主光方向；
* 色温；
* 胶片或调色风格；
* 皮肤质感强度。

Face swap 最多作为最后的局部修复工具，不应成为身份一致性的核心，因为它解决不了发型、头身关系、衣服、透视和光照不匹配。

---

# 十一、针对 Anima 的推荐路线

Anima 官方定位主要是二次元及非写实生成，真人写实并不是其强项。官方模型说明中：

* Base 更灵活，适合 LoRA 和进一步训练；
* Aesthetic 更强调质量和一致性；
* Turbo 更快、更稳定、采样步数较低，但多样性也较低；
* 官方明确提示其真实感表现有限。([Hugging Face][5])

因此建议：

### 草图和交互预览

```text
Anima Turbo
+ 固定角色描述编译
+ 可选角色 LoRA
+ 低成本姿态或线稿控制
```

### 最终二次元成图

```text
Anima Base
+ identity LoRA
+ outfit LoRA
+ style LoRA
+ lineart / canny / depth / pose
+ 区域蒙版
+ 局部 inpaint
```

暂时不训练 LoRA 时，可以使用 Aesthetic 作为相对稳定的最终出图选择，再根据实际基准比较。

Anima 提供了 ControlNet-LLLite 的训练和 ComfyUI 使用路径，可利用 lineart、canny、depth 等条件；目前这部分仍带有实验性质，因此最好通过能力接口接入，不要写死为唯一实现。([GitHub][10])

Anima Prompt 编译器应遵循其标签结构，把质量、年份、安全标签、人数、角色、系列、画师和一般属性按稳定顺序编译；自然语言用于动作、场景和复杂空间关系。多人物时，对每个人分别显式写出外观和服装，不要只写角色名字。([Hugging Face][5])

---

# 十二、针对 Z-Image 的推荐路线

Z-Image 官方模型矩阵把 Turbo 定位为快速、低步数、低多样性的生成版本，而基础模型更适合高质量、多样性、可控生成和微调。官方为 Base 给出了 CFG 3–5、约 28–50 步的推荐区间，并提供 LoRA 或完整训练支持；Turbo 主要是快速推理，不适合作为核心个性化训练模型。([GitHub][11])

因此建议：

### 快速预演

```text
Z-Image Turbo
+ Shot Plan
+ Canny / layout
+ 少量候选
```

### 真人或半写实最终生成

```text
Z-Image Base
+ identity LoRA
+ outfit reference / outfit LoRA
+ Canny、姿态、深度条件
+ 场景母版
+ 区域生成
+ 低 denoise 编辑与修复
```

官方 ComfyUI 示例已经包含 Z-Image-Turbo 的 Union ControlNet Canny 工作流，可以先用它验证 Comaic 新的 control binding 设计。([ComfyUI][12])

Z-Image 的图像转 LoRA 等社区插件可以作为实验性 provider，但不应成为核心数据模型的前提。Comaic 的结构应当允许某个模型没有原生 reference adapter 时，退化为：

```text
canonical references
→ 训练 LoRA
→ img2img / inpaint
→ 独立编辑模型修复
```

官方仓库中仍标记为待发布的 Omni/Edit 组件，不建议据此设计当前必须依赖的功能。([GitHub][11])

---

# 十三、值得支持的其他后端

## SDXL 兼容后端

即使 SDXL 不是你的主要质量目标，也建议保留一个 SDXL provider 作为架构验证平台，因为 IP-Adapter、InstantID、PuLID、StoryMaker 和大量区域控制工具在该生态里更成熟。

它适合验证：

* 多参考图；
* 人脸身份；
* 多人物区域绑定；
* ControlNet 组合；
* 关键帧到后续镜头；
* 局部编辑闭环。

验证成功后，再为 Anima 和 Z-Image 实现同样的抽象，而不是把 SDXL 节点名称写入业务层。

## Qwen-Image-Edit-2511

它可以作为独立的“修复和编辑后端”，而不必替代主生成模型。其官方资料明确强调了多图输入、角色一致性和多人一致性的改进，适合：

* 用多张角色和服装参考修复已生成图片；
* 在不改变构图的情况下修改服装；
* 修正某个角色的身份；
* 为同一角色生成新视角；
* 进行多人物局部替换。

代价是模型规模和运行资源明显更高。([GitHub][13])

---

# 十四、必须补全生成溯源

建议把当前 `ComicImage` 拆分或扩展为 `GenerationRun` 和 `GenerationArtifact`，至少保存：

```text
checkpoint 名称和 hash
模型家族
VAE / text encoder
LoRA 名称、hash、权重
所有参考资产 ID 和版本
ControlNet / adapter 名称和 hash
控制图 ID
控制强度、start/end
完整 workflow JSON 和 hash
ComfyUI custom node 版本
sampler
scheduler
steps
CFG
denoise
seed
父级关键帧 ID
ImageSpec hash
Prompt compiler 版本
各项一致性分数
人工选择结果和原因
```

否则某次结果突然变好或变差时，很难确定究竟是哪一个节点或模型文件发生了变化。

用户最终选中的图片可以成为：

* 当前连续性块的关键帧；
* 当前场景版本的候选母版；
* 某个服装版本的新参考；

但只有经过明确批准后才能晋升为 canonical asset。

---

# 十五、建议增加一个公开的一致性回归基准

可以在仓库中增加一组固定小故事，例如：

1. 单角色、同服装、8 个视角；
2. 同角色从室外进入室内；
3. 穿上和脱下外套；
4. 衣服淋湿后保持湿润状态；
5. 两个人物左右交换位置但身份不能交换；
6. 同一房间多个机位；
7. 门由关闭变成打开并持续保持；
8. 真人角色在不同光照和表情下保持身份；
9. 同一角色换装，但脸和体型不变；
10. 同一场景中指定道具从 A 转移给 B。

每次模型、Prompt 编译器、workflow 或 LoRA 更新后，都运行这套基准并记录：

* 身份一致性；
* 服装一致性；
* 场景一致性；
* 动作准确率；
* 风格一致性；
* 复制粘贴程度；
* 失败率；
* 显存和时间成本。

这样 Comaic 才能客观回答“某个新工作流是否真的提高了一致性”，而不是仅展示几张成功样例。

---

# 十六、落到当前代码的优先改造顺序

## P0：收益最高

1. **新增 `VisualStateSnapshot` 和 `ContinuityEvent`**
   把角色、服装、道具、场景状态变成确定性状态机。

2. **新增 `VisualAsset`、`OutfitVariant`、`SceneVisualVersion`**
   建立人工批准、可版本化的视觉参考资产。

3. **将 `ImagePromptAgent` 拆为 `ShotPlannerAgent + ImageSpecCompiler`**
   LLM 只产生镜头和变化，固定信息由代码确定性合并。

4. **将 `ComfyWorkflowPreset` 扩展为 capabilities + bindings**
   支持参考图、LoRA、ControlNet、区域条件、img2img 和 inpaint。

5. **默认使用每页独立 seed，同时保存完整溯源**
   当前跨页面复用候选 seed 可保留为实验模式，但不要把它当身份锁。

## P1：达到稳定漫画生产所需

6. 建立连续性块和关键帧；
7. 背景、人物、修复多阶段生成；
8. 多人物区域绑定；
9. 身份、服装、风格 LoRA 模块化；
10. 自动一致性评分、候选排序和局部重绘。

## P2：进一步追求上限

11. 接入 StoryDiffusion 类整组生成后端；
12. 维护跨页面 attention/reference bank；
13. 高频场景引入 Blender 3D 草模；
14. 训练 Anima/Z-Image 原生的参考图适配器；
15. 建立用户选择反馈驱动的项目级 reranker。

---

# 十七、几个应当明确避免的方案

* 不要把固定 seed 当成身份控制；
* 不要只依赖越来越长的 Prompt；
* 不要用上一张生成图作为下一张图唯一参考；
* 不要把身份、服装、风格全部训练进同一个 LoRA；
* 不要在一个无区域控制的采样里塞入过多角色；
* 不要只用 face swap 解决真人一致性；
* 不要默认 SDXL 的 IP-Adapter、InstantID 或 PuLID 权重能跨架构用于 Anima/Z-Image；
* 不要让模型绘制必须完全准确的文字、徽标、纹身和漫画气泡；
* 不要将自动生成的漂移图片未经人工审核就加入 canonical reference。

---

## 许可方面的额外提醒

Anima 更准确地说属于**开放权重模型**，但其许可证包含非商业及模型服务方面的限制，并不是 Apache、MIT 或严格 OSI 意义下的开源许可；即使输出内容的使用条款相对宽松，基于模型提供付费服务仍需单独关注许可证要求。Z-Image 官方则采用 Apache 2.0。([Hugging Face][5])

建议在 `ModelProfile` 中直接加入：

```text
license
commercial_use_allowed
paid_service_allowed
fine_tuning_allowed
redistribution_allowed
license_notice
```

并在用户选择底模时显示，而不是仅写在项目文档里。

---

最终最值得首先实现的组合是：

> **视觉状态快照 + 人工批准的参考资产 + 结构化 ImageSpec + 模型专用编译器 + ComfyUI 多条件绑定 + 连续性关键帧 + 区域生成 + 自动质检和局部修复。**

这套结构不会把 Comaic 绑定到 Anima、Z-Image 或某一篇论文，也能同时覆盖二次元和真人工作流。对真人模式尤其重要的是：把“角色一致性”从单纯的脸部相似，提升为面部、发型、身体、服装、相机、光照和场景共同受控的完整视觉状态。

[1]: https://github.com/Paran0idoX/Comaic/blob/main/AGENTS.md "https://github.com/Paran0idoX/Comaic/blob/main/AGENTS.md"
[2]: https://github.com/Paran0idoX/Comaic/blob/main/backend/prompts/image_prompt_system_prompt.md?plain=1 "https://github.com/Paran0idoX/Comaic/blob/main/backend/prompts/image_prompt_system_prompt.md?plain=1"
[3]: https://github.com/Paran0idoX/Comaic/blob/main/backend/services/image_generation_service.py?plain=1 "https://github.com/Paran0idoX/Comaic/blob/main/backend/services/image_generation_service.py?plain=1"
[4]: https://arxiv.org/abs/2308.06721 "https://arxiv.org/abs/2308.06721"
[5]: https://huggingface.co/circlestone-labs/Anima "https://huggingface.co/circlestone-labs/Anima"
[6]: https://arxiv.org/abs/2405.01434 "https://arxiv.org/abs/2405.01434"
[7]: https://arxiv.org/abs/2302.08113 "https://arxiv.org/abs/2302.08113"
[8]: https://arxiv.org/html/2505.24862v4 "https://arxiv.org/html/2505.24862v4"
[9]: https://arxiv.org/abs/2401.07519 "https://arxiv.org/abs/2401.07519"
[10]: https://github.com/kohya-ss/ComfyUI-Anima-LLLite/blob/main/nodes.py "https://github.com/kohya-ss/ComfyUI-Anima-LLLite/blob/main/nodes.py"
[11]: https://github.com/Tongyi-MAI/Z-Image "https://github.com/Tongyi-MAI/Z-Image"
[12]: https://docs.comfy.org/tutorials/image/z-image/z-image-turbo "https://docs.comfy.org/tutorials/image/z-image/z-image-turbo"
[13]: https://github.com/QwenLM/Qwen-Image "https://github.com/QwenLM/Qwen-Image"
