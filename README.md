# bili-news-video —— 时政快讯视频线

Grok 任务D（巴尔干快讯雷达）隔日出中文简报 → 本产线出 **1-3 分钟带配音带字幕的
快讯成片**。日报型新闻播报，只讲"发生了什么"和"各方怎么说"，不站队、不评论、不预测。

与 `bili-news/`（图文线）的关系：同一时政人设的两条载体。图文线首篇被毙的
选题边界（抗议/游行/警力叙事过线）已内化为本产线的红线规则 `src/redlines.py`。

## 流水线

```
briefing.md ──ingest──▶ briefing.json ──scriptgen──▶ script.json
                              │ GLM主路+规则降级        │ GLM主路+模板降级
                              ▼                        ▼
                        hammer 红线锤稿 ──▶ voice 逐段配音 ──▶ cards 文字卡
                                                                │
                     upload_info.txt ◀── publish-prepare ◀── render+qc
                     （投稿永远人工）
```

- **ingest**：简报原文 → 结构化。GLM 主路，无 key 规则降级；「今日无事」直接停。
- **scriptgen**：口播逐字稿 + 每段卡片字段。结构固定：hook → 逐条 → 涉华 → 主线 → outro。
- **hammer**：红线检查（继承图文线实测边界 + grokbot 讨论定稿）。BLOCK 命中
  GLM 稿定向重写一次、模板稿剔条目；条目清零即拒稿——无事不硬凑。
- **voice**：cosy(可选) → edge-tts → zhipu → 报错停线，绝不放机械音。
- **cards**：新闻卡面（台标条/信源徽标/**Natural Earth 真实底图卡**：焦点国
  红色高亮、标题地名自动定位（含首都别名），右栏外围行为者指向焦点；
  底图数据缺失时降级棋盘示意卡）。
- **render**：Ken Burns 缓推 + 顺序硬切 + ASS 字幕烧录 + loudnorm。
- **qc**：规格/时长/响度/字幕自检，不过关不出审片。

## 用法

```bash
python cli.py doctor                          # 体检
python cli.py ingest briefings/grok-1109.md   # 粘贴 Grok 简报原文（建 ep-NNN）
python cli.py ingest-script drafts/稿.md      # 人工稿通道：已成稿逐字稿直接进产线
python cli.py make ep-001                     # 全链到 QC（断点续跑）
python cli.py redo ep-001 voice               # 某阶段起重跑
python cli.py show ep-001                     # 状态/锤稿问题/QC 一览
python cli.py approve ep-001                  # 人工看片放行
python cli.py publish-prepare ep-001          # 生成 upload_info.txt
python cli.py publish ep-001                  # biliup 真实投稿（唯一出片动作）
python cli.py login                           # B站扫码登录/续期（cookie 与 bili-autopost-sau 共用）
```

人工稿通道（`ingest-script`）：吃 Grok 出稿模板式的 markdown（【时间｜段标题】+
口播段），跳过 AI 写稿直接进锤稿→配音→卡面→渲染全链；硬红线照查（信源徽标
检查豁免——人工稿信源在行文里），解析器在 md 标题/分隔线处截断，稿子后附的
信源表/红线清单不会被吞进口播；QC 校验成片时长对齐分镜时间轴（±90s）。

投稿走 `bili-autopost-sau/sau_bridge.py` 的 biliup（自制·AI辅助，分区 tid 228
知识·时事，config.yaml 可改）。**演示数据做的片子永远不要 publish**——卡面
没有水印，发出去就是虚构时政新闻；简报带「勿直接发布」标记的直接跳过。

联调/无网：`python cli.py make ep-001 --offline`（强制模板降级，配音仍需联网走 edge）。

## 信源四级（与 Grok 任务D 提示词一致）

`官方 / 主流媒体 / 区域专家 / 单方声称待核实`——口播必须带徽标；待核实只进
灰卡引语位，且必须念出「尚待核实」。

## 红线速查（详见 src/redlines.py）

- 不做：抗议/游行/罢工/骚乱/警力部署等社会运动叙事；伤亡画面化。
- 不做：预测（必将/恐怕会→各方关注）；站队定性词；涉华无官方锚点。
- 数字加「约」注机构；英里/海里必须换算公里（霍尔木兹脚本教训）。
