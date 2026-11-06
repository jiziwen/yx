<!-- 供应商验证准备包的入口、素材隐私边界与运行语义。 -->
# 供应商验证准备

运行 `uv run python -m evals.prepare` 校验 8 个样例定义并生成 `.data/evals/preparation.json`。这是 M0 的准备检查；状态始终为 prepared_not_evaluated，不会使用真实模型或伪造质量/费用成绩。

样例覆盖单人正面、侧面、否定约束、双人身份区分/不同光线，以及未知提交、明确拒绝和撤销后迟到结果。评分与证据标准见 rubrics/provider-review.md。

下一步在 M1 准备真实授权素材清单、选定供应商和模型，设置验证预算后采集质量、成本、恢复证据并确认放行门槛。私有素材、输出和完整调用正文不提交 Git。

## M1 · 302.AI 联调准备

`uv run python -m evals.preflight --provider ai302-image` 检查候选配置和凭证是否存在，不发送图片或付费请求。默认缺少真实素材时状态为 blocked_for_measurement。凭证来自进程环境或后端受忽略的 .env，报告不包含凭证值。

使用私有目录的授权清单继续检查：

```sh
uv run python -m evals.preflight --provider ai302-image \
  --manifest /absolute/private-tests/fixtures.json --require-ready
```

清单字段示意（须按实际授权、摘要和有效期填写；以下不是可用授权凭证）：

```json
{
  "schema_version": 1,
  "version": "authorized-samples-v1",
  "fixtures": [{
    "key": "person_a/front",
    "file": "person-a/front.png",
    "sha256": "填写原文件的64位小写SHA256",
    "subject_id": "person_a",
    "authorization_version": "实际授权记录版本",
    "authorized_providers": ["ai302-image"],
    "authorized_until": "2026-10-23T00:00:00+08:00"
  }]
}
```

样例需要 person_a/front、person_a/side、person_b/front、person_b/side；每项人物标识必须与引用键对应。图片只允许位于清单目录以内，工具复核原始摘要、授权供应商/有效期、格式与大小。报告写入后端 .data/evals/provider-preflight.json，仅保留非敏感准备状态，准备通过依然 quality_approved=false。

确定性恢复测试见 tests/test_m1_runtime.py；使用合成图片和 MockTransport 验证真实 302 适配器字段、故障、在途槽位、查询竞争和权益，不产生真实模型评分。真实测量需要人工逐人物复核、重复采样与账单证据。

M2固定集为resources/agent/m2-cases.json，默认运行 `uv run python -m evals.m2`，只跑隔离工程约束；`--live --samples 2`才读取后台白名单模型配置进行真实抽样，0图片/无用户照片。`--baseline <report>`记录逐题差异，`--case`仅用于单题诊断，不替代完整重复抽样。报告位于.data/evals/m2，保留可见合成答复供质量复核，不记录隐藏推理或凭证。quality_approved不会自动置true。

已有报告逐次比较可执行 `uv run python -m evals.compare --baseline <report> --candidate <report>`，只生成相邻comparison.json，不重复付费调用或覆盖原结果；比较键为case_id+sample，避免最后一次成功掩盖早先失败。
