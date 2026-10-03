# GENESIS 推理方法

[English](../inference.md) | 简体中文

GENESIS 是完整的多智能体诊断系统。GENESIS-R1 是 GENESIS 中使用的、经过训练的医学推理模型。

GENESIS 从 Initial differential diagnosis 开始，通过三个并行的证据路径评估候选诊断，再执行 Evidence fusion。需要进一步审查时，Evidence-consistency audit 指导 Revised differential diagnosis 及下一轮证据循环。原始临床叙述在整个流程中始终可用。

## 模型分工

GENESIS-R1 负责 Initial differential diagnosis、三个证据路径中的诊断推理、Evidence fusion、Evidence-consistency audit 及 Revised differential diagnosis。Final diagnosis 是最后完成的一轮返回的最终结果，不需要单独调用模型。

辅助语言模型是用于快速处理简单辅助任务的较小模型：提取用于 HPO 映射的临床表现、检查检索材料与候选诊断的相关性，以及从检索得到的长文档中提取有效片段。这些任务采用 Qwen3-8B。

Qwen3-Embedding-8B 是独立的嵌入模型，生成用于检索的向量表示。BioLORD-2023 将临床术语映射到本体概念，MedCPT-Cross-Encoder 对检索相关性评分。

## Initial differential diagnosis（初步鉴别诊断）

GENESIS-R1 接收临床文本、已出现的表现、明确未出现的表现以及要求的候选数量，返回排序后的候选诊断，包括疾病名称、支持表现、矛盾表现、尚未解决的问题及诊断理由。明确的阴性表现与未提供的信息分开处理。

## 三个证据路径

### Multi-expert consensus（多专家共识）

独立诊断方法返回排序后的疾病列表。概念规范化统一不同疾病名称。代码根据候选诊断在各列表中是否出现及其相对位置计算一致性。GENESIS-R1 解释这种一致性的诊断意义，并识别当前鉴别诊断之外可信的其他诊断。其回复包含候选诊断评估及其他诊断建议，由该路径整理为证据记录。

### Dynamic knowledge retrieval and deduction（动态知识检索与推断）

GENESIS-R1 针对每个候选诊断，围绕典型特征、矛盾表现和疾病机制构建查询。初始检索预算允许每个候选诊断一次查询、每个来源三条记录；修订时允许每个候选诊断三次查询、每个来源十条记录。辅助模型可提取相关片段并判定证据立场；GENESIS-R1 在 Evidence fusion 中综合权衡这些材料。

配置了知识来源且启用该路径后，即可运行知识检索。`Tools.summarizer` 为可选项。未配置时，原始记录以中立立场传递。配置 `ModelEvidenceSummarizer(auxiliary)` 后，将提取相关片段，同时保留来源标识符和原始记录。如果该处理失败，仍保留检索所得的原始记录。

### Historical-case analogy（历史病例类比）

根据病例索引的能力，历史病例可通过表型术语、临床叙述或候选疾病名称检索。无论采用哪种检索方式，辅助模型比较的都是检索病例记载的诊断与当前某个候选诊断，并考虑同义名称和公认亚型。仅有疾病名称匹配，不能说明临床表现相似，也不能据此诊断当前患者。

GENESIS-R1 独立比较当前患者与检索病例的症状、检查结果及病程，解释哪些相似点或差异支持或反对各候选诊断，以及仍有哪些不确定之处。如果当前患者的表现值得考虑其他诊断，模型可以提出检索病例中记载的其他疾病。诊断不在当前候选列表中的病例也会保留，供此比较使用。

比较结果及引用的病例记录一起传递给 Evidence fusion，并保留数据库名称及可用的病例或文献标识符，以便追溯证据来源。

如果未检索到病例，该路径不提供历史病例证据。如果 GENESIS-R1 的比较结果不可用，记载诊断与候选诊断匹配的原始记录仍可传递给后续阶段，但不会将名称匹配本身视为支持诊断的临床证据。

## Evidence fusion（证据融合）

GENESIS-R1 读取原始病例、当前鉴别诊断、积累的证据及建议考虑的其他诊断，返回排序后的鉴别诊断、诊断推理、建议检查、来源引用及反思标志。检索材料与临床病例冲突时，以临床病例为首要依据。

## Evidence-consistency audit and Revised differential diagnosis（证据一致性审查与修订鉴别诊断）

如果 Evidence fusion 请求反思，审查阶段会综合候选诊断分类、跨路径支持情况以及 GENESIS-R1 的证据评估。报告指出缺乏支持的论断、矛盾表现、证据缺口及其他诊断建议。GENESIS-R1 随后接收原始病例、先前候选诊断、积累的证据和审查结果，在下一轮证据循环前保留、删除、引入或重新排序候选诊断。

`max_rounds` 统计初始证据循环之后的修订次数。默认 `max_rounds=3` 允许一次初始循环加最多三次修订，即总计最多四次证据检索与融合循环。满足一致性标准时可提前结束。若要求总计最多三次循环，应设置 `max_rounds=2`。

设置 `use_reflection=False` 会跳过审查和修订。返回结果仍保留 Evidence fusion 是否要求进一步审查的状态；停用反思本身不表示已满足一致性标准。

## Final diagnosis（最终诊断）

Final diagnosis 展示最后完成的一轮所得的排序鉴别诊断、诊断推理、建议检查及证据来源。最终排序在 Evidence fusion 中生成，展示该结果无需额外调用模型。

