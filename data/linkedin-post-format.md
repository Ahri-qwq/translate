# 领英动态文案格式规范

从 DeepModeling 社区已发布的 12 条领英动态里反推出来的格式，供 LLM 生成文案时使用。

## 样本来源

| # | 文章/事件 | 用的模板 |
| --- | --- | --- |
| 1 | Uni-Mol 电池电解质 | 密集叙事 |
| 2 | DPA4C 性能突破 | 问题-方案 |
| 3 | DeePMD 熔盐堆 | 密集叙事 |
| 4 | DeePMD SOI 芯片 | 双链接 |
| 5 | DPA2 核合金 | 密集叙事 |
| 6 | DeePMD Mg-Al-Si-O | 双链接 |
| 7 | APEX V1.3.0 发布 | 工具发布 |
| 8 | DPA4 Matbench | 问题-方案 |
| 9 | DeepFlame 2.0 | 工具发布 |
| 10 | Uni-Lab-OS 1.0 | 工具发布 |
| 11 | DeePMD Si 表面 | 科普钩子 |
| 12 | Uni-Mol OCNet | 密集叙事 |

---

## 必须项（所有模板共用）

- **首行**：一个 emoji + 一句话标题（或悬念句）
- **机构署名**：正文某处必须出现研究团队所属机构全称
- **具体数字**：至少 2 个硬数值（加速比、精度、规模等）
- **期刊名**：末尾注明，用 `Published in <期刊>.` 或嵌在正文里
- **链接**：博客链接单独一行，或用 `👉` 嵌在正文末尾
- **标签**：最后一行，5-9 个，`#DeepModeling` 是固定项
- **长度**：自然写完即可，不要主动凑字数；如果明显超过约 1300 字符再裁（领英的折叠线）

链接和标签的顺序：链接在标签前面，或两者都在末尾时链接在上。

---

## 五种模板

### 模板 A：密集叙事

适合：纯科学发现类，结果清晰但不需要特别强调打破旧范式。

```
<emoji> <标题句>

<正文 1-2 段：第一句点明机构+做了什么，后面几句塞进关键数字和方法>

Published in <期刊>.

🔗 <博客链接>

<标签>
```

示例节奏参考（例 1）：标题 → 一大段（机构+方法+数字+实验验证） → 期刊 → 链接 → 标签。
没有 bullet，靠正文密度取胜，读起来像新闻简报。

---

### 模板 B：问题-方案

适合：有明显"打破旧范式"的工具/模型发布，性能数字突出。

```
<emoji> <标题句（可以是悬念句而非陈述）>

<第一段：描述行业痛点或旧方案的局限，用"For years..."或"The trade-off has always been...">

<第二段：新方案一句话介绍>

<bullet 列表，4-5 条，每条一个硬指标>

<可选：一句补充说明或期刊>

🔗 <博客链接>

<标签>
```

示例节奏参考（例 2）：悬念标题 → 痛点段 → 解决方案 → ✅ bullet × 4 → 链接 → 标签。
注意例 2 链接在标签后面——这种变体也可以用。

---

### 模板 C：科普钩子

适合：科学发现类，目标受众不一定有专业背景，需要先吸引人再讲硬核内容。

```
<emoji> <标题句>

<第一段：一个生活化的铺垫或"你可能不知道"的钩子，让外行也能继续读>

<第二段：引出研究，点明机构和做了什么，带入数字>

<可选：👉 Know more: <链接>>

<标签>
```

示例节奏参考（例 11）：标题 → 科普段（硅片原子运动的比喻）→ "Recently, 研究团队..." → 链接 → 标签。
不用 bullet，靠叙事张力取胜。

---

### 模板 D：工具发布

适合：版本发布、开源工具上线、平台宣告。语气偏官方，两段正文。

```
<emoji> <产品名 + 版本/事件，陈述句>

<第一段：背景和意图，这个工具在解决什么问题>

<第二段：本次版本/发布的具体内容，可以列举 2-3 个亮点>

Learn more 👉 <链接>  （或 🔗 <链接>）

<标签>
```

示例节奏参考（例 7/9/10）：标题宣告 → 背景段 → 内容段 → 链接 → 标签（有时无标签）。

---

### 模板 E：双链接

适合：既要给工具主页又要给论文 DOI，或者想同时引导两个去处。

```
<emoji> <标题句>

<正文 1-2 段，机构+方法+数字，风格同模板 A>

👉 Visit <工具名>: <工具链接>
👉 See this paper: <论文链接>

<标签>
```

示例节奏参考（例 4/6）：标题 → 一大段正文 → 两个 👉 → 标签。
博客链接可以省略，也可以换成其中一个 👉。

---

## 模板选择逻辑

**不要随机选**，读完博客全文后根据文章内容判断。每个模板都有明确的适用信号，缺少信号就不要强行套用。

