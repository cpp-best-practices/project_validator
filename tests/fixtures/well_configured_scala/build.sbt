ThisBuild / scalaVersion := "3.3.5"
ThisBuild / organization := "com.example"

lazy val root = (project in file("."))
  .settings(
    name := "shop",
    scalacOptions ++= Seq("-deprecation", "-feature", "-Wunused:all", "-Werror"),
    semanticdbEnabled := true,
    coverageMinimumBranchTotal := 90,
    coverageFailOnMinimum := true,
    libraryDependencies += "org.scalameta" %% "munit" % "1.1.0" % Test
  )
