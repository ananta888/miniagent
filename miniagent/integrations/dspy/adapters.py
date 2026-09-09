import dspy

from miniagent.prompts.strategy import PromptArtifact


class RawTextAdapter(dspy.Adapter):
    """One text output, including raw/fenced code, without JSON or field markers."""

    def format(self, signature, demos, inputs):
        artifact = export_prompt(signature, demos)
        return [{"role": "user", "content": artifact.render({k: str(v) for k, v in inputs.items()})}]

    def parse(self, signature, completion):
        if len(signature.output_fields) != 1:
            raise ValueError("RawTextAdapter needs one text output; use a DSPy adapter for other signatures")
        return {next(iter(signature.output_fields)): completion}


def export_prompt(signature, demos) -> PromptArtifact:
    outputs = list(signature.output_fields)
    if len(outputs) != 1 or signature.output_fields[outputs[0]].annotation is not str:
        raise ValueError("Portable raw-text prompts require one string output field")
    names = [*signature.input_fields, *outputs]
    return PromptArtifact(instructions=signature.instructions, input_fields=list(signature.input_fields),
                          output_field=outputs[0], demos=[{name: str(demo[name]) for name in names} for demo in demos])