### 判断标准

按顺序检查，第一个满足条件的就用那个模板：

**D（工具发布）** — 文章标题或正文明确提到"发布"、"上线"、"Release"、"版本号"（如 v1.3.0）：
- ✅ "APEX V1.3.0 Released"
- ✅ "DeepFlame 2.0: Embracing the Agent Era"
- ❌ 只是介绍工具用法的教程文章

**E（双链接）** — 博客里同时给了工具主页和论文链接，且两者都重要：
- ✅ 正文末尾有"Visit DeePMD-kit: ..." + "See this paper: ..."
- ❌ 只有论文 DOI，没有独立的工具页

**B（问题-方案）** — 文章正文明确描述了旧方案的局限或行业痛点，新方案突破了它：
- ✅ "传统 DFT 一直预测错"、"For years, the trade-off has been..."、"以往只能顾此失彼"
- ✅ 有 3+ 个明确的性能对比数字（"20× 加速"、"误差从 5.2 降到 1.2"）
- ❌ 文章只是说"我们做了 X，得到了 Y"，没有对比旧方案

**C（科普钩子）** — 文章的主题离日常生活或常识较远，且正文开头用了科普铺垫：
- ✅ "硅片原子在高温下'出汗'"、"你可能不知道，地幔深处的矿物相变..."
- ✅ 中文原文就有科普段落
- ❌ 纯技术性研究，没有生活化类比

**A（密集叙事）** — 其他所有情况，包括：
- 纯科学发现，无明显痛点对比
- 方法创新但不是工具发布
- 数字清晰但不需要用 bullet 堆砌

### 默认选择

**当不确定或多个模板都适用时，选 A（密集叙事）**。

A 是最稳的基准模板，适用范围最广，不会因为硬编痛点或科普钩子显得刻意。

### 反例提醒

- **不要因为"有数字"就选 B**：A 也可以把数字嵌进正文，不一定要用 bullet
- **不要因为"想要 bullet"就选 B**：bullet 只是形式，关键是有没有痛点对比
- **不要因为"想吸引人"就选 C**：科普钩子型只适合确实有生活化类比的文章，强行编一个反而显得油腻

---

## 首行 emoji 选择

- 🚀 工具/性能突破，速度或规模类进展
- 📣 科学发现发布
- 📊 数据/计算类研究
- 🔋🧪🌍 按学科领域（电池/化学/地球科学）
- 😍🙌🎉 非正式场合，产品发布、庆祝类
- 📝 综述/方法论类

---

## 话题标签

固定项：
- `#DeepModeling` — 每篇都有
- `#AIforScience` 或 `#AI4Science` 或 `#AI4S` — 三种写法都出现过，任选一个

按分类追加：

| 博客分类 | 建议标签 |
| --- | --- |
| DeePMD-kit | #DeePMD #MolecularDynamics #DeepPotential |
| ABACUS | #ABACUS #DFT #ComputationalChemistry |
| Uni-Mol | #UniMol #DeepLearning |
| DPA | #MachineLearning #MaterialsScience #DPA |

再按文章主题补 1-3 个领域标签（#MaterialsScience #NuclearEnergy #Semiconductors
#EnergyStorage #GPUComputing #Geophysics #ComputationalMaterials 等）。

---

## 完整示例（ABACUS_2026_09_01，模板 B）

```
🚀 ABACUS Brings Real-Time TDDFT to GPUs

A collaborative team from Peking University, USTC, and the Institute of
Physics has built a unified heterogeneous computing framework for real-time
time-dependent DFT (RT-TDDFT) on numerical atomic orbitals — inside the
open-source DFT package ABACUS.

The design uses a three-layer hardware-agnostic abstraction: a unified tensor
container, a linear algebra operator interface, and a real-space grid
integration interface. Physics algorithm developers write the formulation,
never the device memory management or vendor-specific kernels — so the code
stays portable across NVIDIA, AMD, and whatever accelerator comes next.

What it delivers:
✅ Single A800 GPU runs 3–4× faster than a fully-loaded 56-core dual-socket CPU node
✅ Core wavefunction propagation module: up to 6–7× acceleration
✅ Velocity-gauge spherical grid integration: up to 12× acceleration
✅ 40 GPUs across nodes still hold ~76% parallel efficiency on a 1728-atom system
✅ GPU numerics identical to CPU, and benchmarked against SIESTA

Optical absorption spectra, dielectric functions, and nonadiabatic Ehrenfest
ion-electron coupled dynamics are all supported. Available now in ABACUS
v3.9.0.26+. Published in Computer Physics Communications.

🔗 https://blogs.deepmodeling.com/ABACUS_2026_09_01/

#AIforScience #DeepModeling #ABACUS #DFT #HeterogeneousComputing
#MaterialsScience #GPUComputing
```
