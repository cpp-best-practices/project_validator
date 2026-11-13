"""EditorConfig (`.editorconfig`): the file the formatters of several languages read their style from (dotnet format,
shfmt), so a project that has one defines its style there."""

from __future__ import annotations

from project_validator.facts.settings import file_reader

EDITORCONFIG = file_reader("EditorConfig", (".editorconfig",))
