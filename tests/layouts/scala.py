"""Kinds of Scala project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="sbt Scala",
        files={
            "build.sbt": 'scalaVersion := "3.3.5"\n',
            "project/build.properties": "sbt.version=1.10.7\n",
            "src/main/scala/Shop.scala": "object Shop\n",
        },
        languages=frozenset({"Scala"}),
        build_systems=frozenset({"sbt"}),
    ),
    ProjectLayout(
        name="Mill Scala",
        files={
            "build.mill": "package build\nimport mill._, scalalib._\nobject shop extends ScalaModule {\n"
            '  def scalaVersion = "3.3.5"\n}\n',
            "shop/src/Shop.scala": "object Shop\n",
        },
        languages=frozenset({"Scala"}),
        build_systems=frozenset({"Mill"}),
    ),
    ProjectLayout(
        name="scala-cli Scala",
        files={"project.scala": "//> using scala 3.3.5\n", "Shop.scala": "object Shop\n"},
        languages=frozenset({"Scala"}),
        build_systems=frozenset({"scala-cli"}),
    ),
)
