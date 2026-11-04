from project_validator.core import Context, Result
from project_validator.ecosystems import practice
from project_validator.rules import CompilerExtensions


@practice(
    name="cxx-extensions",
    description="Compiler extensions are disabled (-std=c++NN rather than -std=gnu++NN)",
    rule=CompilerExtensions,
)
def cxx_extensions(rule: CompilerExtensions, context: Context) -> Result:
    return rule.judge(context)
