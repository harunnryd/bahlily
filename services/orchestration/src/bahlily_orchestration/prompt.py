from __future__ import annotations

from bahlily_orchestration.models import TemplateSpec, TranscriptSegment


def build_prompt(segments: list[TranscriptSegment], template: TemplateSpec) -> list[dict[str, str]]:
    system_content = template.system_prompt
    if template.focus_instructions:
        system_content = f"{system_content}\n\n{template.focus_instructions}"

    messages = [{"role": "system", "content": system_content}]

    for example in template.few_shot_examples:
        messages.append({"role": "user", "content": example["input"]})
        messages.append({"role": "assistant", "content": example["output"]})

    ordered_segments = sorted(segments, key=lambda segment: segment.segment_id)
    transcript_text = "\n".join(
        f"[{segment.speaker or 'Unknown'}] {segment.text}" for segment in ordered_segments
    )
    messages.append({"role": "user", "content": transcript_text})

    return messages