## 本地部署

软件包要求 Python 3.10 或更高版本，仅使用标准库。以下配置将所有诊断模型调用分配给 GENESIS-R1，将辅助处理分配给 Qwen3-8B。模型由部署环境提供，应使用相应服务端点公布的模型标识符。

```python
from genesis import Config, Models, Tools, diagnose
from genesis.llm.openai_compat import OpenAIChat
from genesis.tools import ModelPhenotypeExtractor, ModelEvidenceSummarizer

reasoner = OpenAIChat("http://localhost:8000/v1", "GENESIS-R1")
auxiliary = OpenAIChat("http://localhost:8001/v1", "Qwen3-8B", thinking=False)
models = Models(reasoner=reasoner, auxiliary=auxiliary)
tools = Tools(
    phenotype_extractor=ModelPhenotypeExtractor(auxiliary),
    summarizer=ModelEvidenceSummarizer(auxiliary),
    # Attach expert_methods, knowledge_sources and case_indices here.
    # Configure embedding and ontology encoders in those tool implementations.
)
config = Config(k=5, max_rounds=3)
```

表型适配器输出临床表现、明确阴性表现及对应的原文片段；HPO 标识符由配置的本体映射工具分配。辅助模型负责从文本提取临床表现，而非生成本体标识符。

在未配置独立辅助端点的最小部署中，疾病匹配检查使用 `reasoner`；表现提取与片段处理仍是可选工具。构造参数 `worker` 是同一 `reasoner` 对象的兼容别名。独立模型应通过 `auxiliary` 传入，而非 `worker`。

完整模板参见 [Prompt 参考](prompts.md)，可运行的示例输入参见 [`minimal_dataset`](../../minimal_dataset/README.md)。

## 联网与来源配置

允许联网时，可通过已配置的外部文献、知识和网页搜索服务补充本地证据资源。所选配置需要时启用公共 PubCaseFinder 服务。

不允许外网访问时，关闭外部服务请求，推理使用本地部署的模型、索引和诊断工具。可用的本地病例文献语料（包括 PMC-Patients）支持不依赖实时 PubMed 请求的检索。只有具备本地实现及所需数据的服务才在这一设置中使用。诊断流程保持一致，可用证据来源则随设置变化。

`Config.allow_external_requests` 默认为 `True`，允许已配置的外部服务，并兼容现有工具适配器。设为 `False` 后，仅保留明确声明 `requires_external_access=False` 的工具；外部工具和未声明访问属性的工具会在推理前被筛除。推理模型和辅助模型也必须声明为本地访问，否则诊断会在任何模型或工具调用前停止。

`ConfiguredTool` 为已有工具适配器附加来源名称、访问属性和 `enabled` 开关。`enabled=False` 在两种设置下都会排除该来源。它不下载数据，也不替代服务后端实现。以下配置接收实现既有工具协议的部署适配器，假定 PhenoBrain、病例及知识索引部署在本地，PubCaseFinder 使用公共服务。应按实际后端填写访问属性，包括本地 MCP 代理转发的请求。

```python
from genesis import Config, Models, Tools
from genesis.llm.openai_compat import OpenAIChat
from genesis.tools import ConfiguredTool, ModelPhenotypeExtractor, ModelEvidenceSummarizer

reasoner = OpenAIChat("http://localhost:8000/v1", "GENESIS-R1",
                      requires_external_access=False)
auxiliary = OpenAIChat("http://localhost:8001/v1", "Qwen3-8B", thinking=False,
                       requires_external_access=False)
models = Models(reasoner=reasoner, auxiliary=auxiliary)

def configure_sources(phenobrain, pubcasefinder, local_knowledge,
                      pubmed, wikipedia, web_search, local_cases):
    return Tools(
        phenotype_extractor=ModelPhenotypeExtractor(auxiliary),
        summarizer=ModelEvidenceSummarizer(auxiliary),
        expert_methods=[
            ConfiguredTool(phenobrain, "PhenoBrain", requires_external_access=False),
            ConfiguredTool(pubcasefinder, "PubCaseFinder", requires_external_access=True),
        ],
        knowledge_sources=[
            ConfiguredTool(local_knowledge, "Local knowledge", requires_external_access=False),
            ConfiguredTool(pubmed, "PubMed", requires_external_access=True),
            ConfiguredTool(wikipedia, "Wikipedia", requires_external_access=True),
            ConfiguredTool(web_search, "General web search", requires_external_access=True,
                           enabled=False),
        ],
        case_indices=[
            ConfiguredTool(local_cases, "Local cases", requires_external_access=False),
        ],
    )

config = Config(k=5, max_rounds=3, allow_external_requests=False)
```

访问开关依据适配器的声明筛选组件，不是操作系统防火墙。需要强制网络隔离的部署还应在运行环境中限制外网流量。模型端点与检索来源分别声明访问属性；部署网络内的 API 不一定使用公共互联网。辅助工具适配器继承所用模型的访问属性。

仓库附带的文件索引示例可通过 `python3 examples/run_dataset.py --network disabled` 运行。使用本地模型端点时，另加 `--model-access local`，使用辅助端点时再加 `--auxiliary-access local`。外部工具需要显式配置；允许联网不会自动启用未接入的服务。两种设置的证据覆盖范围可能不同。
